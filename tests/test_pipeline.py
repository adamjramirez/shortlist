"""End-to-end pipeline tests."""
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter, BriefConfig
from shortlist.pipeline import run_pipeline, run_collect_only, run_brief_only
from shortlist.processors.scorer import ScoreResult


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Skip LLM configuration in pipeline tests."""
    monkeypatch.setattr("shortlist.pipeline._ensure_llm", lambda _: None)


@pytest.fixture(autouse=True)
def no_enrichment(monkeypatch):
    """Disable enrichment and resume tailoring in pipeline tests."""
    monkeypatch.setattr("shortlist.pipeline.enrich_company", lambda *a, **kw: None)
    monkeypatch.setattr("shortlist.pipeline.tailor_jobs_parallel", lambda *a, **kw: [])


def _mock_score_jobs_parallel(jobs, config, max_workers=10):
    """Deterministic mock for parallel scoring."""
    results = []
    for row_id, job in jobs:
        results.append((row_id, _mock_score_job(job, config)))
    return results


@pytest.fixture
def config():
    return Config(
        filters=Filters(
            location=LocationFilter(remote=True, local_zip="75098", max_commute_minutes=30),
            salary=SalaryFilter(min_base=250000),
            role_type=RoleTypeFilter(reject_explicit_ic=True),
        ),
        brief=BriefConfig(output_dir="briefs/", top_n=10),
    )


@pytest.fixture
def project_root(tmp_path):
    return tmp_path


@pytest.fixture
def mock_hn_jobs():
    """Mock HN collector to return predictable jobs."""
    from shortlist.collectors.base import RawJob
    jobs = [
        RawJob(
            title="VP Engineering",
            company="BigCo",
            url="https://bigco.com/jobs/vp",
            description="Lead 40-person eng org. Remote. $300k-$350k.",
            source="hn",
            location="Remote",
            salary_text="$300k-$350k",
        ),
        RawJob(
            title="Senior Software Engineer",
            company="SmallCo",
            url="https://smallco.com/jobs/swe",
            description="Individual contributor role. No direct reports. NYC only. $180k.",
            source="hn",
            location="NYC",
            salary_text="$180,000",
        ),
        RawJob(
            title="Engineering Manager",
            company="MidCo",
            url="https://midco.com/jobs/em",
            description="Manage a team of 25 engineers. Build platform.",
            source="hn",
            location="Remote",
        ),
    ]
    return jobs


def _mock_score_job(job, config):
    """Deterministic mock scorer for pipeline tests."""
    if "VP" in job.title:
        return ScoreResult(fit_score=91, matched_track="vp", reasoning="Great VP fit")
    elif "Manager" in job.title:
        return ScoreResult(fit_score=78, matched_track="em", reasoning="Good EM fit")
    return ScoreResult(fit_score=30, matched_track="", reasoning="Poor fit")


class TestRunPipeline:
    def test_produces_brief(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            brief_path = run_pipeline(config, project_root)
            assert brief_path.exists()

    def test_brief_contains_passing_job(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            brief_path = run_pipeline(config, project_root)
            content = brief_path.read_text()
            # BigCo VP Eng passes all filters and scores 91
            assert "BigCo" in content

    def test_scores_filtered_jobs(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)

            db = sqlite3.connect(str(project_root / "jobs.db"))
            db.row_factory = sqlite3.Row
            bigco = db.execute(
                "SELECT status, fit_score, matched_track FROM jobs WHERE company = 'BigCo'"
            ).fetchone()
            assert bigco["status"] == "scored"
            assert bigco["fit_score"] == 91
            assert bigco["matched_track"] == "vp"
            db.close()

    def test_filters_ic_role(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)

            db = sqlite3.connect(str(project_root / "jobs.db"))
            db.row_factory = sqlite3.Row
            smallco = db.execute(
                "SELECT status, reject_reason FROM jobs WHERE company = 'SmallCo'"
            ).fetchone()
            assert smallco["status"] == "rejected"
            db.close()

    def test_filters_bad_location(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)

            db = sqlite3.connect(str(project_root / "jobs.db"))
            db.row_factory = sqlite3.Row
            smallco = db.execute(
                "SELECT status, reject_reason FROM jobs WHERE company = 'SmallCo'"
            ).fetchone()
            assert smallco["status"] == "rejected"
            db.close()

    def test_creates_run_log(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)

            db = sqlite3.connect(str(project_root / "jobs.db"))
            db.row_factory = sqlite3.Row
            logs = db.execute("SELECT * FROM run_logs").fetchall()
            assert len(logs) == 1
            assert logs[0]["jobs_collected"] == 3
            db.close()

    def test_creates_source_run(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)

            db = sqlite3.connect(str(project_root / "jobs.db"))
            db.row_factory = sqlite3.Row
            runs = db.execute("SELECT * FROM source_runs").fetchall()
            assert len(runs) == 1
            assert runs[0]["status"] == "success"
            assert runs[0]["jobs_found"] == 3
            db.close()

    def test_source_failure_doesnt_kill_pipeline(self, config, project_root):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            failing = MagicMock()
            failing.fetch_new.side_effect = Exception("API error")
            mock_gc.return_value = {"broken_source": failing}

            brief_path = run_pipeline(config, project_root)
            assert brief_path.exists()

            db = sqlite3.connect(str(project_root / "jobs.db"))
            db.row_factory = sqlite3.Row
            runs = db.execute("SELECT * FROM source_runs").fetchall()
            assert runs[0]["status"] == "failure"
            assert "API error" in runs[0]["error_message"]
            db.close()

    def test_idempotent_runs(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)
            run_pipeline(config, project_root)

            db = sqlite3.connect(str(project_root / "jobs.db"))
            count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            assert count == 3
            db.close()


class TestCollectOnly:
    def test_returns_count(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc:
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            count = run_collect_only(config, project_root)
            assert count == 3


class TestBriefOnly:
    def test_generates_brief(self, config, project_root, mock_hn_jobs):
        with patch("shortlist.pipeline._get_collectors") as mock_gc, \
             patch("shortlist.pipeline.score_jobs_parallel", side_effect=_mock_score_jobs_parallel):
            collector = MagicMock()
            collector.fetch_new.return_value = mock_hn_jobs
            mock_gc.return_value = {"hn": collector}

            run_pipeline(config, project_root)

        path = run_brief_only(config, project_root)
        assert path.exists()
