"""Proactive job expiry checking — visits job URLs to detect closed listings.

All HTTP calls go through shortlist.http (rate limiting + proxy auto-applied).
Runs in the scheduler background between pipeline runs.
"""
import json
import logging
import re

from shortlist import http
from shortlist import pgdb

logger = logging.getLogger(__name__)

# Regex patterns for extracting org slug + job ID from ATS URLs
_GREENHOUSE_PATTERN = re.compile(
    r"https?://(?:job-boards|boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)",
    re.I,
)
_LEVER_PATTERN = re.compile(
    r"https?://jobs\.lever\.co/([^/]+)/([a-z0-9\-]+)",
    re.I,
)


def _parse_greenhouse_api_url(url: str) -> str | None:
    """Return Greenhouse API URL if job is on greenhouse.io, else None.

    Native greenhouse.io URLs → construct API endpoint.
    Custom company domains (e.g. samsara.com) → return None (use stored URL).
    """
    m = _GREENHOUSE_PATTERN.match(url)
    if not m:
        return None
    slug, job_id = m.group(1), m.group(2)
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"


def _parse_lever_api_url(url: str) -> str | None:
    """Return Lever API URL for individual job check, or None if not a Lever URL."""
    m = _LEVER_PATTERN.match(url)
    if not m:
        return None
    slug, job_id = m.group(1), m.group(2)
    return f"https://api.lever.co/v0/postings/{slug}/{job_id}"


def check_job_url(url: str, sources_seen: list[str]) -> bool | None:
    """Check if a job URL is still active.

    Returns:
        True  — job is active
        False — job is expired/gone
        None  — unknown (network error, no proxy, unsupported source — do not close)

    All HTTP via shortlist.http. LinkedIn proxy auto-applied by PROXY_DOMAINS.
    """
    try:
        if "linkedin" in sources_seen:
            resp = http.head(url)
            return resp.status_code == 200

        if "greenhouse" in sources_seen:
            api_url = _parse_greenhouse_api_url(url)
            check_url = api_url if api_url else url
            resp = http.head(check_url)
            return resp.status_code == 200

        if "lever" in sources_seen:
            api_url = _parse_lever_api_url(url)
            if not api_url:
                return None
            resp = http.head(api_url)
            return resp.status_code == 200

        if "ashby" in sources_seen:
            resp = http.get(url, timeout=5)
            # Active jobs: "<title>Job Title @ Company</title>"
            # Expired jobs: "<title>Jobs</title>"
            title_match = re.search(r"<title>([^<]*)</title>", resp.text, re.I)
            if not title_match:
                return None
            return "@" in title_match.group(1)

        # HN and other sources have no useful URL signal
        return None

    except Exception as e:
        logger.debug("Expiry check failed for %s: %s", url, e)
        return None


def _run_batch(conn, limit: int = 20) -> dict:
    """Run expiry checks on a batch of jobs using an existing connection."""
    jobs = pgdb.get_jobs_for_expiry_check(conn, limit=limit)
    checked = closed = errors = 0

    for job in jobs:
        sources = job["sources_seen"]
        if isinstance(sources, str):
            try:
                sources = json.loads(sources)
            except (ValueError, TypeError):
                sources = []

        try:
            result = check_job_url(job["url"], sources)
            if result is None:
                # Unknown — still mark as checked so we don't retry immediately
                pgdb.mark_expiry_checked(conn, job_id=job["id"], is_closed=False)
                errors += 1
            elif result is False:
                pgdb.mark_expiry_checked(conn, job_id=job["id"], is_closed=True,
                                         closed_reason="url_check")
                closed += 1
            else:
                pgdb.mark_expiry_checked(conn, job_id=job["id"], is_closed=False)
            checked += 1
        except Exception as e:
            logger.warning("Expiry check error for job %s: %s", job["id"], e)
            errors += 1

    conn.commit()
    return {"checked": checked, "closed": closed, "errors": errors}


def check_expiry_batch(db_url: str, limit: int = 20) -> dict:
    """Open a DB connection, check a batch of jobs, close the connection.

    Safe to call from asyncio.to_thread — opens and closes its own connection.
    Returns {"checked": N, "closed": N, "errors": N}.
    """
    conn = pgdb.get_pg_connection(db_url)
    try:
        return _run_batch(conn, limit=limit)
    except Exception as e:
        logger.warning("check_expiry_batch failed: %s", e)
        return {"checked": 0, "closed": 0, "errors": 1}
    finally:
        conn.close()
