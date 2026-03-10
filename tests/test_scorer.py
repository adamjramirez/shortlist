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
