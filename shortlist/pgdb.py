"""PostgreSQL database layer for the web pipeline.

Sync psycopg2 connection — used from pipeline thread (asyncio.to_thread).
Separate from db.py (SQLite, CLI only) and api/db.py (async SQLAlchemy, API only).
"""
import json
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def get_pg_connection(db_url: str):
    """Open a sync psycopg2 connection with RealDictCursor."""
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def upsert_job(conn, user_id: int, job) -> None:
    """Insert a new job or update last_seen + sources.

    Dedup by: (user_id + description_hash) OR (user_id + url).
    On conflict: updates last_seen, appends source to sources_seen.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, sources_seen FROM jobs "
            "WHERE user_id = %s AND (description_hash = %s OR url = %s)",
            (user_id, job.description_hash, job.url),
        )
        existing = cur.fetchone()

        # Parse posted_at string to datetime if present
        posted_at_dt = None
        if getattr(job, "posted_at", None):
            try:
                posted_at_dt = datetime.fromisoformat(job.posted_at)
            except (ValueError, TypeError):
                pass

        if existing:
            raw = existing["sources_seen"] or []
            sources = json.loads(raw) if isinstance(raw, str) else list(raw)
            if job.source not in sources:
                sources.append(job.source)
            cur.execute(
                "UPDATE jobs SET last_seen = %s, sources_seen = %s, "
                "posted_at = COALESCE(posted_at, %s) WHERE id = %s",
                (datetime.now(timezone.utc), json.dumps(sources),
                 posted_at_dt, existing["id"]),
            )
        else:
            sources = json.dumps([job.source])
            cur.execute(
                "INSERT INTO jobs (user_id, title, company, location, url, description, "
                "description_hash, salary_text, sources_seen, first_seen, last_seen, "
                "posted_at, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new')",
                (
                    user_id, job.title, job.company, job.location, job.url,
                    job.description, job.description_hash, job.salary_text,
                    sources, datetime.now(timezone.utc), datetime.now(timezone.utc),
                    posted_at_dt,
                ),
            )
    conn.commit()


def log_source_run(conn, user_id: int, source_name: str, started_at: str,
                   status: str, jobs_found: int, error: str | None = None) -> None:
    """Log a source run to server logs (no source_runs table in PG)."""
    if status == "failure":
        logger.warning(f"Source {source_name}: failed — {error}")
    else:
        logger.info(f"Source {source_name}: {status} — {jobs_found} jobs")


def get_cached_enrichment(conn, user_id: int, company: str):
    """Check if we have recent enrichment for this company."""
    from shortlist.processors.enricher import _normalize_company, CompanyIntel, CACHE_DAYS
    normalized = _normalize_company(company)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM companies "
            "WHERE user_id = %s AND name_normalized = %s "
            "AND enriched_at > NOW() - INTERVAL '%s days'",
            (user_id, normalized, CACHE_DAYS),
        )
        row = cur.fetchone()

    if row and row.get("growth_signals"):
        return CompanyIntel.from_json(company, row["growth_signals"])
    return None


def cache_enrichment(conn, user_id: int, company: str, intel) -> None:
    """Cache enrichment data in the companies table."""
    from shortlist.processors.enricher import _normalize_company
    normalized = _normalize_company(company)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO companies (user_id, name, name_normalized, domain, stage, headcount, "
            "growth_signals, glassdoor_rating, eng_blog_url, enriched_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) "
            "ON CONFLICT (user_id, name_normalized, domain) DO UPDATE SET "
            "stage = EXCLUDED.stage, headcount = EXCLUDED.headcount, "
            "growth_signals = EXCLUDED.growth_signals, "
            "glassdoor_rating = EXCLUDED.glassdoor_rating, "
            "eng_blog_url = EXCLUDED.eng_blog_url, "
            "domain = EXCLUDED.domain, "
            "enriched_at = NOW()",
            (user_id, company, normalized, intel.website_domain, intel.stage,
             intel.headcount_estimate, intel.to_json(), intel.glassdoor_rating,
             intel.eng_blog_url),
        )
    conn.commit()


def fetch_jobs(conn, user_id: int, status: str, extra_where: str = "",
               extra_params: list | None = None,
               order: str = "first_seen DESC", limit: int | None = None) -> list[dict]:
    """Fetch jobs for a user by status with optional extra conditions."""
    query = f"SELECT * FROM jobs WHERE user_id = %s AND status = %s {extra_where} ORDER BY {order}"
    params: list = [user_id, status] + (extra_params or [])
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def update_job(conn, job_id: int, **fields) -> None:
    """Update specific fields on a job by ID."""
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE jobs SET {set_clause} WHERE id = %s",
            (*fields.values(), job_id),
        )


# --- NextPlay cache (system-level, not per-user) ---

def ensure_nextplay_cache_table(conn) -> None:
    """Create the nextplay_cache table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nextplay_cache (
                domain TEXT PRIMARY KEY,
                ats TEXT,
                slug TEXT,
                jobs JSONB,
                cached_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()


def get_cached_ats_discovery(conn, domain: str, max_age_hours: int = 24) -> dict | None:
    """Get cached ATS discovery result for a domain. Returns None if expired/missing."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ats, slug, jobs FROM nextplay_cache "
            "WHERE domain = %s AND cached_at > NOW() - INTERVAL '%s hours'",
            (domain, max_age_hours),
        )
        return cur.fetchone()


def cache_ats_discovery(conn, domain: str, ats: str | None, slug: str | None, jobs_json: list) -> None:
    """Cache ATS discovery result for a domain."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO nextplay_cache (domain, ats, slug, jobs, cached_at) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            "ON CONFLICT (domain) DO UPDATE SET "
            "ats = EXCLUDED.ats, slug = EXCLUDED.slug, "
            "jobs = EXCLUDED.jobs, cached_at = NOW()",
            (domain, ats, slug, json.dumps(jobs_json)),
        )
    conn.commit()


def get_career_url_for_domain(conn, domain: str) -> str | None:
    """Look up cached ATS URL for a company domain. Normalizes www. prefix."""
    clean = domain.lower().removeprefix("www.").strip()
    for d in [clean, f"www.{clean}"]:
        cached = get_cached_ats_discovery(conn, d)
        if cached and cached["ats"] and cached["slug"]:
            return _build_ats_url(cached["ats"], cached["slug"])
    return None


def _build_ats_url(ats: str, slug: str) -> str:
    """Build a human-friendly ATS careers page URL."""
    if ats == "greenhouse":
        return f"https://boards.greenhouse.io/{slug}"
    elif ats == "lever":
        return f"https://jobs.lever.co/{slug}"
    elif ats == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}"
    return ""


# ---------------------------------------------------------------------------
# Curated career page sources
# ---------------------------------------------------------------------------

def ensure_career_page_sources_table(conn) -> None:
    """Create the career_page_sources table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS career_page_sources (
                id SERIAL PRIMARY KEY,
                company_name TEXT NOT NULL,
                career_url TEXT NOT NULL UNIQUE,
                ats TEXT,
                slug TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                consecutive_empty INT NOT NULL DEFAULT 0,
                last_jobs_count INT NOT NULL DEFAULT 0,
                last_checked_at TIMESTAMPTZ,
                added_at TIMESTAMPTZ DEFAULT NOW(),
                source TEXT,
                notes TEXT
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_page_sources_status "
            "ON career_page_sources(status)"
        )
    conn.commit()


def add_career_page_source(
    conn,
    company_name: str,
    career_url: str,
    ats: str | None,
    slug: str | None,
    source: str | None = None,
    notes: str | None = None,
) -> None:
    """Add a single curated career page source. Silently ignores duplicate URLs."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO career_page_sources
                (company_name, career_url, ats, slug, source, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (career_url) DO NOTHING
            """,
            (company_name, career_url, ats, slug, source, notes),
        )
    conn.commit()


def bulk_add_career_page_sources(
    conn,
    entries: list[dict],
    source: str | None = None,
) -> int:
    """Bulk-insert curated career page sources. Returns count of rows inserted.

    Each entry: {company_name, career_url, ats, slug, notes (optional)}
    Duplicate career_urls are silently skipped.
    """
    inserted = 0
    with conn.cursor() as cur:
        for entry in entries:
            cur.execute(
                """
                INSERT INTO career_page_sources
                    (company_name, career_url, ats, slug, source, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (career_url) DO NOTHING
                """,
                (
                    entry["company_name"],
                    entry["career_url"],
                    entry.get("ats"),
                    entry.get("slug"),
                    entry.get("source", source),
                    entry.get("notes"),
                ),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def get_active_career_page_sources(conn) -> list[dict]:
    """Return all active curated career page sources."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, company_name, career_url, ats, slug, status, "
            "consecutive_empty, last_jobs_count, last_checked_at, source "
            "FROM career_page_sources WHERE status = 'active' ORDER BY added_at"
        )
        return [dict(row) for row in cur.fetchall()]


def update_career_page_source_after_fetch(
    conn,
    career_url: str,
    jobs_found: int,
    fetch_error: str | None,
) -> None:
    """Update state after a fetch attempt.

    - fetch_error set → mark invalid
    - jobs_found > 0  → reset consecutive_empty, stay active
    - jobs_found == 0 → increment consecutive_empty; close at 3
    """
    if fetch_error:
        new_status = "invalid"
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE career_page_sources SET status = %s, last_checked_at = NOW() "
                "WHERE career_url = %s",
                (new_status, career_url),
            )
    elif jobs_found > 0:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE career_page_sources SET consecutive_empty = 0, "
                "last_jobs_count = %s, status = 'active', last_checked_at = NOW() "
                "WHERE career_url = %s",
                (jobs_found, career_url),
            )
    else:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE career_page_sources "
                "SET consecutive_empty = consecutive_empty + 1, "
                "last_jobs_count = 0, last_checked_at = NOW(), "
                "status = CASE WHEN consecutive_empty + 1 >= 3 THEN 'closed' ELSE status END "
                "WHERE career_url = %s",
                (career_url,),
            )
    conn.commit()


def count_jobs(conn, user_id: int, status: str) -> int:
    """Count jobs for a user by status."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE user_id = %s AND status = %s",
            (user_id, status),
        )
        return cur.fetchone()["n"]


def fetch_companies(conn, user_id: int, extra_where: str = "") -> list[dict]:
    """Fetch companies for a user with optional conditions."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM companies WHERE user_id = %s {extra_where}",
            (user_id,),
        )
        return cur.fetchall()


def update_company(conn, company_id: int, **fields) -> None:
    """Update specific fields on a company by ID."""
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE companies SET {set_clause} WHERE id = %s",
            (*fields.values(), company_id),
        )
