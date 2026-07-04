"""Getro VC job-board collector.

Getro powers many VC portfolio job boards (Thrive Capital, etc.) through an
open JSON API:

    POST https://api.getro.com/api/v2/collections/{network_id}/search/jobs
    body: {"hitsPerPage": N, "page": P, "query": "<role text>"}

Each result carries the role title, the company (``organization.name``), the
**real ATS url** (greenhouse/lever/…) — good for dedup and expiry — plus
location, ``created_at``, and compensation. The ``query`` param filters
server-side, so we can target senior roles (CTO / VP Engineering / …) directly.

This reaches VC-portfolio startups that don't surface in HN/LinkedIn, without
the anti-scraping walls of the aggregator front-ends (levels.fyi, startup.jobs).
"""
import logging
from datetime import datetime, timezone

from shortlist.collectors.base import RawJob
from shortlist.collectors.career_page import detect_ats
from shortlist import http

logger = logging.getLogger(__name__)

GETRO_API = "https://api.getro.com/api/v2/collections/{cid}/search/jobs"

# Elite VC-portfolio boards on Getro (name, collection_id). Extend freely — a
# board's id is in its page's __NEXT_DATA__ at props.pageProps.network.id.
GETRO_NETWORKS = [
    {"name": "Thrive Capital", "collection_id": 2105},
    {"name": "General Catalyst", "collection_id": 222},
    {"name": "Craft Ventures", "collection_id": 340},
]

# Server-side query terms that narrow to senior/leadership roles before the
# title_filter runs (Getro searches full-text over title + description).
DEFAULT_GETRO_QUERIES = ["engineering leadership", "vp engineering", "chief technology officer"]

# Getro returns 406 unless the request explicitly accepts JSON (the shared
# http client defaults to Accept: text/html).
_GETRO_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://jobs.getro.com",
    "Referer": "https://jobs.getro.com/",
}


def _format_getro_salary(job: dict) -> str | None:
    """Build a salary string from Getro compensation cents, or None."""
    lo = job.get("compensation_amount_min_cents")
    hi = job.get("compensation_amount_max_cents")
    if not lo and not hi:
        return None
    currency = (job.get("compensation_currency") or "USD").upper()
    sym = "$" if currency in ("USD", "CAD", "AUD") else ""

    def k(cents):
        return f"{sym}{round(cents / 100 / 1000)}k" if cents else None

    lo_s, hi_s = k(lo), k(hi)
    if lo_s and hi_s:
        return f"{lo_s}-{hi_s} {currency}" if not sym else f"{lo_s}-{hi_s}"
    return lo_s or hi_s


def _getro_job_to_rawjob(job: dict) -> RawJob | None:
    """Convert one Getro API job dict to a RawJob, or None if unusable."""
    url = (job.get("url") or "").split("?")[0]
    title = job.get("title")
    if not url or not title:
        return None

    org = job.get("organization") or {}
    company = org.get("name") or "Unknown"

    locations = job.get("searchable_locations") or job.get("locations") or []
    location = locations[0] if locations else None

    posted_at = None
    created = job.get("created_at")
    if created:
        try:
            posted_at = datetime.fromtimestamp(int(created), tz=timezone.utc).date().isoformat()
        except (ValueError, OSError, OverflowError):
            posted_at = None

    # The url is a real ATS posting — tag the source with the detected ATS so
    # expiry checking and cross-source dedup work; fall back to "getro".
    source = detect_ats(url) or "getro"

    description = f"{title} at {company}."
    if location:
        description += f" Location: {location}."

    return RawJob(
        title=title,
        company=company,
        url=url,
        description=description,
        source=source,
        location=location,
        salary_text=_format_getro_salary(job),
        posted_at=posted_at,
    )


class GetroCollector:
    """Collects jobs from Getro-powered VC job boards.

    Args:
        networks: list of {"name": str, "collection_id": int}.
        queries: role search strings (server-side filter). Default [""] = all.
        title_filter: optional callable(title) -> bool applied after parsing.
        max_pages: pages to pull per (network, query).
        hits_per_page: results per page.
    """

    def __init__(self, networks, queries=None, title_filter=None,
                 max_pages: int = 3, hits_per_page: int = 50):
        self.networks = networks
        self.queries = queries or [""]
        self.title_filter = title_filter
        self.max_pages = max_pages
        self.hits_per_page = hits_per_page
        self._seen_urls: set[str] = set()

    def fetch_new(self) -> list[RawJob]:
        jobs: list[RawJob] = []
        for network in self.networks:
            cid = network["collection_id"]
            name = network.get("name", str(cid))
            for query in self.queries:
                jobs.extend(self._fetch_network_query(cid, name, query))
        return jobs

    def _fetch_network_query(self, cid, name, query) -> list[RawJob]:
        out: list[RawJob] = []
        for page in range(self.max_pages):
            try:
                resp = http.post(
                    GETRO_API.format(cid=cid),
                    json={"hitsPerPage": self.hits_per_page, "page": page, "query": query},
                    headers=_GETRO_HEADERS,
                )
            except Exception as e:
                logger.warning(f"Getro {name} q={query!r} page={page} failed: {e}")
                break
            if resp.status_code != 200:
                logger.warning(f"Getro {name} q={query!r} page={page} → {resp.status_code}")
                break
            page_jobs = (resp.json().get("results") or {}).get("jobs") or []
            if not page_jobs:
                break
            for j in page_jobs:
                rj = _getro_job_to_rawjob(j)
                if rj is None or rj.url in self._seen_urls:
                    continue
                if self.title_filter and not self.title_filter(rj.title):
                    continue
                self._seen_urls.add(rj.url)
                out.append(rj)
            if len(page_jobs) < self.hits_per_page:
                break  # last page
        logger.info(f"Getro {name} q={query!r} → {len(out)} jobs")
        return out
