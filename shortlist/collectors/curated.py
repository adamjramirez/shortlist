"""Curated career page sources collector.

Fetches jobs from manually-curated career page URLs stored in
career_page_sources. Supports Ashby, Greenhouse, Lever, and direct
career pages. Reports per-source results via an optional callback.
"""
import logging
from typing import Callable

from shortlist.collectors.base import RawJob
from shortlist.collectors.career_page import (
    fetch_ashby_jobs,
    fetch_greenhouse_jobs,
    fetch_lever_jobs,
    fetch_career_page,
)

logger = logging.getLogger(__name__)


class CuratedSourcesCollector:
    """Fetches jobs from a list of curated career page source records.

    Args:
        sources: List of dicts from pgdb.get_active_career_page_sources().
        on_fetched: Optional callback(career_url, jobs, error_str | None)
                    called once per source after each fetch attempt.
    """

    def __init__(
        self,
        sources: list[dict],
        on_fetched: Callable[[str, list[RawJob], str | None], None] | None = None,
    ):
        self.sources = sources
        self.on_fetched = on_fetched

    def fetch_new(self) -> list[RawJob]:
        """Fetch jobs from all active curated sources. Returns combined list."""
        all_jobs: list[RawJob] = []

        for source in self.sources:
            url = source["career_url"]
            ats = source.get("ats")
            slug = source.get("slug")
            company = source["company_name"]

            try:
                jobs = self._fetch_one(ats, slug, url, company)
                all_jobs.extend(jobs)
                if self.on_fetched:
                    self.on_fetched(url, jobs, None)
                logger.info(f"Curated: {company} → {len(jobs)} jobs")
            except Exception as e:
                error = str(e)
                logger.warning(f"Curated: {company} fetch failed — {error}")
                if self.on_fetched:
                    self.on_fetched(url, [], error)

        return all_jobs

    def _fetch_one(
        self, ats: str | None, slug: str | None, url: str, company: str
    ) -> list[RawJob]:
        if ats == "ashby" and slug:
            return fetch_ashby_jobs(slug)
        if ats == "greenhouse" and slug:
            return fetch_greenhouse_jobs(slug)
        if ats == "lever" and slug:
            return fetch_lever_jobs(slug)
        # direct or unknown — fetch the page and let the detector handle it
        return fetch_career_page(url)
