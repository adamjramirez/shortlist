"""Tests for career page ATS parsers."""
from unittest.mock import patch, MagicMock

import pytest

from shortlist.collectors.career_page import (
    detect_ats,
    extract_org_slug,
    fetch_greenhouse_jobs,
    fetch_lever_jobs,
    fetch_ashby_jobs,
    fetch_career_page,
    _clean_html,
)


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


class TestDetectATS:
    def test_greenhouse_boards(self):
        assert detect_ats("https://boards.greenhouse.io/nabis") == "greenhouse"

    def test_greenhouse_job_boards(self):
        assert detect_ats("https://job-boards.greenhouse.io/nabis/jobs/123") == "greenhouse"

    def test_lever(self):
        assert detect_ats("https://jobs.lever.co/soraschools") == "lever"

    def test_ashby(self):
        assert detect_ats("https://jobs.ashbyhq.com/suno") == "ashby"

    def test_unknown(self):
        assert detect_ats("https://www.acme.com/careers") is None

    def test_linkedin(self):
        assert detect_ats("https://www.linkedin.com/company/foo/jobs/") is None


class TestExtractOrgSlug:
    def test_greenhouse_simple(self):
        assert extract_org_slug("https://boards.greenhouse.io/nabis", "greenhouse") == "nabis"

    def test_greenhouse_with_job(self):
        assert extract_org_slug("https://job-boards.greenhouse.io/nabis/jobs/123", "greenhouse") == "nabis"

    def test_lever_simple(self):
        assert extract_org_slug("https://jobs.lever.co/soraschools", "lever") == "soraschools"

    def test_lever_with_posting(self):
        assert extract_org_slug("https://jobs.lever.co/soraschools/abc-123", "lever") == "soraschools"

    def test_ashby_simple(self):
        assert extract_org_slug("https://jobs.ashbyhq.com/suno", "ashby") == "suno"

    def test_ashby_with_job(self):
        assert extract_org_slug("https://jobs.ashbyhq.com/suno/abc-123", "ashby") == "suno"

    def test_empty_path(self):
        assert extract_org_slug("https://boards.greenhouse.io/", "greenhouse") is None


MOCK_GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "title": "VP Engineering",
            "location": {"name": "Remote"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "content": "<p>Lead our 50-person engineering team. $300k-$350k.</p>",
        },
        {
            "title": "Software Engineer",
            "location": {"name": "San Francisco"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/456",
            "content": "<p>Build great software.</p>",
        },
    ]
}

MOCK_LEVER_RESPONSE = [
    {
        "text": "Head of Engineering",
        "categories": {"location": "Remote, US"},
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "descriptionPlain": "Lead our engineering organization.",
        "lists": [
            {"text": "Requirements", "content": ["10+ years", "Management experience"]},
        ],
    },
]

MOCK_ASHBY_LIST_RESPONSE = {
    "data": {
        "jobBoard": {
            "jobPostings": [
                {
                    "id": "job-uuid-1",
                    "title": "Engineering Manager",
                    "locationName": "Remote",
                    "compensationTierSummary": "$250k-$300k",
                    "employmentType": "FullTime",
                },
            ]
        }
    }
}

MOCK_ASHBY_DETAIL_RESPONSE = {
    "data": {
        "jobPosting": {
            "descriptionHtml": "<p>Manage a team of 20 engineers building AI products.</p>",
        }
    }
}


class TestFetchGreenhouseJobs:
    @patch("shortlist.http.get")
    def test_returns_raw_jobs(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_GREENHOUSE_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = fetch_greenhouse_jobs("acme")
        assert len(jobs) == 2

    @patch("shortlist.http.get")
    def test_extracts_fields(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_GREENHOUSE_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = fetch_greenhouse_jobs("acme")
        assert jobs[0].title == "VP Engineering"
        assert jobs[0].location == "Remote"
        assert jobs[0].source == "greenhouse"
        assert "$300k-$350k" in jobs[0].description

    @patch("shortlist.http.get")
    def test_has_description_hash(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_GREENHOUSE_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = fetch_greenhouse_jobs("acme")
        assert all(len(j.description_hash) == 64 for j in jobs)

    @patch("shortlist.http.get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        assert fetch_greenhouse_jobs("acme") == []


class TestFetchLeverJobs:
    @patch("shortlist.http.get")
    def test_returns_raw_jobs(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_LEVER_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = fetch_lever_jobs("acme")
        assert len(jobs) == 1

    @patch("shortlist.http.get")
    def test_includes_lists_in_description(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_LEVER_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = fetch_lever_jobs("acme")
        assert "10+ years" in jobs[0].description
        assert "Management experience" in jobs[0].description

    @patch("shortlist.http.get")
    def test_extracts_fields(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_LEVER_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        jobs = fetch_lever_jobs("acme")
        assert jobs[0].title == "Head of Engineering"
        assert jobs[0].location == "Remote, US"
        assert jobs[0].source == "lever"


class TestFetchAshbyJobs:
    @patch("shortlist.http.post")
    def test_returns_raw_jobs(self, mock_post):
        list_resp = MagicMock()
        list_resp.json.return_value = MOCK_ASHBY_LIST_RESPONSE
        list_resp.raise_for_status = MagicMock()

        detail_resp = MagicMock()
        detail_resp.json.return_value = MOCK_ASHBY_DETAIL_RESPONSE
        detail_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [list_resp, detail_resp]

        jobs = fetch_ashby_jobs("acme")
        assert len(jobs) == 1

    @patch("shortlist.http.post")
    def test_extracts_fields(self, mock_post):
        list_resp = MagicMock()
        list_resp.json.return_value = MOCK_ASHBY_LIST_RESPONSE
        list_resp.raise_for_status = MagicMock()

        detail_resp = MagicMock()
        detail_resp.json.return_value = MOCK_ASHBY_DETAIL_RESPONSE
        detail_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [list_resp, detail_resp]

        jobs = fetch_ashby_jobs("acme")
        assert jobs[0].title == "Engineering Manager"
        assert jobs[0].location == "Remote"
        assert jobs[0].source == "ashby"
        assert "20 engineers" in jobs[0].description
        assert "$250k-$300k" in jobs[0].description

    @patch("shortlist.http.post")
    def test_constructs_url(self, mock_post):
        list_resp = MagicMock()
        list_resp.json.return_value = MOCK_ASHBY_LIST_RESPONSE
        list_resp.raise_for_status = MagicMock()

        detail_resp = MagicMock()
        detail_resp.json.return_value = MOCK_ASHBY_DETAIL_RESPONSE
        detail_resp.raise_for_status = MagicMock()

        mock_post.side_effect = [list_resp, detail_resp]

        jobs = fetch_ashby_jobs("acme")
        assert jobs[0].url == "https://jobs.ashbyhq.com/acme/job-uuid-1"


class TestFetchCareerPage:
    def test_routes_greenhouse(self):
        mock_gh = MagicMock(return_value=[MagicMock()])
        with patch.dict("shortlist.collectors.career_page.FETCHERS", {"greenhouse": mock_gh}):
            result = fetch_career_page("https://job-boards.greenhouse.io/acme")
        mock_gh.assert_called_once_with("acme")
        assert len(result) == 1

    def test_routes_lever(self):
        mock_lever = MagicMock(return_value=[MagicMock()])
        with patch.dict("shortlist.collectors.career_page.FETCHERS", {"lever": mock_lever}):
            fetch_career_page("https://jobs.lever.co/acme")
        mock_lever.assert_called_once_with("acme")

    def test_routes_ashby(self):
        mock_ashby = MagicMock(return_value=[MagicMock()])
        with patch.dict("shortlist.collectors.career_page.FETCHERS", {"ashby": mock_ashby}):
            fetch_career_page("https://jobs.ashbyhq.com/acme")
        mock_ashby.assert_called_once_with("acme")

    def test_unknown_ats_returns_empty(self):
        assert fetch_career_page("https://www.acme.com/careers") == []
