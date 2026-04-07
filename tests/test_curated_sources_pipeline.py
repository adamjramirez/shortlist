"""Tests for curated career page sources pipeline integration."""
from unittest.mock import patch, MagicMock, call
import pytest

from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter, LLMConfig
from shortlist.collectors.base import RawJob


def _make_config():
    return Config(
        fit_context="VP Engineering at AI-native company",
        filters=Filters(
            location=LocationFilter(remote=True),
            salary=SalaryFilter(min_base=0),
            role_type=RoleTypeFilter(reject_explicit_ic=False),
        ),
        llm=LLMConfig(model="gemini-2.0-flash", max_jobs_per_run=50),
    )


def _ashby_job(title="VP Engineering", company="Momentic"):
    return RawJob(
        title=title,
        company=company,
        url=f"https://jobs.ashbyhq.com/momentic/{title.lower().replace(' ', '-')}",
        description=f"{title} at {company}. Remote. $300k.",
        source="curated",
        location="Remote",
    )


# ── CuratedSourcesCollector ───────────────────────────────────────────────────

def test_curated_collector_fetches_ashby_jobs():
    """CuratedSourcesCollector calls fetch_ashby_jobs for ashby sources."""
    from shortlist.collectors.curated import CuratedSourcesCollector

    sources = [
        {"id": 1, "company_name": "Momentic", "career_url": "https://jobs.ashbyhq.com/momentic",
         "ats": "ashby", "slug": "momentic", "status": "active"},
    ]
    expected_jobs = [_ashby_job()]

    with patch("shortlist.collectors.curated.fetch_ashby_jobs", return_value=expected_jobs) as mock_fetch:
        collector = CuratedSourcesCollector(sources)
        results = collector.fetch_new()

    mock_fetch.assert_called_once_with("momentic")
    assert len(results) == 1
    assert results[0].company == "Momentic"


def test_curated_collector_fetches_greenhouse_jobs():
    from shortlist.collectors.curated import CuratedSourcesCollector

    sources = [
        {"id": 2, "company_name": "Grotto AI", "career_url": "https://boards.greenhouse.io/grotto",
         "ats": "greenhouse", "slug": "grotto", "status": "active"},
    ]
    job = RawJob(title="CTO", company="Grotto AI",
                 url="https://boards.greenhouse.io/grotto/jobs/1",
                 description="CTO role.", source="curated", location="Remote")

    with patch("shortlist.collectors.curated.fetch_greenhouse_jobs", return_value=[job]):
        collector = CuratedSourcesCollector(sources)
        results = collector.fetch_new()

    assert len(results) == 1
    assert results[0].title == "CTO"


def test_curated_collector_fetches_direct_career_page():
    from shortlist.collectors.curated import CuratedSourcesCollector

    sources = [
        {"id": 3, "company_name": "Ando", "career_url": "https://www.ando.work/careers",
         "ats": "direct", "slug": None, "status": "active"},
    ]
    job = RawJob(title="VP Engineering", company="Ando",
                 url="https://www.ando.work/careers/vp-eng",
                 description="VP Eng role.", source="curated", location="Remote")

    with patch("shortlist.collectors.curated.fetch_career_page", return_value=[job]):
        collector = CuratedSourcesCollector(sources)
        results = collector.fetch_new()

    assert len(results) == 1


def test_curated_collector_reports_results_via_callback():
    """on_fetched callback is called once per source with (career_url, jobs, error)."""
    from shortlist.collectors.curated import CuratedSourcesCollector

    sources = [
        {"id": 1, "company_name": "Momentic", "career_url": "https://jobs.ashbyhq.com/momentic",
         "ats": "ashby", "slug": "momentic", "status": "active"},
        {"id": 2, "company_name": "DeadCo", "career_url": "https://jobs.ashbyhq.com/deadco",
         "ats": "ashby", "slug": "deadco", "status": "active"},
    ]
    calls = []

    with patch("shortlist.collectors.curated.fetch_ashby_jobs", side_effect=[
        [_ashby_job()],  # momentic: 1 job
        [],              # deadco: 0 jobs
    ]):
        collector = CuratedSourcesCollector(sources, on_fetched=lambda url, jobs, err: calls.append((url, len(jobs), err)))
        collector.fetch_new()

    assert len(calls) == 2
    assert calls[0] == ("https://jobs.ashbyhq.com/momentic", 1, None)
    assert calls[1] == ("https://jobs.ashbyhq.com/deadco", 0, None)


def test_curated_collector_handles_fetch_error():
    """Fetch error is captured; source continues; callback gets error string."""
    from shortlist.collectors.curated import CuratedSourcesCollector

    sources = [
        {"id": 1, "company_name": "BrokenCo", "career_url": "https://jobs.ashbyhq.com/broken",
         "ats": "ashby", "slug": "broken", "status": "active"},
    ]
    calls = []

    with patch("shortlist.collectors.curated.fetch_ashby_jobs", side_effect=Exception("404 Not Found")):
        collector = CuratedSourcesCollector(
            sources, on_fetched=lambda url, jobs, err: calls.append((url, jobs, err))
        )
        results = collector.fetch_new()

    assert results == []
    assert len(calls) == 1
    assert calls[0][2] == "404 Not Found"


def test_curated_collector_empty_sources():
    from shortlist.collectors.curated import CuratedSourcesCollector
    collector = CuratedSourcesCollector([])
    assert collector.fetch_new() == []


# ── Pipeline integration ──────────────────────────────────────────────────────

def test_pipeline_fetches_curated_sources(monkeypatch):
    """run_pipeline_pg reads active curated sources and fetches jobs from them."""
    from shortlist.pipeline import run_pipeline_pg

    active_sources = [
        {"id": 1, "company_name": "Momentic", "career_url": "https://jobs.ashbyhq.com/momentic",
         "ats": "ashby", "slug": "momentic", "status": "active"},
    ]
    update_calls = []

    monkeypatch.setattr("shortlist.pgdb.fetch_companies", lambda *a, **kw: [])
    monkeypatch.setattr("shortlist.pgdb.get_active_career_page_sources", lambda conn: active_sources)
    monkeypatch.setattr(
        "shortlist.pgdb.update_career_page_source_after_fetch",
        lambda conn, career_url, jobs_found, fetch_error: update_calls.append((career_url, jobs_found, fetch_error)),
    )

    with patch("shortlist.pipeline._get_collectors", return_value={}), \
         patch("shortlist.pgdb.get_pg_connection") as mock_conn, \
         patch("shortlist.pgdb.ensure_nextplay_cache_table"), \
         patch("shortlist.pgdb.ensure_career_page_sources_table"), \
         patch("shortlist.pipeline._ensure_llm"), \
         patch("shortlist.collectors.curated.fetch_ashby_jobs", return_value=[_ashby_job()]):

        mock_conn.return_value = MagicMock()
        try:
            run_pipeline_pg(_make_config(), db_url="postgresql://fake", user_id=1)
        except Exception:
            pass

    assert any(url == "https://jobs.ashbyhq.com/momentic" for url, _, _ in update_calls)


def test_pipeline_updates_state_after_curated_fetch(monkeypatch):
    """State update is called even when 0 jobs found."""
    from shortlist.pipeline import run_pipeline_pg

    active_sources = [
        {"id": 1, "company_name": "EmptyCo", "career_url": "https://jobs.ashbyhq.com/empty",
         "ats": "ashby", "slug": "empty", "status": "active"},
    ]
    update_calls = []

    monkeypatch.setattr("shortlist.pgdb.fetch_companies", lambda *a, **kw: [])
    monkeypatch.setattr("shortlist.pgdb.get_active_career_page_sources", lambda conn: active_sources)
    monkeypatch.setattr(
        "shortlist.pgdb.update_career_page_source_after_fetch",
        lambda conn, career_url, jobs_found, fetch_error: update_calls.append((career_url, jobs_found, fetch_error)),
    )

    with patch("shortlist.pipeline._get_collectors", return_value={}), \
         patch("shortlist.pgdb.get_pg_connection") as mock_conn, \
         patch("shortlist.pgdb.ensure_nextplay_cache_table"), \
         patch("shortlist.pgdb.ensure_career_page_sources_table"), \
         patch("shortlist.pipeline._ensure_llm"), \
         patch("shortlist.collectors.curated.fetch_ashby_jobs", return_value=[]):

        mock_conn.return_value = MagicMock()
        try:
            run_pipeline_pg(_make_config(), db_url="postgresql://fake", user_id=1)
        except Exception:
            pass

    assert any(jobs == 0 for _, jobs, _ in update_calls)
