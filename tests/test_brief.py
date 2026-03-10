"""Tests for the brief generator."""
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from shortlist.brief import generate_brief, BriefData
from shortlist.db import init_db, upsert_job
from shortlist.collectors.base import RawJob


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = init_db(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def briefs_dir(tmp_path):
    d = tmp_path / "briefs"
    d.mkdir()
    return d


_DB_ONLY_FIELDS = {
    "matched_track", "score_reasoning", "yellow_flags", "reject_reason",
    "first_briefed", "brief_count", "salary_estimate", "salary_confidence",
}


def _insert_job(db, title="EM", company="Acme", status="scored", score=85, **kwargs):
    # Separate RawJob fields from DB-only fields
    db_updates = {}
    raw_kwargs = {}
    for k, v in kwargs.items():
        if k in _DB_ONLY_FIELDS:
            db_updates[k] = v
        else:
            raw_kwargs[k] = v

    defaults = dict(
        location="Remote",
        url="https://acme.com/jobs/1",
        description=f"{title} at {company} - {score}",
        source="hn",
        salary_text=None,
    )
    defaults.update(raw_kwargs)
    job = RawJob(title=title, company=company, **defaults)
    upsert_job(db, job)

    # Update status, score, and DB-only fields
    updates = {"status": status}
    if score is not None:
        updates["fit_score"] = score
    updates.update(db_updates)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job.description_hash]
    db.execute(f"UPDATE jobs SET {set_clause} WHERE description_hash = ?", values)
    db.commit()
    return job


class TestBriefData:
    def test_collects_top_matches(self, db):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91)
        _insert_job(db, "EM", "MidCo", status="scored", score=75)
        data = BriefData.from_db(db)
        assert len(data.top_matches) == 1  # score >= 80
        assert data.top_matches[0]["company"] == "BigCo"

    def test_collects_worth_a_look(self, db):
        _insert_job(db, "EM", "MidCo", status="scored", score=65)
        data = BriefData.from_db(db)
        assert len(data.worth_a_look) == 1

    def test_collects_filtered_out(self, db):
        _insert_job(db, "SWE", "BadCo", status="rejected", score=None,
                     reject_reason="Salary: $150k (below $250k minimum)")
        data = BriefData.from_db(db)
        assert len(data.filtered_out) == 1

    def test_collects_tracker(self, db):
        _insert_job(db, "VP Eng", "BigCo", status="applied", score=91)
        _insert_job(db, "EM", "MidCo", status="scored", score=75)
        data = BriefData.from_db(db)
        # Tracker includes all non-rejected, non-new jobs
        assert len(data.tracker) >= 2

    def test_counts(self, db):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91)
        _insert_job(db, "EM", "MidCo", status="scored", score=65)
        _insert_job(db, "SWE", "BadCo", status="rejected", score=None)
        data = BriefData.from_db(db)
        assert data.total_collected >= 3
        assert data.total_filtered >= 1


class TestGenerateBrief:
    def test_creates_file(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91)
        path = generate_brief(db, briefs_dir)
        assert path.exists()

    def test_filename_is_date(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91)
        path = generate_brief(db, briefs_dir)
        today = date.today().isoformat()
        assert today in path.name

    def test_contains_header(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91)
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "# Shortlist" in content

    def test_contains_top_match(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91,
                     location="Remote", matched_track="vp")
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "BigCo" in content
        assert "VP Eng" in content

    def test_contains_filtered_section(self, db, briefs_dir):
        _insert_job(db, "SWE", "BadCo", status="rejected", score=None,
                     reject_reason="Salary below minimum")
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "Filtered Out" in content
        assert "Below salary minimum" in content

    def test_contains_tracker(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="applied", score=91)
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "Tracker" in content

    def test_contains_source_health(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91)
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "Source Health" in content

    def test_marks_new_jobs(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91, brief_count=0)
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "🆕" in content

    def test_marks_seen_jobs(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91,
                     brief_count=2, first_briefed=date.today().isoformat())
        path = generate_brief(db, briefs_dir)
        content = path.read_text()
        assert "👁️" in content

    def test_empty_db_produces_brief(self, db, briefs_dir):
        """Even with no jobs, should produce a valid brief."""
        path = generate_brief(db, briefs_dir)
        assert path.exists()
        content = path.read_text()
        assert "# Shortlist" in content

    def test_updates_brief_count(self, db, briefs_dir):
        _insert_job(db, "VP Eng", "BigCo", status="scored", score=91, brief_count=0)
        generate_brief(db, briefs_dir)
        row = db.execute("SELECT brief_count, first_briefed FROM jobs WHERE company = 'BigCo'").fetchone()
        assert row["brief_count"] == 1
        assert row["first_briefed"] is not None
