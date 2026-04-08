"""Tests for LLM scorer."""
import json
from unittest.mock import patch, MagicMock

import pytest

from shortlist.processors.scorer import (
    score_job,
    build_scoring_prompt,
    parse_score_response,
    ScoreResult,
)
from shortlist.collectors.base import RawJob
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter, Track


@pytest.fixture
def config():
    return Config(
        name="Adam",
        tracks={
            "em": Track(
                title="Engineering Manager",
                resume="resumes/em.md",
                target_orgs="large",
                min_reports=20,
                search_queries=["Engineering Manager"],
            ),
            "vp": Track(
                title="VP Engineering",
                resume="resumes/vp.md",
                target_orgs="series_b_plus",
                min_reports=20,
                search_queries=["VP Engineering"],
            ),
            "ai": Track(
                title="AI Engineering",
                resume="resumes/ai.md",
                target_orgs="any",
                min_reports=5,
                search_queries=["AI Engineering Manager"],
            ),
        },
        filters=Filters(
            location=LocationFilter(remote=True, local_zip="75098"),
            salary=SalaryFilter(min_base=250000),
            role_type=RoleTypeFilter(reject_explicit_ic=True),
        ),
    )


@pytest.fixture
def sample_job():
    return RawJob(
        title="VP Engineering",
        company="BigCo",
        url="https://bigco.com/jobs/vp",
        description=(
            "We're looking for a VP of Engineering to lead our 40-person engineering "
            "organization. You'll report to the CEO and own the technical roadmap. "
            "Requirements: 10+ years of engineering leadership, experience scaling "
            "teams from 30 to 100+. We're a Series C company, fully remote. "
            "Compensation: $300k-$350k base + equity."
        ),
        source="hn",
        location="Remote",
        salary_text="$300k-$350k",
    )


class TestBuildScoringPrompt:
    def test_includes_job_description(self, config, sample_job):
        prompt = build_scoring_prompt(sample_job, config)
        assert "40-person engineering" in prompt

    def test_includes_requirements(self, config, sample_job):
        prompt = build_scoring_prompt(sample_job, config)
        assert "250000" in prompt or "250,000" in prompt or "250k" in prompt

    def test_includes_tracks(self, config, sample_job):
        prompt = build_scoring_prompt(sample_job, config)
        assert "Engineering Manager" in prompt
        assert "VP Engineering" in prompt

    def test_includes_preferences(self, config, sample_job):
        prompt = build_scoring_prompt(sample_job, config)
        assert "remote" in prompt.lower() or "Remote" in prompt

    def test_scoring_prompt_includes_local_cities(self, sample_job):
        """UK user's cities appear in prompt so LLM can penalize US-only roles."""
        uk_config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(
                    remote=True,
                    local_zip="TQ13 8EH",
                    local_cities=["London"],
                ),
                salary=SalaryFilter(min_base=120000),
                role_type=RoleTypeFilter(),
            ),
        )
        prompt = build_scoring_prompt(sample_job, uk_config)
        assert "London" in prompt
        assert "TQ13 8EH" in prompt
        assert "score below 60" in prompt.lower()

    def test_scoring_prompt_zip_only(self, sample_job, config):
        """US user with zip but no cities still gets clean location line."""
        prompt = build_scoring_prompt(sample_job, config)
        assert "75098" in prompt
        assert "Remote or near" in prompt

    def test_scoring_prompt_country_in_location(self, sample_job):
        """Country appears in location requirement."""
        uk_config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(country="United Kingdom"),
                salary=SalaryFilter(min_base=80000, currency="GBP"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, uk_config)
        assert "Remote in United Kingdom" in prompt

    def test_scoring_prompt_country_with_cities(self, sample_job):
        """Country + cities both appear."""
        config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(
                    country="Germany",
                    local_cities=["Berlin", "Munich"],
                ),
                salary=SalaryFilter(min_base=90000, currency="EUR"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "Berlin" in prompt
        assert "Germany" in prompt

    def test_scoring_prompt_currency_gbp(self, sample_job):
        """GBP user sees GBP in salary requirement, not $."""
        config = Config(
            name="Test",
            filters=Filters(
                salary=SalaryFilter(min_base=80000, currency="GBP"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "80,000 GBP" in prompt
        assert "$" not in prompt.split("Salary (if listed)")[0]  # no $ in requirements section

    def test_scoring_prompt_currency_default_usd(self, sample_job, config):
        """Default config uses USD."""
        prompt = build_scoring_prompt(sample_job, config)
        assert "250,000 USD" in prompt

    def test_scoring_prompt_salary_estimate_format_uses_currency(self, sample_job):
        """Salary estimate instruction uses user's currency."""
        config = Config(
            name="Test",
            filters=Filters(
                salary=SalaryFilter(min_base=80000, currency="EUR"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "XXXk-XXXk EUR" in prompt

    def test_scoring_prompt_onsite_country_no_remote(self, sample_job):
        """Non-remote user with country gets 'In Germany', not 'Remote in Germany'."""
        config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(remote=False, country="Germany"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "- Location: In Germany" in prompt

    def test_scoring_prompt_onsite_cities_country(self, sample_job):
        """Non-remote + cities + country = 'Near Berlin in Germany'."""
        config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(
                    remote=False, country="Germany", local_cities=["Berlin"],
                ),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "Near Berlin in Germany" in prompt

    def test_scoring_prompt_region_expanded(self, sample_job):
        """Region names like 'DACH' are expanded to concrete country names."""
        config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(country="DACH"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "Germany" in prompt
        assert "Austria" in prompt
        assert "Switzerland" in prompt
        # The raw region name should NOT appear as-is in the location requirement
        assert "- Location: Remote in DACH" not in prompt

    def test_scoring_prompt_europe_region_expanded(self, sample_job):
        """Large region 'Europe' expands to country list."""
        config = Config(
            name="Test",
            filters=Filters(
                location=LocationFilter(country="Europe"),
            ),
        )
        prompt = build_scoring_prompt(sample_job, config)
        assert "United Kingdom" in prompt
        assert "Germany" in prompt
        assert "France" in prompt


class TestParseScoreResponse:
    def test_parses_valid_json(self):
        response = json.dumps({
            "fit_score": 91,
            "matched_track": "vp",
            "reasoning": "Strong VP fit — 40-person org, Series C, remote, $300k+.",
            "yellow_flags": [],
            "salary_estimate": "$300k-$350k",
            "salary_confidence": "high",
        })
        result = parse_score_response(response)
        assert result.fit_score == 91
        assert result.matched_track == "vp"
        assert "Series C" in result.reasoning

    def test_parses_json_in_markdown_block(self):
        response = '```json\n{"fit_score": 85, "matched_track": "em", "reasoning": "Good EM fit.", "yellow_flags": ["small team"], "salary_estimate": "$260k", "salary_confidence": "medium"}\n```'
        result = parse_score_response(response)
        assert result.fit_score == 85
        assert result.matched_track == "em"

    def test_clamps_score_to_range(self):
        response = json.dumps({
            "fit_score": 150,
            "matched_track": "em",
            "reasoning": "test",
            "yellow_flags": [],
            "salary_estimate": "",
            "salary_confidence": "low",
        })
        result = parse_score_response(response)
        assert result.fit_score == 100

    def test_handles_missing_fields(self):
        response = json.dumps({"fit_score": 70, "matched_track": "ai"})
        result = parse_score_response(response)
        assert result.fit_score == 70
        assert result.reasoning == ""

    def test_returns_none_for_garbage(self):
        result = parse_score_response("I can't score this job")
        assert result is None


def test_build_scoring_prompt_includes_prestige_criteria_from_config():
    """Main scoring prompt derives prestige criteria from config tracks."""
    from shortlist.processors.scorer import build_scoring_prompt
    config = Config(
        name="Test",
        fit_context="Engineering leader",
        tracks={"vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10)},
        filters=Filters(
            salary=SalaryFilter(min_base=200000, currency="USD"),
            location=LocationFilter(remote=True),
        ),
    )
    job = RawJob(title="VP Eng", company="Acme", url="https://example.com",
                 description="desc", source="linkedin", location="Remote")
    prompt = build_scoring_prompt(job, config)
    assert "Target role levels:" in prompt
    assert "VP of Engineering" in prompt


def test_score_prestige_returns_valid_tier(monkeypatch):
    """score_prestige returns A/B/C/D from LLM response."""
    from shortlist.processors.scorer import score_prestige
    import shortlist.llm as llm_mod
    monkeypatch.setattr(llm_mod, "call_llm", lambda *a, **kw: '{"prestige_tier": "B"}')
    config = Config(
        fit_context="Engineering leader",
        tracks={"vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10)},
    )
    job = RawJob(title="VP Eng", company="Acme", url="https://example.com",
                 description="desc", source="linkedin", location="Remote")
    assert score_prestige(job, config) == "B"


def test_score_prestige_returns_empty_on_llm_failure(monkeypatch):
    """score_prestige returns empty string when LLM call fails."""
    from shortlist.processors.scorer import score_prestige
    import shortlist.llm as llm_mod
    monkeypatch.setattr(llm_mod, "call_llm", lambda *a, **kw: None)
    config = Config(
        fit_context="Engineering leader",
        tracks={"vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10)},
    )
    job = RawJob(title="VP Eng", company="Acme", url="https://example.com",
                 description="desc", source="linkedin", location="Remote")
    assert score_prestige(job, config) == ""


def test_score_result_has_prestige_tier():
    r = ScoreResult(fit_score=80, matched_track="vp")
    assert hasattr(r, 'prestige_tier')
    assert r.prestige_tier == ""


def test_parse_score_response_extracts_prestige_tier():
    response = '''{
        "fit_score": 85, "matched_track": "vp", "reasoning": "Strong.",
        "yellow_flags": [], "salary_estimate": "200k-300k USD",
        "salary_confidence": "medium", "corrected_title": "VP Engineering",
        "corrected_company": "Acme", "corrected_location": "Remote",
        "prestige_tier": "A"
    }'''
    result = parse_score_response(response)
    assert result is not None
    assert result.prestige_tier == "A"


def test_parse_score_response_rejects_invalid_prestige_tier():
    response = '''{
        "fit_score": 75, "matched_track": "vp", "reasoning": "OK.",
        "yellow_flags": [], "salary_estimate": "150k USD",
        "salary_confidence": "low", "corrected_title": "Dir",
        "corrected_company": "Corp", "corrected_location": "Remote",
        "prestige_tier": "X"
    }'''
    result = parse_score_response(response)
    assert result is not None
    assert result.prestige_tier == ""


def test_parse_score_response_defaults_prestige_tier_when_missing():
    response = '''{
        "fit_score": 75, "matched_track": "vp", "reasoning": "OK.",
        "yellow_flags": [], "salary_estimate": "150k USD",
        "salary_confidence": "low", "corrected_title": "Dir",
        "corrected_company": "Corp", "corrected_location": "Remote"
    }'''
    result = parse_score_response(response)
    assert result is not None
    assert result.prestige_tier == ""


class TestScoreResult:
    def test_dataclass_fields(self):
        r = ScoreResult(
            fit_score=85,
            matched_track="em",
            reasoning="Good fit",
            yellow_flags=["travel required"],
            salary_estimate="$280k",
            salary_confidence="medium",
        )
        assert r.fit_score == 85
        assert r.yellow_flags == ["travel required"]
