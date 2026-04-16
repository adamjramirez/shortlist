"""Tests for shortlist/expiry.py — proactive URL-based job expiry checking."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from shortlist.expiry import (
    check_job_url,
    check_expiry_batch,
    _parse_greenhouse_api_url,
    _parse_lever_api_url,
    _run_batch,
)


# ---------------------------------------------------------------------------
# URL parsers
# ---------------------------------------------------------------------------

def test_parse_greenhouse_api_url_job_boards():
    url = "https://job-boards.greenhouse.io/anthropic/jobs/4887952008"
    result = _parse_greenhouse_api_url(url)
    assert result == "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs/4887952008"


def test_parse_greenhouse_api_url_boards():
    url = "https://boards.greenhouse.io/chime/jobs/8465206002"
    result = _parse_greenhouse_api_url(url)
    assert result == "https://boards-api.greenhouse.io/v1/boards/chime/jobs/8465206002"


def test_parse_greenhouse_api_url_custom_domain():
    """Custom domain (samsara.com etc.) → returns None, use stored URL directly."""
    url = "https://www.samsara.com/company/careers/roles/7644634?gh_jid=7644634"
    assert _parse_greenhouse_api_url(url) is None


def test_parse_lever_api_url():
    url = "https://jobs.lever.co/soraschools/abc123-def456-ghi789"
    result = _parse_lever_api_url(url)
    assert result == "https://api.lever.co/v0/postings/soraschools/abc123-def456-ghi789"


def test_parse_lever_api_url_non_lever():
    assert _parse_lever_api_url("https://example.com/jobs/123") is None


# ---------------------------------------------------------------------------
# check_job_url — LinkedIn
# ---------------------------------------------------------------------------

def test_check_linkedin_404():
    """HEAD 404 → job is gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is False


def test_check_linkedin_200():
    """HEAD 200 → job is active."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is True


def test_check_linkedin_error():
    """Network error → unknown, return None."""
    with patch("shortlist.expiry.http.head", side_effect=Exception("timeout")):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is None


# ---------------------------------------------------------------------------
# check_job_url — Greenhouse (native greenhouse.io URL)
# ---------------------------------------------------------------------------

def test_check_greenhouse_native_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://job-boards.greenhouse.io/anthropic/jobs/4887952008",
            ["greenhouse"],
        )
    assert result is False


def test_check_greenhouse_native_200():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://job-boards.greenhouse.io/anthropic/jobs/4887952008",
            ["greenhouse"],
        )
    assert result is True


def test_check_greenhouse_custom_domain_404():
    """Custom domain Greenhouse job → HEAD stored URL, 404 = gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("shortlist.expiry.http.head", return_value=mock_resp) as mock_head:
        result = check_job_url(
            "https://www.samsara.com/company/careers/roles/7644634?gh_jid=7644634",
            ["greenhouse"],
        )
    assert result is False
    # Must have called HEAD on the stored URL, not a greenhouse.io API URL
    call_url = mock_head.call_args[0][0]
    assert "samsara.com" in call_url


def test_check_greenhouse_custom_domain_200():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://www.samsara.com/company/careers/roles/7644634",
            ["greenhouse"],
        )
    assert result is True


# ---------------------------------------------------------------------------
# check_job_url — Lever
# ---------------------------------------------------------------------------

def test_check_lever_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.lever.co/soraschools/abc123-def456",
            ["lever"],
        )
    assert result is False


def test_check_lever_200():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.lever.co/soraschools/abc123-def456",
            ["lever"],
        )
    assert result is True


# ---------------------------------------------------------------------------
# check_job_url — Ashby
# ---------------------------------------------------------------------------

def test_check_ashby_active():
    """Title contains '@' → job is active."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><head><title>Founding Engineer @ Mobasi</title></head></html>"
    with patch("shortlist.expiry.http.get", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.ashbyhq.com/mobasi/b385d2bb",
            ["ashby"],
        )
    assert result is True


def test_check_ashby_expired():
    """Title is generic 'Jobs' → job is gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><head><title>Jobs</title></head></html>"
    with patch("shortlist.expiry.http.get", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.ashbyhq.com/mobasi/00000000",
            ["ashby"],
        )
    assert result is False


def test_check_ashby_error():
    with patch("shortlist.expiry.http.get", side_effect=Exception("timeout")):
        result = check_job_url("https://jobs.ashbyhq.com/co/abc", ["ashby"])
    assert result is None


# ---------------------------------------------------------------------------
# check_job_url — unknown source
# ---------------------------------------------------------------------------

def test_check_unknown_source():
    """Source not in checkable list → return None (skip)."""
    result = check_job_url("https://news.ycombinator.com/item?id=123", ["hn"])
    assert result is None


# ---------------------------------------------------------------------------
# check_expiry_batch
# ---------------------------------------------------------------------------

def _make_fake_pgdb(jobs):
    """Return a fake pgdb module with controllable job list."""
    fake = MagicMock()
    fake.get_jobs_for_expiry_check.return_value = jobs
    return fake


def test_check_expiry_batch_closes_expired(tmp_path):
    """Batch marks expired jobs closed and alive jobs checked-not-closed."""
    jobs = [
        {"id": 1, "url": "https://www.linkedin.com/jobs/view/1",
         "sources_seen": ["linkedin"], "fit_score": 85},
        {"id": 2, "url": "https://www.linkedin.com/jobs/view/2",
         "sources_seen": ["linkedin"], "fit_score": 80},
    ]

    responses = {
        "https://www.linkedin.com/jobs/view/1": 404,
        "https://www.linkedin.com/jobs/view/2": 200,
    }

    def mock_head(url, **kwargs):
        resp = MagicMock()
        resp.status_code = responses[url]
        return resp

    fake_conn = MagicMock()

    with patch("shortlist.expiry.pgdb") as mock_pgdb, \
         patch("shortlist.expiry.http.head", side_effect=mock_head), \
         patch("shortlist.expiry.pgdb.get_pg_connection", return_value=fake_conn):
        mock_pgdb.get_pg_connection.return_value = fake_conn
        mock_pgdb.get_jobs_for_expiry_check.return_value = jobs

        from shortlist.expiry import check_expiry_batch
        result = check_expiry_batch.__wrapped__(fake_conn, limit=10) \
            if hasattr(check_expiry_batch, "__wrapped__") \
            else _run_batch_with_conn(fake_conn, jobs, mock_head)

    assert result["checked"] == 2
    assert result["closed"] == 1
    assert result["errors"] == 0


def _run_batch_with_conn(conn, jobs, mock_head):
    """Helper to run batch logic directly with a pre-built conn."""
    import shortlist.expiry as exp
    import shortlist.pgdb as pgdb_mod

    marked = []

    def fake_get_jobs(c, limit=20):
        return jobs

    def fake_mark(c, job_id, is_closed, closed_reason=None):
        marked.append((job_id, is_closed))

    orig_get = pgdb_mod.get_jobs_for_expiry_check
    orig_mark = pgdb_mod.mark_expiry_checked
    pgdb_mod.get_jobs_for_expiry_check = fake_get_jobs
    pgdb_mod.mark_expiry_checked = fake_mark

    try:
        result = exp._run_batch(conn, limit=10)
    finally:
        pgdb_mod.get_jobs_for_expiry_check = orig_get
        pgdb_mod.mark_expiry_checked = orig_mark

    return result


def test_check_expiry_batch_connection_closed_on_error():
    """DB connection is closed even when an exception occurs."""
    fake_conn = MagicMock()

    with patch("shortlist.expiry.pgdb.get_pg_connection", return_value=fake_conn), \
         patch("shortlist.expiry.pgdb.get_jobs_for_expiry_check",
               side_effect=Exception("db error")):
        from shortlist.expiry import check_expiry_batch
        result = check_expiry_batch("postgresql://fake/db")

    fake_conn.close.assert_called_once()
    assert result["checked"] == 0
    assert result["errors"] == 1


def test_check_expiry_batch_empty_returns_zero():
    """No eligible jobs → returns zeros, no error."""
    fake_conn = MagicMock()

    with patch("shortlist.expiry.pgdb.get_pg_connection", return_value=fake_conn), \
         patch("shortlist.expiry.pgdb.get_jobs_for_expiry_check", return_value=[]):
        from shortlist.expiry import check_expiry_batch
        result = check_expiry_batch("postgresql://fake/db")

    assert result == {
        "checked": 0, "closed": 0, "live": 0,
        "unknown": 0, "skipped_recent": 0, "errors": 0,
    }
    fake_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# check_job_url — LinkedIn transient failures → None (not False)
# ---------------------------------------------------------------------------

def test_check_linkedin_403():
    """403 = bot challenge / auth wall → unknown, not gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is None


def test_check_linkedin_429():
    """429 = rate limited → unknown, not gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is None


def test_check_linkedin_500():
    """5xx = server error → unknown, not gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is None


def test_check_linkedin_302():
    """3xx redirect → unknown (may be login wall), not gone."""
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url("https://www.linkedin.com/jobs/view/123", ["linkedin"])
    assert result is None


# ---------------------------------------------------------------------------
# check_job_url — Greenhouse transient failures → None
# ---------------------------------------------------------------------------

def test_check_greenhouse_403():
    """Greenhouse 403 → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://job-boards.greenhouse.io/anthropic/jobs/4887952008",
            ["greenhouse"],
        )
    assert result is None


def test_check_greenhouse_429():
    """Greenhouse 429 → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://job-boards.greenhouse.io/anthropic/jobs/4887952008",
            ["greenhouse"],
        )
    assert result is None


def test_check_greenhouse_500():
    """Greenhouse 5xx → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://job-boards.greenhouse.io/anthropic/jobs/4887952008",
            ["greenhouse"],
        )
    assert result is None


# ---------------------------------------------------------------------------
# check_job_url — Lever transient failures → None
# ---------------------------------------------------------------------------

def test_check_lever_403():
    """Lever 403 → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.lever.co/soraschools/abc123-def456",
            ["lever"],
        )
    assert result is None


def test_check_lever_429():
    """Lever 429 → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.lever.co/soraschools/abc123-def456",
            ["lever"],
        )
    assert result is None


def test_check_lever_500():
    """Lever 5xx → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("shortlist.expiry.http.head", return_value=mock_resp):
        result = check_job_url(
            "https://jobs.lever.co/soraschools/abc123-def456",
            ["lever"],
        )
    assert result is None


def test_check_lever_non_lever_url():
    """Non-Lever URL with lever source → None (can't parse API URL)."""
    result = check_job_url("https://example.com/jobs/abc123", ["lever"])
    assert result is None


# ---------------------------------------------------------------------------
# check_job_url — Ashby transient failures → None
# ---------------------------------------------------------------------------

def test_check_ashby_non_200():
    """Ashby non-200 → unknown (don't reach title parsing)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("shortlist.expiry.http.get", return_value=mock_resp):
        result = check_job_url("https://jobs.ashbyhq.com/co/abc", ["ashby"])
    assert result is None


def test_check_ashby_403():
    """Ashby 403 → unknown."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    with patch("shortlist.expiry.http.get", return_value=mock_resp):
        result = check_job_url("https://jobs.ashbyhq.com/co/abc", ["ashby"])
    assert result is None


def test_check_ashby_200_no_title():
    """Ashby 200 but no title tag → unknown (parse error)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>No title here</body></html>"
    with patch("shortlist.expiry.http.get", return_value=mock_resp):
        result = check_job_url("https://jobs.ashbyhq.com/co/abc", ["ashby"])
    assert result is None


# ---------------------------------------------------------------------------
# Recency skip — batch level
# ---------------------------------------------------------------------------

def _make_job(job_id: int, url: str, sources: list, last_seen: datetime) -> dict:
    return {
        "id": job_id,
        "url": url,
        "sources_seen": sources,
        "fit_score": 85,
        "last_seen": last_seen,
    }


def test_recency_skip_no_http_call():
    """Job last_seen < 24h ago → skip HTTP call entirely, returns None result."""
    recent = datetime.now(timezone.utc) - timedelta(hours=6)
    job = _make_job(99, "https://www.linkedin.com/jobs/view/99", ["linkedin"], recent)

    fake_conn = MagicMock()
    mock_mark = MagicMock()

    with patch("shortlist.expiry.pgdb.get_jobs_for_expiry_check", return_value=[job]), \
         patch("shortlist.expiry.pgdb.mark_expiry_checked", mock_mark), \
         patch("shortlist.expiry.http.head") as mock_head:
        result = _run_batch(fake_conn, limit=10)

    # No HTTP call should have been made
    mock_head.assert_not_called()
    # Job is not closed — errors count covers the skip
    assert result["closed"] == 0


def test_recency_skip_old_job_makes_http_call():
    """Job last_seen > 24h ago → HTTP call proceeds normally."""
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    job = _make_job(
        100,
        "https://job-boards.greenhouse.io/anthropic/jobs/4887952008",
        ["greenhouse"],
        old,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    fake_conn = MagicMock()

    with patch("shortlist.expiry.pgdb.get_jobs_for_expiry_check", return_value=[job]), \
         patch("shortlist.expiry.pgdb.mark_expiry_checked"), \
         patch("shortlist.expiry.http.head", return_value=mock_resp) as mock_head:
        result = _run_batch(fake_conn, limit=10)

    mock_head.assert_called_once()
    assert result["checked"] == 1


# ---------------------------------------------------------------------------
# _run_batch — observability: close decisions logged at INFO
# ---------------------------------------------------------------------------

def test_run_batch_logs_close_at_info(caplog):
    """Close decisions should be logged at INFO level with job id, source, url."""
    import logging
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    job = _make_job(
        42,
        "https://www.linkedin.com/jobs/view/42",
        ["linkedin"],
        old,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    fake_conn = MagicMock()

    with patch("shortlist.expiry.pgdb.get_jobs_for_expiry_check", return_value=[job]), \
         patch("shortlist.expiry.pgdb.mark_expiry_checked"), \
         patch("shortlist.expiry.http.head", return_value=mock_resp), \
         caplog.at_level(logging.INFO, logger="shortlist.expiry"):
        _run_batch(fake_conn, limit=10)

    close_logs = [r for r in caplog.records if "url_check close" in r.message]
    assert len(close_logs) == 1
    assert "42" in close_logs[0].message
    assert "linkedin" in close_logs[0].message
