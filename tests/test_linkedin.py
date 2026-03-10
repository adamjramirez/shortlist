"""Tests for LinkedIn collector."""
import re
from unittest.mock import patch, MagicMock

import pytest

from shortlist.collectors.linkedin import LinkedInCollector, _clean_html


MOCK_SEARCH_HTML = """
<li>
<div class="base-card relative w-full hover:no-underline focus:no-underline
    base-card--link base-search-card base-search-card--link job-search-card"
    data-entity-urn="urn:li:jobPosting:1234567890">
    <a class="base-card__full-link absolute top-0"
       href="https://www.linkedin.com/jobs/view/vp-eng-at-acme-1234567890?trk=123">
        VP Engineering
    </a>
    <h4 class="base-search-card__subtitle">
        <a href="/company/acme">Acme Corp</a>
    </h4>
    <span class="job-search-card__location">United States</span>
    <time datetime="2026-03-09">2 days ago</time>
</div>
</li>
<li>
<div class="base-card relative w-full hover:no-underline focus:no-underline
    base-card--link base-search-card base-search-card--link job-search-card"
    data-entity-urn="urn:li:jobPosting:9876543210">
    <a class="base-card__full-link absolute top-0"
       href="https://www.linkedin.com/jobs/view/em-at-bigco-9876543210?trk=456">
        Engineering Manager, Platform
    </a>
    <h4 class="base-search-card__subtitle">
        <a href="/company/bigco">BigCo Inc</a>
    </h4>
    <span class="job-search-card__location">Remote</span>
    <time datetime="2026-03-10">1 day ago</time>
</div>
</li>
"""

MOCK_DETAIL_HTML = """
<div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5">
    <p>We're looking for a VP of Engineering to lead our 40-person team.</p>
    <p>Requirements: 10+ years experience, scaling teams from 20 to 100+.</p>
    <p>Compensation: $300k-$350k + equity.</p>
</div>
"""


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    """Disable rate limiting in tests."""
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


class TestLinkedInCollector:
    @pytest.fixture
    def collector(self):
        return LinkedInCollector(
            searches=[{"keywords": "VP Engineering", "f_WT": "2"}],
            max_pages=1,
        )

    def test_parse_search_extracts_jobs(self, collector):
        with patch.object(collector, "_fetch_description", return_value="Full description here"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert len(jobs) == 2

    def test_parse_search_extracts_title(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert jobs[0].title == "VP Engineering"
        assert jobs[1].title == "Engineering Manager, Platform"

    def test_parse_search_extracts_company(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert jobs[0].company == "Acme Corp"
        assert jobs[1].company == "BigCo Inc"

    def test_parse_search_extracts_location(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert jobs[0].location == "United States"
        assert jobs[1].location == "Remote"

    def test_parse_search_strips_tracking_params(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert "?trk=" not in jobs[0].url
        assert "linkedin.com/jobs/view/" in jobs[0].url

    def test_parse_search_sets_source(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert all(j.source == "linkedin" for j in jobs)

    def test_parse_search_has_description_hash(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        for j in jobs:
            assert j.description_hash
            assert len(j.description_hash) == 64

    def test_deduplicates_within_run(self, collector):
        """Same job ID appearing twice should only be returned once."""
        double_html = MOCK_SEARCH_HTML + MOCK_SEARCH_HTML
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(double_html)
        assert len(jobs) == 2  # not 4

    def test_fetch_description_parses_detail_html(self, collector):
        with patch("shortlist.http.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = MOCK_DETAIL_HTML
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            desc = collector._fetch_description("1234567890")
            assert "40-person team" in desc
            assert "$300k-$350k" in desc

    @patch("shortlist.http.get")
    def test_fetch_new_calls_search_api(self, mock_get, collector):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector.fetch_new()
        assert mock_get.called
        assert "seeMoreJobPostings" in str(mock_get.call_args_list[0])


class TestCleanHtml:
    def test_strips_tags(self):
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_unescapes_entities(self):
        assert _clean_html("AT&amp;T") == "AT&T"

    def test_normalizes_whitespace(self):
        assert _clean_html("hello\n\n  world") == "hello world"
