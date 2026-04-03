"""Tests for LinkedIn collector."""
import re
from unittest.mock import patch, MagicMock

import pytest

from shortlist.collectors.linkedin import (
    LinkedInCollector, _clean_html, searches_from_config, _work_type_filter,
    REGION_COUNTRIES,
)


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

    def test_parse_search_extracts_posted_at(self, collector):
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(MOCK_SEARCH_HTML)
        assert jobs[0].posted_at == "2026-03-09"
        assert jobs[1].posted_at == "2026-03-10"

    def test_parse_search_posted_at_none_when_missing(self, collector):
        html_no_time = '<li><div data-entity-urn="urn:li:jobPosting:555"><a class="base-card__full-link" href="https://linkedin.com/jobs/view/x-555">Title</a><h4 class="base-search-card__subtitle">Co</h4><span class="job-search-card__location">US</span></div></li>'
        with patch.object(collector, "_fetch_description", return_value="desc"):
            jobs = collector._parse_search_results(html_no_time)
        assert len(jobs) == 1
        assert jobs[0].posted_at is None

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


class TestWorkTypeFilter:
    """Test f_WT derivation from location preferences."""

    def _make_config(self, remote=True, local_cities=None):
        from shortlist.config import Config, Filters, LocationFilter
        return Config(
            filters=Filters(
                location=LocationFilter(
                    remote=remote,
                    local_cities=local_cities or [],
                ),
            ),
        )

    def test_remote_no_cities(self):
        assert _work_type_filter(self._make_config(remote=True, local_cities=[])) == "2"

    def test_remote_with_cities(self):
        assert _work_type_filter(self._make_config(remote=True, local_cities=["London"])) == "2,3"

    def test_onsite_with_cities(self):
        assert _work_type_filter(self._make_config(remote=False, local_cities=["London"])) == "1,3"

    def test_onsite_no_cities(self):
        assert _work_type_filter(self._make_config(remote=False, local_cities=[])) is None


class TestSearchesFromConfig:
    """Test search param generation from config."""

    def _make_config(self, queries=None, remote=True, local_cities=None):
        from shortlist.config import Config, Filters, LocationFilter, Track
        tracks = {"em": Track(title="EM", search_queries=queries or ["Engineering Manager"])}
        return Config(
            tracks=tracks,
            filters=Filters(
                location=LocationFilter(
                    remote=remote,
                    local_cities=local_cities or [],
                ),
            ),
        )

    def test_remote_only_sets_f_wt_2(self):
        searches = searches_from_config(self._make_config(remote=True))
        assert searches[0]["f_WT"] == "2"

    def test_remote_with_cities_sets_f_wt_2_3(self):
        searches = searches_from_config(self._make_config(remote=True, local_cities=["London"]))
        assert searches[0]["f_WT"] == "2,3"

    def test_onsite_no_cities_omits_f_wt(self):
        searches = searches_from_config(self._make_config(remote=False))
        assert "f_WT" not in searches[0]

    def test_fallback_respects_work_type(self):
        """Empty tracks → fallback search still uses correct f_WT."""
        from shortlist.config import Config, Filters, LocationFilter
        config = Config(
            tracks={},
            filters=Filters(location=LocationFilter(remote=False, local_cities=["Berlin"])),
        )
        searches = searches_from_config(config)
        assert searches[0]["f_WT"] == "1,3"


class TestLinkedInCollectorLocation:
    """Test that collector passes location to search API."""

    @patch("shortlist.http.get")
    def test_uses_custom_location(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = LinkedInCollector(
            searches=[{"keywords": "EM"}],
            location="United Kingdom",
        )
        collector.fetch_new()

        call_params = mock_get.call_args_list[0]
        assert call_params[1]["params"]["location"] == "United Kingdom"

    @patch("shortlist.http.get")
    def test_defaults_to_united_states(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = LinkedInCollector(searches=[{"keywords": "EM"}])
        collector.fetch_new()

        call_params = mock_get.call_args_list[0]
        assert call_params[1]["params"]["location"] == "United States"


class TestRegionExpansion:
    """Test multi-country expansion for region searches."""

    def test_single_country_not_expanded(self):
        collector = LinkedInCollector(location="Germany")
        assert collector._resolve_locations() == ["Germany"]

    def test_dach_expands_to_three_countries(self):
        collector = LinkedInCollector(location="DACH")
        locations = collector._resolve_locations()
        assert set(locations) == {"Germany", "Austria", "Switzerland"}

    def test_all_regions_have_entries(self):
        """Every region key maps to a non-empty country list."""
        for region, countries in REGION_COUNTRIES.items():
            assert len(countries) > 0, f"Region {region} has no countries"

    @patch("shortlist.http.get")
    def test_region_searches_each_country(self, mock_get):
        """DACH with 1 query = 3 countries x 1 query = 3 search calls (1 page each)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = LinkedInCollector(
            searches=[{"keywords": "EM"}],
            location="DACH",
        )
        collector.fetch_new()

        # 3 countries x 1 query x 1 page = 3 calls
        assert mock_get.call_count == 3
        locations_searched = [
            call[1]["params"]["location"]
            for call in mock_get.call_args_list
        ]
        assert set(locations_searched) == {"Germany", "Austria", "Switzerland"}

    @patch("shortlist.http.get")
    def test_region_uses_one_page_per_country(self, mock_get):
        """Multi-country search uses 1 page per country, not max_pages."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_SEARCH_HTML  # returns results so it would try page 2
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = LinkedInCollector(
            searches=[{"keywords": "EM"}],
            location="DACH",
            max_pages=3,  # would be 3 pages for single country
        )
        collector.fetch_new()

        # 3 countries x 1 page each = 3 calls (not 3 x 3 = 9)
        assert mock_get.call_count == 3

    @patch("shortlist.http.get")
    def test_single_country_uses_max_pages(self, mock_get):
        """Single country search uses full max_pages."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_SEARCH_HTML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = LinkedInCollector(
            searches=[{"keywords": "EM"}],
            location="Germany",
            max_pages=2,
        )
        collector.fetch_new()

        # 1 country x 1 query x 2 pages = 2 calls
        assert mock_get.call_count == 2

    @patch("shortlist.http.get")
    def test_region_deduplicates_across_countries(self, mock_get):
        """Jobs with same ID from different countries are deduplicated."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_SEARCH_HTML  # has IDs 1234567890 and 9876543210
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        collector = LinkedInCollector(
            searches=[{"keywords": "EM"}],
            location="DACH",
        )
        jobs = collector.fetch_new()

        # Same HTML for all 3 countries, but dedup by job ID
        # MOCK_SEARCH_HTML has 2 unique job IDs
        assert len(jobs) == 2


class TestCleanHtml:
    def test_strips_tags(self):
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_unescapes_entities(self):
        assert _clean_html("AT&amp;T") == "AT&T"

    def test_normalizes_whitespace(self):
        assert _clean_html("hello\n\n  world") == "hello world"
