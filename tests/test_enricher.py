"""Tests for company enrichment and re-scoring."""
import json
import sqlite3
from unittest.mock import patch

import pytest

from shortlist.processors.enricher import (
    CompanyIntel, _normalize_company, is_job_board,
    enrich_company, cache_enrichment, get_cached_enrichment,
    rescore_with_enrichment,
)
from shortlist.config import Config
from shortlist.db import init_db


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def config():
    return Config(
        name="Adam",
        fit_context="Best fit: VP/Director at Series B-D building AI-native products.",
    )


class TestNormalizeCompany:
    def test_lowercase(self):
        assert _normalize_company("Acme Corp") == "acme"

    def test_strips_inc(self):
        assert _normalize_company("Acme, Inc.") == "acme"

    def test_strips_gmbh(self):
        assert _normalize_company("Blindside HB GmbH") == "blindside hb"

    def test_strips_llc(self):
        assert _normalize_company("FooCo LLC") == "fooco"

    def test_strips_pbc(self):
        assert _normalize_company("Posit PBC") == "posit"


class TestCompanyIntel:
    def test_to_json_roundtrip(self):
        intel = CompanyIntel(
            name="Acme", stage="B", headcount_estimate=200,
            glassdoor_rating=4.2, growth_signal="growing",
        )
        data = intel.to_json()
        restored = CompanyIntel.from_json("Acme", data)
        assert restored.stage == "B"
        assert restored.headcount_estimate == 200
        assert restored.glassdoor_rating == 4.2

    def test_has_material_info_true(self):
        intel = CompanyIntel(
            name="X", stage="B", glassdoor_rating=4.0,
            growth_signal="growing",
        )
        assert intel.has_material_info()

    def test_has_material_info_false(self):
        intel = CompanyIntel(name="X")
        assert not intel.has_material_info()

    def test_summary(self):
        intel = CompanyIntel(
            name="Acme", stage="Series C", headcount_estimate=400,
            glassdoor_rating=4.5, growth_signal="growing",
        )
        s = intel.summary()
        assert "Series C" in s
        assert "400" in s
        assert "4.5" in s


class TestJobBoardDetection:
    def test_jobgether(self):
        assert is_job_board("Jobgether")

    def test_hays(self):
        assert is_job_board("Hays")

    def test_seneca_creek(self):
        assert is_job_board("Seneca Creek ES")

    def test_real_company(self):
        assert not is_job_board("Posit PBC")

    def test_enrich_skips_job_board(self):
        result = enrich_company("Jobgether", "VP Engineering desc")
        assert result is None


class TestEnrichCompany:
    @patch("shortlist.llm.call_llm")
    def test_returns_intel(self, mock_gemini):
        mock_gemini.return_value = json.dumps({
            "stage": "Series C",
            "last_funding": "$85M Oct 2025",
            "headcount_estimate": 400,
            "growth_signal": "growing",
            "glassdoor_rating": 4.5,
            "eng_blog_url": "https://blog.acme.com",
            "tech_stack": ["Python", "Go"],
            "oss_presence": "strong",
            "domain_description": "Data science tools",
            "hq_location": "Boston, MA",
        })

        intel = enrich_company("Acme Corp", "VP Eng job at Acme")
        assert intel is not None
        assert intel.stage == "Series C"
        assert intel.headcount_estimate == 400

    @patch("shortlist.llm.call_llm")
    def test_returns_none_on_failure(self, mock_gemini):
        mock_gemini.return_value = None
        assert enrich_company("Unknown", "desc") is None


class TestCacheEnrichment:
    def test_cache_and_retrieve(self, db):
        db.row_factory = sqlite3.Row
        intel = CompanyIntel(
            name="Acme Corp", stage="B", headcount_estimate=200,
            glassdoor_rating=4.0, growth_signal="growing",
        )
        cache_enrichment(db, "Acme Corp", intel)

        cached = get_cached_enrichment(db, "Acme Corp")
        assert cached is not None
        assert cached.stage == "B"
        assert cached.headcount_estimate == 200

    def test_cache_normalizes_name(self, db):
        db.row_factory = sqlite3.Row
        intel = CompanyIntel(name="Acme, Inc.", stage="C")
        cache_enrichment(db, "Acme, Inc.", intel)

        # Should find it with different casing/suffix
        cached = get_cached_enrichment(db, "ACME Corp")
        assert cached is not None
        assert cached.stage == "C"

    def test_no_cache_returns_none(self, db):
        db.row_factory = sqlite3.Row
        assert get_cached_enrichment(db, "NonExistent") is None


class TestRescoreWithEnrichment:
    @patch("shortlist.llm.call_llm")
    def test_returns_new_score(self, mock_gemini, config):
        mock_gemini.return_value = json.dumps({
            "new_score": 88,
            "score_delta": 3,
            "reasoning": "Strong eng culture signals",
        })

        intel = CompanyIntel(
            name="Acme", stage="C", glassdoor_rating=4.5,
            growth_signal="growing", headcount_estimate=400,
        )
        result = rescore_with_enrichment(85, "Good fit", "[]", intel, config)
        assert result is not None
        new_score, delta, reason = result
        assert new_score == 88
        assert delta == 3

    @patch("shortlist.llm.call_llm")
    def test_returns_none_when_no_change(self, mock_gemini, config):
        mock_gemini.return_value = json.dumps({
            "new_score": 85,
            "score_delta": 0,
            "reasoning": "No material new info",
        })

        intel = CompanyIntel(
            name="Acme", stage="B", glassdoor_rating=4.0,
            growth_signal="growing", headcount_estimate=200,
        )
        result = rescore_with_enrichment(85, "Good fit", "[]", intel, config)
        assert result is None  # delta == 0

    def test_skips_when_no_material_info(self, config):
        intel = CompanyIntel(name="Unknown")
        result = rescore_with_enrichment(85, "reason", "[]", intel, config)
        assert result is None
