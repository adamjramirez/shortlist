"""Tests for storing jobs in the database."""
import json
import sqlite3

import pytest

from shortlist.collectors.base import RawJob
from shortlist.db import init_db, get_db, upsert_job


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = init_db(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def sample_job():
    return RawJob(
        title="Engineering Manager",
        company="Acme Corp",
        url="https://acme.com/jobs/1",
        description="Lead a team of 25 engineers",
        source="hn",
        location="Remote",
        salary_text="$280k-$320k",
    )


class TestUpsertJob:
    def test_inserts_new_job(self, db, sample_job):
        upsert_job(db, sample_job)
        row = db.execute("SELECT * FROM jobs WHERE company = 'Acme Corp'").fetchone()
        assert row is not None
        assert row["title"] == "Engineering Manager"

    def test_sets_description_hash(self, db, sample_job):
        upsert_job(db, sample_job)
        row = db.execute("SELECT * FROM jobs").fetchone()
        assert row["description_hash"] == sample_job.description_hash

    def test_sets_sources_seen(self, db, sample_job):
        upsert_job(db, sample_job)
        row = db.execute("SELECT * FROM jobs").fetchone()
        sources = json.loads(row["sources_seen"])
        assert "hn" in sources

    def test_duplicate_hash_updates_last_seen(self, db, sample_job):
        upsert_job(db, sample_job)
        # Insert same job again
        upsert_job(db, sample_job)
        rows = db.execute("SELECT * FROM jobs").fetchall()
        assert len(rows) == 1  # no duplicate

    def test_duplicate_appends_source(self, db, sample_job):
        upsert_job(db, sample_job)
        # Same description from a different source
        job2 = RawJob(
            title="Engineering Manager",
            company="Acme Corp",
            url="https://google.com/jobs/acme-em",
            description="Lead a team of 25 engineers",
            source="google_jobs",
            location="Remote",
        )
        upsert_job(db, job2)
        row = db.execute("SELECT * FROM jobs").fetchone()
        sources = json.loads(row["sources_seen"])
        assert "hn" in sources
        assert "google_jobs" in sources

    def test_different_description_creates_new_row(self, db, sample_job):
        upsert_job(db, sample_job)
        job2 = RawJob(
            title="VP Engineering",
            company="Acme Corp",
            url="https://acme.com/jobs/2",
            description="Lead the entire engineering org of 100",
            source="hn",
            location="Remote",
        )
        upsert_job(db, job2)
        rows = db.execute("SELECT * FROM jobs").fetchall()
        assert len(rows) == 2

    def test_preserves_first_seen(self, db, sample_job):
        upsert_job(db, sample_job)
        row1 = db.execute("SELECT first_seen FROM jobs").fetchone()
        first_seen_1 = row1["first_seen"]

        upsert_job(db, sample_job)
        row2 = db.execute("SELECT first_seen FROM jobs").fetchone()
        assert row2["first_seen"] == first_seen_1

    def test_status_defaults_to_new(self, db, sample_job):
        upsert_job(db, sample_job)
        row = db.execute("SELECT status FROM jobs").fetchone()
        assert row["status"] == "new"
