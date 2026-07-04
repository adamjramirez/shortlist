"""Tests for the Getro VC job-board collector."""
from unittest.mock import MagicMock, patch

import pytest

from shortlist.collectors.getro import (
    GetroCollector, _getro_job_to_rawjob, _format_getro_salary,
)


def _job(**over):
    j = {
        "title": "VP of Engineering",
        "url": "https://boards.greenhouse.io/acme/jobs/123?utm=x",
        "organization": {"name": "Acme AI", "slug": "acme"},
        "searchable_locations": ["San Francisco, CA, USA", "United States"],
        "created_at": 1751500800,  # 2025-07-03
        "work_mode": "remote",
        "compensation_amount_min_cents": 25000000,   # $250k
        "compensation_amount_max_cents": 34000000,   # $340k
        "compensation_currency": "USD",
    }
    j.update(over)
    return j


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


def _resp(jobs):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"results": {"jobs": jobs, "count": len(jobs)}}
    return r


class TestParse:
    def test_maps_core_fields(self):
        rj = _getro_job_to_rawjob(_job())
        assert rj.title == "VP of Engineering"
        assert rj.company == "Acme AI"
        assert rj.url == "https://boards.greenhouse.io/acme/jobs/123"  # query stripped
        assert rj.location == "San Francisco, CA, USA"
        assert rj.posted_at == "2025-07-03"

    def test_source_is_detected_ats_not_getro(self):
        """A greenhouse url → source 'greenhouse' so expiry/dedup work."""
        rj = _getro_job_to_rawjob(_job())
        assert rj.source == "greenhouse"

    def test_source_falls_back_to_getro_for_unknown_url(self):
        rj = _getro_job_to_rawjob(_job(url="https://acme.com/careers/vp-eng"))
        assert rj.source == "getro"

    def test_missing_url_or_title_returns_none(self):
        assert _getro_job_to_rawjob(_job(url="")) is None
        assert _getro_job_to_rawjob(_job(title=None)) is None

    def test_null_organization_uses_unknown(self):
        rj = _getro_job_to_rawjob(_job(organization=None))
        assert rj.company == "Unknown"

    def test_salary_formatting(self):
        assert _format_getro_salary(_job()) == "$250k-$340k"

    def test_salary_none_when_absent(self):
        j = _job(compensation_amount_min_cents=None, compensation_amount_max_cents=None)
        assert _format_getro_salary(j) is None


class TestCollector:
    def test_fetch_parses_and_dedups(self):
        page = [_job(), _job(url="https://boards.greenhouse.io/acme/jobs/123")]  # dup url
        with patch("shortlist.collectors.getro.http.post",
                   side_effect=[_resp(page), _resp([])]):
            jobs = GetroCollector([{"name": "Thrive", "collection_id": 2105}],
                                  max_pages=2, hits_per_page=50).fetch_new()
        assert len(jobs) == 1  # deduped

    def test_title_filter_applied(self):
        jobs_data = [_job(title="VP of Engineering"),
                     _job(title="Barista", url="https://boards.greenhouse.io/acme/jobs/999")]
        is_leadership = lambda t: "VP" in t or "Chief" in t
        with patch("shortlist.collectors.getro.http.post",
                   side_effect=[_resp(jobs_data), _resp([])]):
            jobs = GetroCollector([{"name": "T", "collection_id": 1}],
                                  title_filter=is_leadership, max_pages=2).fetch_new()
        assert [j.title for j in jobs] == ["VP of Engineering"]

    def test_pagination_stops_on_short_page(self):
        """A page smaller than hits_per_page is the last page — no extra call."""
        with patch("shortlist.collectors.getro.http.post",
                   return_value=_resp([_job()])) as mock_post:
            GetroCollector([{"name": "T", "collection_id": 1}],
                           max_pages=5, hits_per_page=50).fetch_new()
        assert mock_post.call_count == 1

    def test_non_200_breaks_gracefully(self):
        bad = MagicMock(); bad.status_code = 500
        with patch("shortlist.collectors.getro.http.post", return_value=bad):
            jobs = GetroCollector([{"name": "T", "collection_id": 1}]).fetch_new()
        assert jobs == []

    def test_exception_breaks_gracefully(self):
        with patch("shortlist.collectors.getro.http.post", side_effect=Exception("boom")):
            jobs = GetroCollector([{"name": "T", "collection_id": 1}]).fetch_new()
        assert jobs == []

    def test_query_sent_in_body(self):
        with patch("shortlist.collectors.getro.http.post",
                   return_value=_resp([])) as mock_post:
            GetroCollector([{"name": "T", "collection_id": 7}],
                           queries=["engineering"], max_pages=1).fetch_new()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["query"] == "engineering"
        assert "collections/7/search/jobs" in mock_post.call_args[0][0]
