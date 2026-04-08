"""Tests for job expiry detection — pgdb functions and upsert re-open behavior."""
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from shortlist.pgdb import upsert_job, mark_stale_jobs, get_jobs_for_expiry_check, mark_expiry_checked


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeJob:
    title: str = "VP Eng"
    company: str = "Acme"
    location: str = "Remote"
    url: str = "https://jobs.lever.co/acme/abc-123"
    description: str = "Lead engineering"
    description_hash: str = "abc123"
    salary_text: str = "$200k"
    source: str = "lever"
    posted_at: str | None = None


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def execute(self, query, params=None):
        # PostgreSQL → SQLite compatibility
        q = query.replace("%s", "?").replace("::text", "").replace("::timestamptz", "")
        # SQLite uses 0/1 for booleans, not true/false
        q = q.replace("is_closed = true", "is_closed = 1").replace("is_closed = false", "is_closed = 0")
        if params:
            self._cursor.execute(q, params)
        else:
            self._cursor.execute(q)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._cursor.description]
        return dict(zip(cols, row))

    def fetchall(self):
        rows = self._cursor.fetchall()
        cols = [d[0] for d in self._cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakePgConn:
    def __init__(self, sqlite_conn):
        self._conn = sqlite_conn

    def cursor(self):
        return FakeCursor(self._conn)

    def commit(self):
        self._conn.commit()


@pytest.fixture
def pg_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            url TEXT,
            description TEXT,
            description_hash TEXT NOT NULL,
            salary_text TEXT,
            sources_seen TEXT DEFAULT '[]',
            first_seen TIMESTAMP,
            last_seen TIMESTAMP,
            posted_at TIMESTAMP,
            status TEXT DEFAULT 'new',
            fit_score INTEGER,
            is_closed INTEGER DEFAULT 0,
            closed_at TIMESTAMP,
            closed_reason TEXT,
            expiry_checked_at TIMESTAMP,
            UNIQUE(user_id, description_hash)
        )
    """)
    conn.commit()
    return FakePgConn(conn)


def _insert_job(pg_conn, *, user_id=1, url="https://jobs.lever.co/acme/abc-123",
                sources_seen=None, last_seen=None, posted_at=None,
                fit_score=85, is_closed=0, closed_reason=None, expiry_checked_at=None):
    if sources_seen is None:
        sources_seen = '["lever"]'
    if last_seen is None:
        last_seen = datetime.now(timezone.utc).isoformat()
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (user_id, title, company, url, description, description_hash, "
            "sources_seen, last_seen, posted_at, fit_score, is_closed, closed_reason, expiry_checked_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scored')",
            (user_id, "VP Eng", "Acme", url, "desc",
             f"hash-{url}-{user_id}",
             sources_seen, last_seen, posted_at, fit_score,
             is_closed, closed_reason, expiry_checked_at),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE url = ? AND user_id = ?", (url, user_id))
        return cur.fetchone()["id"]


def _get_job(pg_conn, job_id):
    with pg_conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return cur.fetchone()


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# mark_stale_jobs — Pass 1: ATS staleness (greenhouse/lever/ashby)
# ---------------------------------------------------------------------------

def test_mark_stale_ats_3_days(pg_conn):
    """ATS job not seen for 3+ days → closed."""
    job_id = _insert_job(pg_conn, sources_seen='["greenhouse"]', last_seen=_days_ago(4))
    count = mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 1
    assert row["closed_reason"] == "last_seen_stale"
    assert row["closed_at"] is not None
    assert count >= 1


def test_mark_stale_ats_under_threshold(pg_conn):
    """ATS job not seen for 2 days → still open."""
    job_id = _insert_job(pg_conn, sources_seen='["lever"]', last_seen=_days_ago(2))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 0


def test_mark_stale_ats_all_three_sources(pg_conn):
    """Greenhouse, lever, and ashby all caught by pass 1."""
    ids = [
        _insert_job(pg_conn, url="https://job-boards.greenhouse.io/x/jobs/1",
                    sources_seen='["greenhouse"]', last_seen=_days_ago(5)),
        _insert_job(pg_conn, url="https://jobs.lever.co/x/1",
                    sources_seen='["lever"]', last_seen=_days_ago(5)),
        _insert_job(pg_conn, url="https://jobs.ashbyhq.com/x/1",
                    sources_seen='["ashby"]', last_seen=_days_ago(5)),
    ]
    count = mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert count == 3
    for job_id in ids:
        assert _get_job(pg_conn, job_id)["is_closed"] == 1


# ---------------------------------------------------------------------------
# mark_stale_jobs — Pass 2: LinkedIn age
# ---------------------------------------------------------------------------

def test_mark_stale_linkedin_30_days(pg_conn):
    """LinkedIn job posted 30+ days ago → closed."""
    job_id = _insert_job(pg_conn,
                         url="https://www.linkedin.com/jobs/view/123",
                         sources_seen='["linkedin"]',
                         posted_at=_days_ago(31))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 1
    assert _get_job(pg_conn, job_id)["closed_reason"] == "age_expired"


def test_mark_stale_linkedin_29_days(pg_conn):
    """LinkedIn job posted 29 days ago → still open."""
    job_id = _insert_job(pg_conn,
                         url="https://www.linkedin.com/jobs/view/123",
                         sources_seen='["linkedin"]',
                         posted_at=_days_ago(29))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 0


def test_mark_stale_linkedin_null_posted_at(pg_conn):
    """LinkedIn job with no posted_at → not caught by age pass (use last_seen via pass 5)."""
    job_id = _insert_job(pg_conn,
                         url="https://www.linkedin.com/jobs/view/456",
                         sources_seen='["linkedin"]',
                         posted_at=None,
                         last_seen=_days_ago(2))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    # LinkedIn with null posted_at is NOT caught by pass 2, and excluded from pass 5
    assert _get_job(pg_conn, job_id)["is_closed"] == 0


# ---------------------------------------------------------------------------
# mark_stale_jobs — Pass 3: HN age (with posted_at)
# ---------------------------------------------------------------------------

def test_mark_stale_hn_with_posted_at(pg_conn):
    """HN job with posted_at 45+ days ago → closed."""
    job_id = _insert_job(pg_conn,
                         url="https://news.ycombinator.com/item?id=123",
                         sources_seen='["hn"]',
                         posted_at=_days_ago(46))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 1
    assert _get_job(pg_conn, job_id)["closed_reason"] == "age_expired"


# ---------------------------------------------------------------------------
# mark_stale_jobs — Pass 4: HN with null posted_at (last_seen fallback)
# ---------------------------------------------------------------------------

def test_mark_stale_hn_null_posted_at_stale(pg_conn):
    """HN job with no posted_at, last_seen 45+ days ago → closed."""
    job_id = _insert_job(pg_conn,
                         url="https://news.ycombinator.com/item?id=456",
                         sources_seen='["hn"]',
                         posted_at=None,
                         last_seen=_days_ago(46))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 1
    assert _get_job(pg_conn, job_id)["closed_reason"] == "last_seen_stale"


def test_mark_stale_hn_null_posted_at_recent(pg_conn):
    """HN job with no posted_at but recently seen → still open."""
    job_id = _insert_job(pg_conn,
                         url="https://news.ycombinator.com/item?id=789",
                         sources_seen='["hn"]',
                         posted_at=None,
                         last_seen=_days_ago(10))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 0


# ---------------------------------------------------------------------------
# mark_stale_jobs — Pass 5: Generic staleness
# ---------------------------------------------------------------------------

def test_mark_stale_generic_7_days(pg_conn):
    """Unknown source not seen in 7+ days → closed."""
    job_id = _insert_job(pg_conn,
                         url="https://somecompany.com/jobs/123",
                         sources_seen='["nextplay"]',
                         last_seen=_days_ago(8))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 1
    assert _get_job(pg_conn, job_id)["closed_reason"] == "last_seen_stale"


def test_mark_stale_generic_under_threshold(pg_conn):
    """Unknown source not seen in 6 days → still open."""
    job_id = _insert_job(pg_conn,
                         url="https://somecompany.com/jobs/456",
                         sources_seen='["nextplay"]',
                         last_seen=_days_ago(6))
    mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert _get_job(pg_conn, job_id)["is_closed"] == 0


# ---------------------------------------------------------------------------
# mark_stale_jobs — user-closed protection
# ---------------------------------------------------------------------------

def test_user_closed_not_overridden(pg_conn):
    """Jobs with closed_reason='user' are never touched by any staleness pass."""
    job_id = _insert_job(pg_conn,
                         sources_seen='["greenhouse"]',
                         last_seen=_days_ago(30),
                         is_closed=1,
                         closed_reason="user")
    count = mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    row = _get_job(pg_conn, job_id)
    assert row["closed_reason"] == "user"  # unchanged
    assert count == 0  # nothing newly closed


def test_already_closed_not_double_counted(pg_conn):
    """Auto-closed jobs are not re-closed (is_closed=1 already)."""
    job_id = _insert_job(pg_conn,
                         sources_seen='["lever"]',
                         last_seen=_days_ago(10),
                         is_closed=1,
                         closed_reason="url_check")
    count = mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert count == 0


def test_user_isolation(pg_conn):
    """Staleness pass only affects the target user_id."""
    _insert_job(pg_conn, user_id=2,
                sources_seen='["lever"]',
                last_seen=_days_ago(10))
    count = mark_stale_jobs(pg_conn, user_id=1, run_started_at=_now())
    assert count == 0


# ---------------------------------------------------------------------------
# upsert_job — re-open on re-appearance
# ---------------------------------------------------------------------------

def test_upsert_reopens_auto_closed(pg_conn):
    """Auto-closed job reappears in feed → is_closed reset to false."""
    job_id = _insert_job(pg_conn,
                         sources_seen='["greenhouse"]',
                         last_seen=_days_ago(5),
                         is_closed=1,
                         closed_reason="url_check")
    job = FakeJob(source="greenhouse",
                  url="https://jobs.lever.co/acme/abc-123",
                  description_hash=f"hash-https://jobs.lever.co/acme/abc-123-1")
    upsert_job(pg_conn, user_id=1, job=job)
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 0
    assert row["closed_reason"] is None
    assert row["closed_at"] is None


def test_upsert_preserves_user_closed(pg_conn):
    """User-closed job reappears in feed → stays closed."""
    job_id = _insert_job(pg_conn,
                         sources_seen='["greenhouse"]',
                         last_seen=_days_ago(5),
                         is_closed=1,
                         closed_reason="user")
    job = FakeJob(source="greenhouse",
                  url="https://jobs.lever.co/acme/abc-123",
                  description_hash=f"hash-https://jobs.lever.co/acme/abc-123-1")
    upsert_job(pg_conn, user_id=1, job=job)
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 1
    assert row["closed_reason"] == "user"


# ---------------------------------------------------------------------------
# get_jobs_for_expiry_check
# ---------------------------------------------------------------------------

def test_get_jobs_for_expiry_check_returns_eligible(pg_conn):
    """Returns jobs from checkable sources, ordered by expiry_checked_at NULLS FIRST."""
    # Never checked
    id1 = _insert_job(pg_conn, url="https://www.linkedin.com/jobs/view/1",
                      sources_seen='["linkedin"]', fit_score=85,
                      expiry_checked_at=None)
    # Checked 2 days ago
    id2 = _insert_job(pg_conn, url="https://www.linkedin.com/jobs/view/2",
                      sources_seen='["linkedin"]', fit_score=80,
                      expiry_checked_at=_days_ago(2))
    # Checked 1 day ago
    id3 = _insert_job(pg_conn, url="https://www.linkedin.com/jobs/view/3",
                      sources_seen='["linkedin"]', fit_score=90,
                      expiry_checked_at=_days_ago(1))

    jobs = get_jobs_for_expiry_check(pg_conn, limit=10)
    ids = [j["id"] for j in jobs]
    assert id1 in ids
    assert id2 in ids
    assert id3 in ids
    # Nulls first
    assert ids.index(id1) < ids.index(id2)
    assert ids.index(id2) < ids.index(id3)


def test_get_jobs_for_expiry_check_skips_closed(pg_conn):
    """Already-closed jobs are not returned."""
    _insert_job(pg_conn, url="https://www.linkedin.com/jobs/view/99",
                sources_seen='["linkedin"]', is_closed=1)
    jobs = get_jobs_for_expiry_check(pg_conn, limit=10)
    assert all(j["id"] != 99 for j in jobs)
    assert len(jobs) == 0


def test_get_jobs_for_expiry_check_skips_hn(pg_conn):
    """HN jobs not returned (no useful URL signal)."""
    _insert_job(pg_conn, url="https://news.ycombinator.com/item?id=1",
                sources_seen='["hn"]', fit_score=85)
    jobs = get_jobs_for_expiry_check(pg_conn, limit=10)
    assert len(jobs) == 0


def test_get_jobs_for_expiry_check_respects_limit(pg_conn):
    """Limit parameter is respected."""
    for i in range(5):
        _insert_job(pg_conn, url=f"https://jobs.lever.co/x/{i}",
                    sources_seen='["lever"]', fit_score=85)
    jobs = get_jobs_for_expiry_check(pg_conn, limit=3)
    assert len(jobs) == 3


def test_get_jobs_for_expiry_check_all_sources(pg_conn):
    """linkedin, greenhouse, lever, ashby all returned."""
    for source, url in [
        ("linkedin", "https://www.linkedin.com/jobs/view/42"),
        ("greenhouse", "https://job-boards.greenhouse.io/co/jobs/1"),
        ("lever", "https://jobs.lever.co/co/abc"),
        ("ashby", "https://jobs.ashbyhq.com/co/abc"),
    ]:
        _insert_job(pg_conn, url=url, sources_seen=f'["{source}"]', fit_score=85)
    jobs = get_jobs_for_expiry_check(pg_conn, limit=10)
    assert len(jobs) == 4


# ---------------------------------------------------------------------------
# mark_expiry_checked
# ---------------------------------------------------------------------------

def test_mark_expiry_checked_alive(pg_conn):
    """Alive result → only sets expiry_checked_at, job stays open."""
    job_id = _insert_job(pg_conn, sources_seen='["lever"]')
    mark_expiry_checked(pg_conn, job_id=job_id, is_closed=False)
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 0
    assert row["expiry_checked_at"] is not None
    assert row["closed_reason"] is None


def test_mark_expiry_checked_closed(pg_conn):
    """Closed result → sets is_closed, closed_at, closed_reason, expiry_checked_at."""
    job_id = _insert_job(pg_conn, sources_seen='["lever"]')
    mark_expiry_checked(pg_conn, job_id=job_id, is_closed=True, closed_reason="url_check")
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 1
    assert row["closed_at"] is not None
    assert row["closed_reason"] == "url_check"
    assert row["expiry_checked_at"] is not None


def test_mark_expiry_checked_error(pg_conn):
    """None result (error/unknown) → sets expiry_checked_at only, job stays open."""
    job_id = _insert_job(pg_conn, sources_seen='["linkedin"]')
    mark_expiry_checked(pg_conn, job_id=job_id, is_closed=False)
    row = _get_job(pg_conn, job_id)
    assert row["is_closed"] == 0
    assert row["expiry_checked_at"] is not None


# ---------------------------------------------------------------------------
# Pipeline integration — closed_count in return dict
# ---------------------------------------------------------------------------

def test_pipeline_includes_closed_count():
    """run_pipeline_pg returns closed_count in result dict."""
    from unittest.mock import patch, MagicMock
    from shortlist.pipeline import run_pipeline_pg
    from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter, LLMConfig

    config = Config(
        fit_context="test",
        filters=Filters(
            location=LocationFilter(remote=True),
            salary=SalaryFilter(min_base=0),
            role_type=RoleTypeFilter(reject_explicit_ic=False),
        ),
        llm=LLMConfig(model="gemini-2.0-flash", max_jobs_per_run=10),
    )

    mock_conn = MagicMock()

    with patch("shortlist.pipeline._get_collectors", return_value={}), \
         patch("shortlist.pgdb.get_pg_connection", return_value=mock_conn), \
         patch("shortlist.pgdb.ensure_nextplay_cache_table"), \
         patch("shortlist.pgdb.ensure_career_page_sources_table"), \
         patch("shortlist.pgdb.fetch_jobs", return_value=[]), \
         patch("shortlist.pgdb.get_active_career_page_sources", return_value=[]), \
         patch("shortlist.pgdb.fetch_companies", return_value=[]), \
         patch("shortlist.pgdb.mark_stale_jobs", return_value=3) as mock_stale, \
         patch("shortlist.pipeline._ensure_llm"):

        result = run_pipeline_pg(config, db_url="postgresql://fake", user_id=1)

    assert "closed_count" in result
    assert result["closed_count"] == 3
    mock_stale.assert_called_once()
