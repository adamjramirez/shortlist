"""Proactive job expiry checking — visits job URLs to detect closed listings.

All HTTP calls go through shortlist.http (rate limiting + proxy auto-applied).
Runs in the scheduler background between pipeline runs.
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta

from shortlist import http
from shortlist import pgdb

logger = logging.getLogger(__name__)

# Jobs seen within this window are skipped — transient network errors more likely
# than genuine removal. last_seen_stale sweep picks up truly old jobs.
_RECENCY_SKIP_HOURS = 24

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
        True  — explicit live signal (200 with valid content)
        False — explicit gone signal (404 or confirmed closed page)
        None  — unknown (transient error, bot challenge, redirect, unsupported source)
                Do NOT close on None.

    All HTTP via shortlist.http. LinkedIn proxy auto-applied by PROXY_DOMAINS.

    Each source has its own "gone" signal — only a definitive 404 (or equivalent)
    returns False. Anything ambiguous (403/429/5xx/redirect/timeout) returns None.
    """
    try:
        if "linkedin" in sources_seen:
            resp = http.head(url)
            if resp.status_code == 200:
                return True
            if resp.status_code == 404:
                return False
            # 403/429/5xx/3xx — proxy flake, bot challenge, rate limit → unknown
            return None

        if "greenhouse" in sources_seen:
            api_url = _parse_greenhouse_api_url(url)
            check_url = api_url if api_url else url
            resp = http.head(check_url)
            if resp.status_code == 200:
                return True
            if resp.status_code == 404:
                return False
            return None

        if "lever" in sources_seen:
            api_url = _parse_lever_api_url(url)
            if not api_url:
                return None
            resp = http.head(api_url)
            if resp.status_code == 200:
                return True
            if resp.status_code == 404:
                return False
            return None

        if "ashby" in sources_seen:
            resp = http.get(url, timeout=5)
            if resp.status_code != 200:
                # Non-200 from Ashby — rate limit, error, or redirect → unknown
                return None
            # Active jobs: "<title>Job Title @ Company</title>"
            # Expired jobs: "<title>Jobs</title>"
            title_match = re.search(r"<title>([^<]*)</title>", resp.text, re.I)
            if not title_match:
                return None
            title = title_match.group(1)
            if title.strip() == "Jobs":
                return False
            if "@" in title:
                return True
            # Unrecognised title format → unknown
            return None

        # HN and other sources have no useful URL signal
        return None

    except Exception as e:
        logger.debug("Expiry check failed for %s: %s", url, e)
        return None


def _run_batch(conn, limit: int = 20) -> dict:
    """Run expiry checks on a batch of jobs using an existing connection.

    Returns {checked, closed, live, unknown, skipped_recent, errors}:
      - checked:        HTTP-backed decisions made (= closed + live + unknown)
      - closed:         explicit 404 → marked closed
      - live:           explicit 200 → confirmed active
      - unknown:        HTTP call returned None (3xx/4xx-non-404/5xx/parse fail)
      - skipped_recent: no HTTP call because last_seen < 24h ago
      - errors:         exceptions raised during processing (true failures)
    """
    jobs = pgdb.get_jobs_for_expiry_check(conn, limit=limit)
    checked = closed = live = unknown = skipped_recent = errors = 0
    now = datetime.now(timezone.utc)
    recency_cutoff = now - timedelta(hours=_RECENCY_SKIP_HOURS)

    for job in jobs:
        sources = job["sources_seen"]
        if isinstance(sources, str):
            try:
                sources = json.loads(sources)
            except (ValueError, TypeError):
                sources = []

        # 5b — Recency skip: last_seen within 24h → transient errors far more
        # likely than genuine removal. Skip the HTTP call entirely.
        last_seen = job.get("last_seen")
        if last_seen is not None:
            if isinstance(last_seen, datetime) and last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if isinstance(last_seen, datetime) and last_seen > recency_cutoff:
                logger.debug(
                    "url_check skip (recent): job=%d last_seen=%s",
                    job["id"], last_seen.isoformat(),
                )
                skipped_recent += 1
                continue

        primary_source = next(
            (s for s in ("linkedin", "greenhouse", "lever", "ashby") if s in sources),
            sources[0] if sources else "unknown",
        )

        try:
            result = check_job_url(job["url"], sources)
            if result is None:
                pgdb.mark_expiry_checked(conn, job_id=job["id"], is_closed=False)
                logger.debug(
                    "url_check unknown: job=%d source=%s url=%s",
                    job["id"], primary_source, job["url"],
                )
                unknown += 1
            elif result is False:
                pgdb.mark_expiry_checked(conn, job_id=job["id"], is_closed=True,
                                         closed_reason="url_check")
                logger.info(
                    "url_check close: job=%d source=%s url=%s",
                    job["id"], primary_source, job["url"],
                )
                closed += 1
            else:
                pgdb.mark_expiry_checked(conn, job_id=job["id"], is_closed=False)
                logger.debug(
                    "url_check live: job=%d source=%s url=%s",
                    job["id"], primary_source, job["url"],
                )
                live += 1
            checked += 1
        except Exception as e:
            logger.warning("Expiry check error for job %s: %s", job["id"], e)
            errors += 1

    conn.commit()
    return {
        "checked": checked,
        "closed": closed,
        "live": live,
        "unknown": unknown,
        "skipped_recent": skipped_recent,
        "errors": errors,
    }


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
