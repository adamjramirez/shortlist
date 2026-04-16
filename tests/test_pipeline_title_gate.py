"""Integration tests for title gate wired into run_pipeline_pg."""
import contextlib
from unittest.mock import patch, MagicMock

import shortlist.pipeline as pipeline_mod
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, LLMConfig
from shortlist.processors.scorer import ScoreResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(title_gate_enabled: bool = True):
    return Config(
        fit_context="VP Engineering at AI-native company",
        filters=Filters(
            location=LocationFilter(remote=True),
            salary=SalaryFilter(min_base=0),
        ),
        llm=LLMConfig(
            model="gemini-2.0-flash",
            max_jobs_per_run=50,
            title_gate_enabled=title_gate_enabled,
        ),
    )


def _make_row(row_id: int, title: str = "VP Engineering") -> dict:
    """Minimal fake DB row dict that satisfies _row_to_raw_job and pgdb.update_job."""
    return {
        "id": row_id,
        "title": title,
        "company": f"Company{row_id}",
        "url": f"https://example.com/{row_id}",
        "description": f"A great {title} role.",
        "location": "Remote",
        "salary_text": None,
        "description_hash": f"hash{row_id}",
        "sources_seen": ["hn"],
        "fit_score": None,
        "score_reasoning": None,
        "yellow_flags": None,
        "enrichment": None,
        "interest_note": None,
        "career_page_url": None,
    }


FILTERED_ROWS = [_make_row(1), _make_row(2), _make_row(3)]


def _mock_fetch_jobs(conn, user_id, status, **kwargs):
    """Return filtered rows only when status='filtered'; empty otherwise."""
    if status == "filtered":
        return list(FILTERED_ROWS)
    return []


def _mock_score_jobs_parallel(score_inputs, config, max_workers=4, on_scored=None, cancel_event=None):
    """Return a passing ScoreResult per job."""
    return [
        (row_id, ScoreResult(fit_score=80, matched_track="vp", reasoning="Good"))
        for row_id, _ in score_inputs
    ]


def _run_with_patches(extra_patches: list, config):
    """Run run_pipeline_pg with common + extra patches; swallow all exceptions."""
    base = [
        patch("shortlist.pgdb.get_pg_connection", return_value=MagicMock()),
        patch("shortlist.pgdb.ensure_nextplay_cache_table"),
        patch("shortlist.pgdb.ensure_career_page_sources_table"),
        patch("shortlist.pipeline._ensure_llm"),
        patch("shortlist.pipeline._get_collectors", return_value={}),
        patch("shortlist.pgdb.fetch_companies", return_value=[]),
        patch("shortlist.pgdb.get_active_career_page_sources", return_value=[]),
        patch("shortlist.pgdb.log_source_run"),
        patch("shortlist.pipeline.enrich_company", return_value=None),
        patch("shortlist.pipeline.tailor_jobs_parallel", return_value=[]),
        patch("shortlist.pgdb.fetch_jobs", side_effect=_mock_fetch_jobs),
    ]
    with contextlib.ExitStack() as stack:
        for p in base + extra_patches:
            stack.enter_context(p)
        try:
            pipeline_mod.run_pipeline_pg(config, db_url="postgresql://fake", user_id=1)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 1: gate rejects job 2, scorer gets 1 and 3 only
# ---------------------------------------------------------------------------

def test_score_filtered_moves_failed_titles_to_title_rejected():
    """Title gate: rejected job gets status=title_rejected; scorer only sees passing jobs."""
    update_calls = []
    scored_row_ids = []

    def capturing_score(score_inputs, config, max_workers=4, on_scored=None, cancel_event=None):
        scored_row_ids.extend(row_id for row_id, _ in score_inputs)
        return _mock_score_jobs_parallel(score_inputs, config)

    def capturing_update_job(conn, job_id, **fields):
        update_calls.append((job_id, fields))

    gate_decisions = {1: (True, ""), 2: (False, "too junior"), 3: (True, "")}

    extra = [
        patch.object(pipeline_mod, "gate_titles", return_value=(gate_decisions, 1)),
        patch("shortlist.pgdb.update_job", side_effect=capturing_update_job),
        patch("shortlist.pipeline.score_jobs_parallel", side_effect=capturing_score),
    ]
    _run_with_patches(extra, _make_config())

    # Job 2 must have been updated to title_rejected
    title_rejected_calls = [
        (job_id, fields)
        for job_id, fields in update_calls
        if fields.get("status") == "title_rejected"
    ]
    assert len(title_rejected_calls) == 1, f"Expected 1 title_rejected call, got: {title_rejected_calls}"
    assert title_rejected_calls[0][0] == 2
    assert title_rejected_calls[0][1]["reject_reason"] == "too junior"

    # Scorer must have received row_ids 1 and 3, not 2
    assert 1 in scored_row_ids
    assert 3 in scored_row_ids
    assert 2 not in scored_row_ids, f"Row 2 should not reach the scorer, got: {scored_row_ids}"


# ---------------------------------------------------------------------------
# Test 2: title gate disabled — gate_titles not called, all 3 reach scorer
# ---------------------------------------------------------------------------

def test_score_filtered_respects_title_gate_disabled():
    """When title_gate_enabled=False, gate_titles is never called and all jobs score."""
    scored_row_ids = []

    def capturing_score(score_inputs, config, max_workers=4, on_scored=None, cancel_event=None):
        scored_row_ids.extend(row_id for row_id, _ in score_inputs)
        return _mock_score_jobs_parallel(score_inputs, config)

    mock_gate = MagicMock()
    extra = [
        patch.object(pipeline_mod, "gate_titles", mock_gate),
        patch("shortlist.pgdb.update_job", return_value=None),
        patch("shortlist.pipeline.score_jobs_parallel", side_effect=capturing_score),
    ]
    _run_with_patches(extra, _make_config(title_gate_enabled=False))

    mock_gate.assert_not_called()
    # All 3 filtered jobs should reach the scorer
    assert set(scored_row_ids) == {1, 2, 3}, f"Expected {{1,2,3}}, got {scored_row_ids}"


# ---------------------------------------------------------------------------
# Test 3: gate returns empty dict (fail-open) — all 3 reach scorer
# ---------------------------------------------------------------------------

def test_score_filtered_gate_all_pass_when_gate_returns_empty_dict():
    """When gate_titles returns {}, .get() default (True,'') passes everything through."""
    scored_row_ids = []
    update_calls = []

    def capturing_score(score_inputs, config, max_workers=4, on_scored=None, cancel_event=None):
        scored_row_ids.extend(row_id for row_id, _ in score_inputs)
        return _mock_score_jobs_parallel(score_inputs, config)

    def capturing_update_job(conn, job_id, **fields):
        update_calls.append((job_id, fields))

    extra = [
        patch.object(pipeline_mod, "gate_titles", return_value=({}, 1)),
        patch("shortlist.pgdb.update_job", side_effect=capturing_update_job),
        patch("shortlist.pipeline.score_jobs_parallel", side_effect=capturing_score),
    ]
    _run_with_patches(extra, _make_config())

    # No title_rejected updates
    title_rejected = [
        (job_id, fields)
        for job_id, fields in update_calls
        if fields.get("status") == "title_rejected"
    ]
    assert title_rejected == [], f"Expected no title_rejected calls, got: {title_rejected}"

    # All 3 should reach the scorer
    assert set(scored_row_ids) == {1, 2, 3}, f"Expected {{1,2,3}}, got {scored_row_ids}"
