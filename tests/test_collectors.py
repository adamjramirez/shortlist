"""Tests for collectors."""
import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from shortlist.collectors.base import BaseCollector, RawJob, normalize_description, description_hash
from shortlist.collectors.hn import HNCollector


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


class TestRawJob:
    def test_required_fields(self):
        job = RawJob(
            title="EM",
            company="Acme",
            url="https://acme.com/jobs/1",
            description="We need an EM",
            source="hn",
        )
        assert job.title == "EM"
        assert job.company == "Acme"
        assert job.source == "hn"

    def test_optional_fields_default_none(self):
        job = RawJob(
            title="EM", company="Acme", url="https://acme.com",
            description="desc", source="hn",
        )
        assert job.location is None
        assert job.salary_text is None
        assert job.posted_at is None

    def test_posted_at_field(self):
        job = RawJob(
            title="EM", company="Acme", url="https://acme.com",
            description="desc", source="hn", posted_at="2026-03-01T12:00:00+00:00",
        )
        assert job.posted_at == "2026-03-01T12:00:00+00:00"

    def test_description_hash_computed(self):
        job = RawJob(
            title="EM", company="Acme", url="https://acme.com",
            description="We need an EM", source="hn",
        )
        assert job.description_hash is not None
        assert len(job.description_hash) == 64  # SHA-256 hex


class TestNormalizeDescription:
    def test_lowercases(self):
        assert normalize_description("Hello World") == "hello world"

    def test_collapses_whitespace(self):
        assert normalize_description("hello   world\n\nfoo") == "hello world foo"

    def test_strips(self):
        assert normalize_description("  hello  ") == "hello"

    def test_identical_content_same_hash(self):
        h1 = description_hash("Hello   World\n\n")
        h2 = description_hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = description_hash("Engineering Manager at Acme")
        h2 = description_hash("VP Engineering at Acme")
        assert h1 != h2


class TestHNCollector:
    """Tests for HN Who's Hiring collector using mocked API responses."""

    @pytest.fixture
    def collector(self):
        return HNCollector()

    @pytest.fixture
    def mock_hn_response(self):
        """Simulates HN Algolia API response for a Who's Hiring thread."""
        return {
            "hits": [
                {
                    "objectID": "111",
                    "author": "user1",
                    "created_at": "2026-03-01T12:00:00Z",
                    "comment_text": (
                        "Acme Corp | Engineering Manager | Remote | $280k-$320k<p>"
                        "We're looking for an experienced EM to lead our platform team. "
                        "You'll manage 25 engineers across 4 squads.<p>"
                        "Apply: https://acme.com/jobs/em"
                    ),
                    "story_id": 99999,
                    "parent_id": 99999,
                },
                {
                    "objectID": "222",
                    "author": "user2",
                    "created_at": "2026-03-01T13:00:00Z",
                    "comment_text": (
                        "BigCo | Senior Software Engineer | NYC | $200k<p>"
                        "Individual contributor role, no management.<p>"
                        "Apply: https://bigco.com/jobs/swe"
                    ),
                    "story_id": 99999,
                    "parent_id": 99999,
                },
                {
                    "objectID": "333",
                    "author": "user3",
                    "created_at": "2026-03-01T14:00:00Z",
                    "comment_text": (
                        "StartupAI | Head of AI | Remote | Equity: 0.5%<p>"
                        "Lead our ML team of 8. Report to CTO.<p>"
                        "Email: jobs@startupai.com"
                    ),
                    "story_id": 99999,
                    "parent_id": 99999,
                },
            ],
            "nbHits": 3,
            "nbPages": 1,
        }

    def test_parse_hn_comment_extracts_company(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        companies = [j.company for j in jobs]
        assert "Acme Corp" in companies

    def test_parse_hn_comment_extracts_title(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        acme_job = next(j for j in jobs if j.company == "Acme Corp")
        assert "Engineering Manager" in acme_job.title

    def test_parse_hn_comment_extracts_location(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        acme_job = next(j for j in jobs if j.company == "Acme Corp")
        assert acme_job.location == "Remote"

    def test_parse_hn_comment_extracts_salary(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        acme_job = next(j for j in jobs if j.company == "Acme Corp")
        assert "$280k-$320k" in (acme_job.salary_text or "")

    def test_parse_hn_comment_preserves_description(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        acme_job = next(j for j in jobs if j.company == "Acme Corp")
        assert "25 engineers" in acme_job.description

    def test_parse_hn_comment_sets_source(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        assert all(j.source == "hn" for j in jobs)

    def test_parse_hn_comment_generates_url(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        acme_job = next(j for j in jobs if j.company == "Acme Corp")
        assert "news.ycombinator.com" in acme_job.url

    def test_parse_handles_multiple_jobs(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        assert len(jobs) >= 2  # at least some parseable comments

    def test_parse_skips_unparseable_comments(self, collector):
        """Comments that don't follow company | title | location format are skipped."""
        hits = [
            {
                "objectID": "444",
                "author": "user4",
                "created_at": "2026-03-01T15:00:00Z",
                "comment_text": "Is anyone else having trouble with the job market?",
                "story_id": 99999,
                "parent_id": 99999,
            },
        ]
        jobs = collector._parse_comments(hits)
        assert len(jobs) == 0

    @patch("shortlist.http.httpx.get")
    def test_fetch_calls_algolia_api(self, mock_get, collector):
        mock_response = MagicMock()
        mock_response.json.return_value = {"hits": [], "nbHits": 0, "nbPages": 1}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        jobs = collector.fetch_new()
        assert mock_get.called
        call_url = mock_get.call_args[0][0]
        assert "algolia" in call_url or "hn" in call_url

    def test_all_jobs_have_description_hash(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        for job in jobs:
            assert job.description_hash is not None
            assert len(job.description_hash) == 64

    def test_parse_hn_comment_extracts_posted_at(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        acme_job = next(j for j in jobs if j.company == "Acme Corp")
        assert acme_job.posted_at is not None
        assert "2026-03-01" in acme_job.posted_at

    def test_parse_hn_comment_posted_at_is_iso(self, collector, mock_hn_response):
        jobs = collector._parse_comments(mock_hn_response["hits"])
        for job in jobs:
            if job.posted_at:
                # Should be parseable as ISO 8601
                dt = datetime.fromisoformat(job.posted_at)
                assert dt.tzinfo is not None  # timezone-aware
