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


def _work_type_filter(config) -> str | None:
    """Derive LinkedIn f_WT filter from user's location preferences.

    Returns f_WT value string or None (omit filter = all work types).
    | remote | local_cities | f_WT  | Meaning                |
    |--------|-------------|-------|------------------------|
    | True   | empty       | "2"   | Remote only            |
    | True   | has cities  | "2,3" | Remote + hybrid        |
    | False  | has cities  | "1,3" | On-site + hybrid       |
    | False  | empty       | None  | All work types         |
    """
    loc = config.filters.location
    remote = loc.remote
    has_cities = bool(loc.local_cities)
    if remote and not has_cities:
        return "2"
    elif remote and has_cities:
        return "2,3"
    elif not remote and has_cities:
        return "1,3"
    else:
        return None


def searches_from_config(config) -> list[dict]:
    """Build LinkedIn search params from track search_queries in config."""
    f_wt = _work_type_filter(config)
    searches = []
    seen = set()
    for track in config.tracks.values():
        for query in track.search_queries:
            if query.lower() in seen:
                continue
            seen.add(query.lower())
            search = {
                "keywords": query,
                "f_E": "4,5,6",   # mid-senior, director, executive
            }
            if f_wt is not None:
                search["f_WT"] = f_wt
            searches.append(search)
    fallback = {"keywords": "Engineering Manager", "f_E": "4,5"}
    if f_wt is not None:
        fallback["f_WT"] = f_wt
    return searches or [fallback]

# Region → country expansion for multi-country search.
# When a user picks a region, we run separate searches per country for
# thorough coverage (LinkedIn's region strings skew toward large markets).
# Max 1 page per country to keep request count reasonable.
REGION_COUNTRIES: dict[str, list[str]] = {
    "DACH": ["Germany", "Austria", "Switzerland"],
    "Scandinavia": ["Denmark", "Norway", "Sweden", "Finland"],
    # Larger regions capped at ~10 countries (biggest job markets first)
    # to keep request count reasonable (~30 requests for 3 queries).
    "European Union": [
        "Germany", "France", "Netherlands", "Spain", "Ireland", "Poland",
        "Italy", "Belgium", "Austria", "Portugal",
    ],
    "Europe": [
        "United Kingdom", "Germany", "France", "Netherlands", "Switzerland",
        "Ireland", "Spain", "Poland", "Italy", "Sweden",
    ],
    "APAC": [
        "India", "Singapore", "Australia", "Japan", "South Korea",
        "Hong Kong", "New Zealand",
    ],
    "LATAM": [
        "Brazil", "Mexico", "Argentina", "Colombia", "Chile", "Peru",
    ],
}

MAX_429_RETRIES = 2
BACKOFF_ON_429 = 30.0


class LinkedInCollector:
    """Collects jobs from LinkedIn's guest API. No auth required."""

    def __init__(self, searches: list[dict] | None = None, max_pages: int = 2,
                 time_filter: str = "r604800", fetch_descriptions: bool = False,
                 location: str = "United States"):
        self.searches = searches or DEFAULT_SEARCHES
        self.max_pages = max_pages
        self.time_filter = time_filter
        self.fetch_descriptions = fetch_descriptions
        self.location = location
        self._seen_ids: set[str] = set()

    def _resolve_locations(self) -> list[str]:
        """Expand region to country list, or return single-country list."""
        return REGION_COUNTRIES.get(self.location, [self.location])

    def fetch_new(self) -> list[RawJob]:
        """Fetch jobs from all configured searches across all locations.

        Request budget: len(searches) × len(locations) × pages_per_country.
        For regions, pages_per_country=1, so Europe(10) × 3 queries = 30 requests.
        Single country uses self.max_pages (default 2), so 3 queries × 2 = 6 requests.
        """
        locations = self._resolve_locations()
        is_multi = len(locations) > 1
        total_requests = len(self.searches) * len(locations) * (1 if is_multi else self.max_pages)
        if total_requests > 40:
            logger.warning(
                f"LinkedIn: high request count ({total_requests}) — "
                f"{len(self.searches)} searches x {len(locations)} locations. "
                f"Consider reducing search queries."
            )
        all_jobs = []

        for location in locations:
            for search in self.searches:
                try:
                    # For multi-country: 1 page per country to stay within rate limits
                    max_pages = 1 if is_multi else self.max_pages
                    jobs = self._run_search(search, location=location, max_pages=max_pages)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(
                        f"LinkedIn search failed for {search.get('keywords')} "
                        f"in {location}: {e}"
                    )
                    continue

        logger.info(
            f"LinkedIn: collected {len(all_jobs)} jobs from "
            f"{len(self.searches)} searches x {len(locations)} location(s)"
        )
        return all_jobs

    def _run_search(self, search_params: dict, location: str | None = None,
                    max_pages: int | None = None) -> list[RawJob]:
        """Run a single search query across multiple pages."""
        location = location or self.location
        max_pages = max_pages if max_pages is not None else self.max_pages
        jobs = []
        for page in range(max_pages):
            params = {
                "location": location,
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
        dates = re.findall(
            r'<time[^>]*datetime="([^"]+)"[^>]*>', html
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
            posted_at = dates[i] if i < len(dates) else None

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
                posted_at=posted_at,
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
