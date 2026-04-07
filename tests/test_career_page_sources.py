"""Tests for curated career page sources — DB CRUD layer."""
import pytest
import psycopg2
import psycopg2.extras

import shortlist.pgdb as pgdb


@pytest.fixture
def conn():
    """In-memory-style PG connection using a temp schema."""
    c = psycopg2.connect("postgresql://localhost/shortlist_test")
    c.autocommit = False
    pgdb.ensure_career_page_sources_table(c)
    yield c
    c.rollback()
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS career_page_sources")
    c.commit()
    c.close()


# --- ensure_career_page_sources_table ---

def test_ensure_creates_table(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'career_page_sources'"
        )
        assert cur.fetchone() is not None


def test_ensure_idempotent(conn):
    """Calling ensure twice doesn't error."""
    pgdb.ensure_career_page_sources_table(conn)


# --- add_career_page_source ---

def test_add_source_basic(conn):
    pgdb.add_career_page_source(
        conn,
        company_name="Momentic",
        career_url="https://jobs.ashbyhq.com/momentic",
        ats="ashby",
        slug="momentic",
        source="ben_lang_2026-04-07",
    )
    rows = pgdb.get_active_career_page_sources(conn)
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Momentic"
    assert rows[0]["career_url"] == "https://jobs.ashbyhq.com/momentic"
    assert rows[0]["ats"] == "ashby"
    assert rows[0]["slug"] == "momentic"
    assert rows[0]["status"] == "active"
    assert rows[0]["consecutive_empty"] == 0
    assert rows[0]["source"] == "ben_lang_2026-04-07"


def test_add_source_direct_url(conn):
    pgdb.add_career_page_source(
        conn,
        company_name="Ando",
        career_url="https://www.ando.work/careers",
        ats="direct",
        slug=None,
        source="ben_lang_2026-04-07",
    )
    rows = pgdb.get_active_career_page_sources(conn)
    assert rows[0]["slug"] is None
    assert rows[0]["ats"] == "direct"


def test_add_source_duplicate_url_ignored(conn):
    """Duplicate career_url is silently ignored (ON CONFLICT DO NOTHING)."""
    pgdb.add_career_page_source(conn, company_name="Momentic",
                                career_url="https://jobs.ashbyhq.com/momentic",
                                ats="ashby", slug="momentic")
    pgdb.add_career_page_source(conn, company_name="Momentic",
                                career_url="https://jobs.ashbyhq.com/momentic",
                                ats="ashby", slug="momentic")
    rows = pgdb.get_active_career_page_sources(conn)
    assert len(rows) == 1


def test_bulk_add_career_page_sources(conn):
    entries = [
        {"company_name": "Momentic", "career_url": "https://jobs.ashbyhq.com/momentic",
         "ats": "ashby", "slug": "momentic"},
        {"company_name": "Grotto AI", "career_url": "https://jobs.ashbyhq.com/grotto",
         "ats": "ashby", "slug": "grotto"},
        {"company_name": "Ando", "career_url": "https://www.ando.work/careers",
         "ats": "direct", "slug": None},
    ]
    pgdb.bulk_add_career_page_sources(conn, entries, source="ben_lang_2026-04-07")
    rows = pgdb.get_active_career_page_sources(conn)
    assert len(rows) == 3


def test_bulk_add_skips_duplicates(conn):
    entries = [
        {"company_name": "Momentic", "career_url": "https://jobs.ashbyhq.com/momentic",
         "ats": "ashby", "slug": "momentic"},
    ]
    pgdb.bulk_add_career_page_sources(conn, entries, source="run1")
    pgdb.bulk_add_career_page_sources(conn, entries, source="run2")
    rows = pgdb.get_active_career_page_sources(conn)
    assert len(rows) == 1


# --- get_active_career_page_sources ---

def test_get_active_excludes_closed_and_invalid(conn):
    pgdb.add_career_page_source(conn, company_name="Active Co",
                                career_url="https://jobs.ashbyhq.com/active",
                                ats="ashby", slug="active")
    pgdb.add_career_page_source(conn, company_name="Closed Co",
                                career_url="https://jobs.ashbyhq.com/closed",
                                ats="ashby", slug="closed")
    pgdb.add_career_page_source(conn, company_name="Invalid Co",
                                career_url="https://jobs.ashbyhq.com/invalid",
                                ats="ashby", slug="invalid")

    # Close and invalidate manually
    with conn.cursor() as cur:
        cur.execute("UPDATE career_page_sources SET status = 'closed' "
                    "WHERE career_url = 'https://jobs.ashbyhq.com/closed'")
        cur.execute("UPDATE career_page_sources SET status = 'invalid' "
                    "WHERE career_url = 'https://jobs.ashbyhq.com/invalid'")
    conn.commit()

    rows = pgdb.get_active_career_page_sources(conn)
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Active Co"


# --- update_career_page_source_after_fetch ---

def test_update_after_fetch_jobs_found_resets_empty(conn):
    pgdb.add_career_page_source(conn, company_name="Momentic",
                                career_url="https://jobs.ashbyhq.com/momentic",
                                ats="ashby", slug="momentic")
    # Simulate a prior empty run
    with conn.cursor() as cur:
        cur.execute("UPDATE career_page_sources SET consecutive_empty = 2 "
                    "WHERE career_url = 'https://jobs.ashbyhq.com/momentic'")
    conn.commit()

    pgdb.update_career_page_source_after_fetch(
        conn, career_url="https://jobs.ashbyhq.com/momentic",
        jobs_found=5, fetch_error=None,
    )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM career_page_sources WHERE career_url = 'https://jobs.ashbyhq.com/momentic'")
        row = cur.fetchone()

    assert row["consecutive_empty"] == 0
    assert row["last_jobs_count"] == 5
    assert row["status"] == "active"
    assert row["last_checked_at"] is not None


def test_update_after_fetch_empty_increments_counter(conn):
    pgdb.add_career_page_source(conn, company_name="Momentic",
                                career_url="https://jobs.ashbyhq.com/momentic",
                                ats="ashby", slug="momentic")

    pgdb.update_career_page_source_after_fetch(
        conn, career_url="https://jobs.ashbyhq.com/momentic",
        jobs_found=0, fetch_error=None,
    )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM career_page_sources WHERE career_url = 'https://jobs.ashbyhq.com/momentic'")
        row = cur.fetchone()

    assert row["consecutive_empty"] == 1
    assert row["status"] == "active"


def test_update_after_fetch_auto_closes_at_three_empty(conn):
    pgdb.add_career_page_source(conn, company_name="Momentic",
                                career_url="https://jobs.ashbyhq.com/momentic",
                                ats="ashby", slug="momentic")
    with conn.cursor() as cur:
        cur.execute("UPDATE career_page_sources SET consecutive_empty = 2 "
                    "WHERE career_url = 'https://jobs.ashbyhq.com/momentic'")
    conn.commit()

    pgdb.update_career_page_source_after_fetch(
        conn, career_url="https://jobs.ashbyhq.com/momentic",
        jobs_found=0, fetch_error=None,
    )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM career_page_sources WHERE career_url = 'https://jobs.ashbyhq.com/momentic'")
        row = cur.fetchone()

    assert row["consecutive_empty"] == 3
    assert row["status"] == "closed"


def test_update_after_fetch_http_error_marks_invalid(conn):
    pgdb.add_career_page_source(conn, company_name="Momentic",
                                career_url="https://jobs.ashbyhq.com/momentic",
                                ats="ashby", slug="momentic")

    pgdb.update_career_page_source_after_fetch(
        conn, career_url="https://jobs.ashbyhq.com/momentic",
        jobs_found=0, fetch_error="404 Not Found",
    )

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM career_page_sources WHERE career_url = 'https://jobs.ashbyhq.com/momentic'")
        row = cur.fetchone()

    assert row["status"] == "invalid"
