"""LinkedIn Jobs collector using the unauthenticated guest API."""
import logging
import re
import time
from html import unescape

from shortlist.collectors.base import BaseCollector, RawJob
from shortlist import http

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# LinkedIn filter codes
# f_WT: 1=on-site, 2=remote, 3=hybrid
# f_E: 1=internship, 2=entry, 3=associate, 4=mid-senior, 5=director, 6=executive
# f_TPR: r86400=past 24h, r604800=past week, r2592000=past month

DEFAULT_SEARCHES: list[dict] = []  # populated from config tracks


def searches_from_config(config) -> list[dict]:
    """Build LinkedIn search params from track search_queries in config."""
    searches = []
    seen = set()
    for track in config.tracks.values():
        for query in track.search_queries:
            if query.lower() in seen:
                continue
            seen.add(query.lower())
            searches.append({
                "keywords": query,
                "f_WT": "2",       # remote
                "f_E": "4,5,6",   # mid-senior, director, executive
            })
    return searches or [{"keywords": "Engineering Manager", "f_WT": "2", "f_E": "4,5"}]

MAX_429_RETRIES = 2
BACKOFF_ON_429 = 30.0


class LinkedInCollector:
    """Collects jobs from LinkedIn's guest API. No auth required."""

    def __init__(self, searches: list[dict] | None = None, max_pages: int = 2,
                 time_filter: str = "r604800", fetch_descriptions: bool = False):
        self.searches = searches or DEFAULT_SEARCHES
        self.max_pages = max_pages
        self.time_filter = time_filter
        self.fetch_descriptions = fetch_descriptions
        self._seen_ids: set[str] = set()

    def fetch_new(self) -> list[RawJob]:
        """Fetch jobs from all configured searches."""
        all_jobs = []
        for search in self.searches:
            try:
                jobs = self._run_search(search)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.warning(f"LinkedIn search failed for {search.get('keywords')}: {e}")
                continue

        logger.info(f"LinkedIn: collected {len(all_jobs)} jobs from {len(self.searches)} searches")
        return all_jobs

    def _run_search(self, search_params: dict) -> list[RawJob]:
        """Run a single search query across multiple pages."""
        jobs = []
        for page in range(self.max_pages):
            params = {
                "location": "United States",
                "f_TPR": self.time_filter,
                "start": str(page * 25),
                **search_params,
            }

            resp = self._get_with_retry(SEARCH_URL, params)
            if resp is None:
                break

            page_jobs = self._parse_search_results(resp.text)
            if not page_jobs:
                break

            jobs.extend(page_jobs)

        return jobs

    def _get_with_retry(self, url: str, params: dict | None = None):
        """GET with 429 retry + backoff. Rate limiting is handled by http module."""
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                resp = http.get(url, params=params)
                if resp.status_code == 429:
                    if attempt < MAX_429_RETRIES:
                        logger.info(f"LinkedIn 429 — backing off {BACKOFF_ON_429}s (attempt {attempt + 1})")
                        time.sleep(BACKOFF_ON_429)
                        continue
                    else:
                        logger.warning(f"LinkedIn 429 — giving up after {MAX_429_RETRIES + 1} attempts")
                        return None
                resp.raise_for_status()
                return resp
            except Exception as e:
                logger.warning(f"LinkedIn request failed: {e}")
                return None
        return None

    def _parse_search_results(self, html: str) -> list[RawJob]:
        """Parse LinkedIn search results HTML into RawJob objects."""
        jobs = []

        titles = re.findall(
            r'<a[^>]*class="base-card__full-link[^"]*"[^>]*>\s*(.*?)\s*</a>',
            html, re.DOTALL,
        )
        companies = re.findall(
            r'<h4[^>]*base-search-card__subtitle[^>]*>\s*(?:<a[^>]*>)?\s*(.*?)\s*(?:</a>)?\s*</h4>',
            html, re.DOTALL,
        )
        locations = re.findall(
            r'<span class="job-search-card__location">\s*(.*?)\s*</span>', html
        )
        links = re.findall(
            r'<a[^>]*class="base-card__full-link[^"]*"[^>]*href="([^"]+)"', html
        )
        job_ids = re.findall(
            r'data-entity-urn="urn:li:jobPosting:(\d+)"', html
        )

        count = min(len(titles), len(companies), len(links))
        for i in range(count):
            job_id = job_ids[i] if i < len(job_ids) else ""

            if job_id and job_id in self._seen_ids:
                continue
            if job_id:
                self._seen_ids.add(job_id)

            title = _clean_html(titles[i])
            company = _clean_html(companies[i])
            location = locations[i].strip() if i < len(locations) else None
            url = links[i].split("?")[0]

            description = ""
            if self.fetch_descriptions and job_id:
                description = self._fetch_description(job_id)

            if not description:
                description = f"{title} at {company}. Location: {location or 'Unknown'}."

            jobs.append(RawJob(
                title=title,
                company=company,
                url=url,
                description=description,
                source="linkedin",
                location=location,
            ))

        return jobs

    def _fetch_description(self, job_id: str) -> str:
        """Fetch full job description from the detail API."""
        resp = self._get_with_retry(DETAIL_URL.format(job_id=job_id))
        if resp is None:
            return ""

        try:
            desc_match = re.search(
                r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                resp.text, re.DOTALL,
            )
            if desc_match:
                desc = _clean_html(desc_match.group(1))
                if len(desc) > 50:
                    return desc

            desc_match = re.search(
                r'class="description__text[^"]*"[^>]*>(.*?)</section>',
                resp.text, re.DOTALL,
            )
            if desc_match:
                return _clean_html(desc_match.group(1))

            criteria = re.findall(
                r'description__job-criteria-text[^>]*>(.*?)<', resp.text
            )
            if criteria:
                return f"Job criteria: {', '.join(c.strip() for c in criteria)}"

        except Exception as e:
            logger.debug(f"Failed to parse description for job {job_id}: {e}")

        return ""


def fetch_description_for_url(url: str) -> str:
    """Fetch the full job description for a LinkedIn job URL.

    Extracts the job ID from the URL and fetches from the detail API.
    Returns empty string on failure.
    """
    match = re.search(r"/view/[^/]+-(\d+)", url)
    if not match:
        match = re.search(r"(\d{8,})", url)
    if not match:
        return ""

    job_id = match.group(1)
    collector = LinkedInCollector()
    return collector._fetch_description(job_id)


def _clean_html(text: str) -> str:
    """Strip HTML tags, unescape entities, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
