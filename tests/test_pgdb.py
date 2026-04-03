"""Tests for pgdb module — sync PG layer for pipeline."""
import sqlite3
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from shortlist.pgdb import upsert_job, log_source_run


@dataclass
class FakeJob:
    title: str = "VP Eng"
    company: str = "Acme"
    location: str = "Remote"
    url: str = "https://example.com/job"
    description: str = "Lead engineering"
    description_hash: str = "abc123"
    salary_text: str = "$200k"
    source: str = "hn"
    posted_at: str | None = None


class FakeCursor:
    """Mimics psycopg2 RealDictCursor for testing."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()
        self._last_query = ""

    def execute(self, query, params=None):
        # Convert %s to ? for SQLite compat
        sqlite_query = query.replace("%s", "?")
        self._last_query = sqlite_query
        if params:
            self._cursor.execute(sqlite_query, params)
        else:
            self._cursor.execute(sqlite_query)

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
    """Wraps sqlite3 connection to mimic psycopg2 interface for testing."""

    def __init__(self, sqlite_conn):
        self._conn = sqlite_conn

    def cursor(self):
        return FakeCursor(self._conn)

    def commit(self):
        self._conn.commit()


@pytest.fixture
def pg_conn():
    """Fake PG connection backed by SQLite (for testing SQL logic)."""
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
            UNIQUE(user_id, description_hash)
        )
    """)
    conn.commit()
    return FakePgConn(conn)


def test_upsert_job_insert(pg_conn):
    job = FakeJob()
    upsert_job(pg_conn, user_id=1, job=job)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE user_id = 1")
        rows = cur.fetchall()

    assert len(rows) == 1
    assert rows[0]["title"] == "VP Eng"
    assert rows[0]["company"] == "Acme"
    assert rows[0]["status"] == "new"
    assert rows[0]["user_id"] == 1


def test_upsert_job_update_sources(pg_conn):
    job1 = FakeJob(source="hn")
    upsert_job(pg_conn, user_id=1, job=job1)

    job2 = FakeJob(source="linkedin")
    upsert_job(pg_conn, user_id=1, job=job2)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE user_id = 1")
        rows = cur.fetchall()

    assert len(rows) == 1  # Same hash — no duplicate
    import json
    sources = json.loads(rows[0]["sources_seen"])
    assert "hn" in sources
    assert "linkedin" in sources


def test_upsert_job_different_users(pg_conn):
    job = FakeJob()
    upsert_job(pg_conn, user_id=1, job=job)
    upsert_job(pg_conn, user_id=2, job=job)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs")
        rows = cur.fetchall()

    assert len(rows) == 2  # Different users — separate rows


def test_log_source_run_success(pg_conn, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="shortlist.pgdb"):
        log_source_run(pg_conn, user_id=1, source_name="hn",
                       started_at="2026-01-01", status="success", jobs_found=42)
    assert "hn" in caplog.text
    assert "42" in caplog.text


def test_log_source_run_failure(pg_conn, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="shortlist.pgdb"):
        log_source_run(pg_conn, user_id=1, source_name="linkedin",
                       started_at="2026-01-01", status="failure",
                       jobs_found=0, error="rate limited")
    assert "linkedin" in caplog.text
    assert "rate limited" in caplog.text


def test_upsert_job_stores_posted_at(pg_conn):
    job = FakeJob(posted_at="2026-03-15T10:30:00+00:00")
    upsert_job(pg_conn, user_id=1, job=job)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT posted_at FROM jobs WHERE user_id = 1")
        row = cur.fetchone()

    assert row["posted_at"] is not None


def test_upsert_job_posted_at_none_when_missing(pg_conn):
    job = FakeJob()  # posted_at=None
    upsert_job(pg_conn, user_id=1, job=job)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT posted_at FROM jobs WHERE user_id = 1")
        row = cur.fetchone()

    assert row["posted_at"] is None


def test_upsert_job_preserves_existing_posted_at(pg_conn):
    """Re-seen job should NOT overwrite existing posted_at."""
    job1 = FakeJob(source="hn", posted_at="2026-03-15T10:30:00+00:00")
    upsert_job(pg_conn, user_id=1, job=job1)

    job2 = FakeJob(source="linkedin", posted_at="2026-03-20T08:00:00+00:00")
    upsert_job(pg_conn, user_id=1, job=job2)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT posted_at FROM jobs WHERE user_id = 1")
        row = cur.fetchone()

    # Should keep the first posted_at (COALESCE behavior)
    assert "2026-03-15" in str(row["posted_at"])
