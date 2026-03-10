"""Tests for database initialization and helpers."""
import sqlite3
from pathlib import Path

import pytest

from shortlist.db import init_db, get_db


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def db(db_path):
    return init_db(db_path)


class TestInitDb:
    def test_creates_database_file(self, db_path):
        init_db(db_path)
        assert db_path.exists()

    def test_creates_jobs_table(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        )
        assert cursor.fetchone() is not None

    def test_creates_companies_table(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='companies'"
        )
        assert cursor.fetchone() is not None

    def test_creates_sources_table(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
        )
        assert cursor.fetchone() is not None

    def test_creates_source_runs_table(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_runs'"
        )
        assert cursor.fetchone() is not None

    def test_creates_run_logs_table(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='run_logs'"
        )
        assert cursor.fetchone() is not None

    def test_jobs_table_has_required_columns(self, db):
        cursor = db.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in cursor.fetchall()}
        required = {
            "id", "title", "company", "location", "url", "description",
            "description_hash", "salary_text", "sources_seen", "first_seen",
            "last_seen", "status", "reject_reason", "fit_score", "matched_track",
            "score_reasoning", "yellow_flags", "salary_estimate", "salary_confidence",
            "enrichment", "enriched_at", "tailored_resume_path", "notes",
            "first_briefed", "brief_count",
        }
        assert required.issubset(columns), f"Missing columns: {required - columns}"

    def test_companies_table_has_normalized_name(self, db):
        cursor = db.execute("PRAGMA table_info(companies)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "name_normalized" in columns
        assert "domain" in columns

    def test_idempotent_init(self, db_path):
        """Calling init_db twice doesn't error."""
        db1 = init_db(db_path)
        db1.close()
        db2 = init_db(db_path)
        cursor = db2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        )
        assert cursor.fetchone() is not None
        db2.close()

    def test_description_hash_unique_constraint(self, db):
        db.execute(
            "INSERT INTO jobs (title, company, description_hash, sources_seen) "
            "VALUES (?, ?, ?, ?)",
            ("EM", "Acme", "hash123", '["hn"]'),
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO jobs (title, company, description_hash, sources_seen) "
                "VALUES (?, ?, ?, ?)",
                ("EM", "Acme", "hash123", '["google"]'),
            )


class TestGetDb:
    def test_returns_connection(self, db_path):
        init_db(db_path)
        conn = get_db(db_path)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_set(self, db_path):
        init_db(db_path)
        conn = get_db(db_path)
        assert conn.row_factory == sqlite3.Row
        conn.close()
