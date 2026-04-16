"""Tests for title gate: LLM batch pre-filter that runs before full scorer."""
import json
from unittest.mock import MagicMock, patch
import importlib

import pytest

from shortlist.collectors.base import RawJob
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter, Track, LLMConfig
import shortlist.processors.title_gate as title_gate_mod
from shortlist.processors.title_gate import (
    build_target_role_levels,
    build_title_gate_prompt,
    parse_title_gate_response,
    gate_titles,
    TITLE_GATE_SCHEMA,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
        },
        filters=Filters(
            location=LocationFilter(remote=True, local_zip="75098"),
            salary=SalaryFilter(min_base=250000),
            role_type=RoleTypeFilter(reject_explicit_ic=True),
        ),
        llm=LLMConfig(title_gate_enabled=True, title_gate_batch_size=50),
    )


@pytest.fixture
def sample_jobs():
    return [
        (101, RawJob(title="VP Engineering", company="BigCo", url="https://bigco.com/1",
                     description="VP role", source="hn", location="Remote")),
        (102, RawJob(title="Software Engineer", company="SmallCo", url="https://smallco.com/2",
                     description="IC role", source="hn", location=None)),
        (103, RawJob(title="Engineering Manager", company="MidCo", url="https://midco.com/3",
                     description="EM role", source="hn", location="Austin, TX")),
    ]


# ---------------------------------------------------------------------------
# Task 1: LLMConfig defaults
# ---------------------------------------------------------------------------

class TestLLMConfigDefaults:
    def test_llmconfig_defaults_title_gate_enabled_true(self):
        cfg = LLMConfig()
        assert cfg.title_gate_enabled is True

    def test_llmconfig_defaults_title_gate_batch_size_50(self):
        cfg = LLMConfig()
        assert cfg.title_gate_batch_size == 50


# ---------------------------------------------------------------------------
# Task 2: build_title_gate_prompt
# ---------------------------------------------------------------------------

class TestBuildTargetRoleLevels:
    def test_joins_track_titles(self, config):
        result = build_target_role_levels(config)
        assert "Engineering Manager" in result
        assert "VP Engineering" in result

    def test_fallback_when_no_tracks(self):
        empty_config = Config(tracks={})
        result = build_target_role_levels(empty_config)
        assert result == "senior engineering leadership"

    def test_skips_tracks_with_empty_title(self):
        cfg = Config(tracks={"no_title": Track(title="", resume="x.md")})
        result = build_target_role_levels(cfg)
        assert result == "senior engineering leadership"


class TestBuildTitleGatePrompt:
    def test_build_prompt_includes_target_role_levels_label(self, config, sample_jobs):
        prompt = build_title_gate_prompt(config, sample_jobs)
        assert "Target role levels:" in prompt
        # Also check the track title appears (proving the label is populated)
        assert "VP Engineering" in prompt

    def test_build_prompt_contains_each_item_title_and_company(self, config, sample_jobs):
        prompt = build_title_gate_prompt(config, sample_jobs)
        assert "VP Engineering" in prompt
        assert "BigCo" in prompt
        assert "Software Engineer" in prompt
        assert "SmallCo" in prompt
        assert "Engineering Manager" in prompt
        assert "MidCo" in prompt

    def test_build_prompt_numbers_items_for_response_mapping(self, config, sample_jobs):
        prompt = build_title_gate_prompt(config, sample_jobs)
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt

    def test_build_prompt_omits_fit_context(self, config, sample_jobs):
        config_with_context = Config(
            name="Adam",
            fit_context="I am a seasoned engineering leader with deep expertise in distributed systems and team growth.",
            tracks=config.tracks,
            filters=config.filters,
        )
        prompt = build_title_gate_prompt(config_with_context, sample_jobs)
        assert config_with_context.fit_context not in prompt

    def test_build_prompt_uses_unknown_for_missing_location(self, config):
        jobs = [
            (201, RawJob(title="Director of Eng", company="X", url="https://x.com/1",
                         description="dir role", source="hn", location=None)),
        ]
        prompt = build_title_gate_prompt(config, jobs)
        assert "unknown" in prompt.lower()


# ---------------------------------------------------------------------------
# Task 3: parse_title_gate_response
# ---------------------------------------------------------------------------

class TestParseTitleGateResponse:
    def test_parse_response_maps_decisions_to_row_ids(self, sample_jobs):
        # LLM returns decisions for indices 1, 2, 3 → should map to row_ids 101, 102, 103
        raw = json.dumps({
            "decisions": [
                {"id": 1, "pass": True, "reason": "VP matches"},
                {"id": 2, "pass": False, "reason": "IC role"},
                {"id": 3, "pass": True, "reason": "EM matches"},
            ]
        })
        result = parse_title_gate_response(raw, sample_jobs)
        assert result[101] == (True, "VP matches")
        assert result[102] == (False, "IC role")
        assert result[103] == (True, "EM matches")

    def test_parse_response_missing_id_defaults_to_pass(self, sample_jobs):
        # LLM omits id 2 — row_id 102 should default to (True, "")
        raw = json.dumps({
            "decisions": [
                {"id": 1, "pass": True, "reason": "VP matches"},
                {"id": 3, "pass": True, "reason": "EM matches"},
            ]
        })
        result = parse_title_gate_response(raw, sample_jobs)
        assert result[102] == (True, "")

    def test_parse_response_invalid_json_returns_all_pass(self, sample_jobs):
        result = parse_title_gate_response("not json", sample_jobs)
        assert result[101] == (True, "")
        assert result[102] == (True, "")
        assert result[103] == (True, "")

    def test_parse_response_none_input_returns_all_pass(self, sample_jobs):
        result = parse_title_gate_response(None, sample_jobs)
        assert result[101] == (True, "")
        assert result[102] == (True, "")
        assert result[103] == (True, "")

    def test_parse_response_string_id_coerced(self, sample_jobs):
        # LLM returns "id": "1" as a string — should still map to row_id 101
        raw = json.dumps({
            "decisions": [
                {"id": "1", "pass": False, "reason": "string id"},
            ]
        })
        result = parse_title_gate_response(raw, sample_jobs)
        assert result[101] == (False, "string id")
        # Others default to pass
        assert result[102] == (True, "")
        assert result[103] == (True, "")

    def test_parse_response_truncates_long_reason(self, sample_jobs):
        long_reason = "x" * 300
        raw = json.dumps({
            "decisions": [{"id": 1, "pass": True, "reason": long_reason}]
        })
        result = parse_title_gate_response(raw, sample_jobs)
        _, reason = result[101]
        assert len(reason) <= 200


# ---------------------------------------------------------------------------
# Task 4: gate_titles
# ---------------------------------------------------------------------------

def _make_all_pass_json(batch):
    decisions = [{"id": i + 1, "pass": True, "reason": "ok"} for i in range(len(batch))]
    return json.dumps({"decisions": decisions})


def _make_mixed_json(batch):
    decisions = []
    for i, (row_id, _) in enumerate(batch):
        decisions.append({"id": i + 1, "pass": i % 2 == 0, "reason": "mixed"})
    return json.dumps({"decisions": decisions})


class TestGateTitles:
    def test_gate_titles_empty_batch_no_llm_call(self, config):
        mock_llm = MagicMock()
        with patch.object(title_gate_mod, "llm", mock_llm):
            result, batch_count = gate_titles([], config)
        assert result == {}
        assert batch_count == 0
        mock_llm.call_llm.assert_not_called()

    def test_gate_titles_batches_in_chunks_of_50(self, config):
        # 120 jobs → 3 batches (50, 50, 20)
        jobs = [
            (i, RawJob(title=f"VP Eng {i}", company=f"Co{i}", url=f"https://co{i}.com",
                       description="desc", source="hn"))
            for i in range(120)
        ]
        mock_llm = MagicMock()
        # Return all-pass JSON for each batch call
        def side_effect(prompt, json_schema=None):
            # Determine batch size from the prompt by counting numbered items
            count = prompt.count("\n1.") + sum(
                1 for n in range(2, 121) if f"\n{n}." in prompt
            )
            # Simpler: just return all pass for up to 50
            return _make_all_pass_json(jobs[:50])  # shape doesn't matter as long as valid

        # Actually we need the real chunk sizes, so let's use a simpler approach
        call_results = []
        def capture_call(prompt, json_schema=None):
            # count how many items are in this chunk by looking at the last number
            import re
            nums = re.findall(r"^(\d+)\.", prompt, re.MULTILINE)
            n = int(nums[-1]) if nums else 0
            result = [{"id": i+1, "pass": True, "reason": "ok"} for i in range(n)]
            call_results.append(n)
            return json.dumps({"decisions": result})

        mock_llm.call_llm.side_effect = capture_call

        with patch.object(title_gate_mod, "llm", mock_llm):
            result, batch_count = gate_titles(jobs, config)

        assert mock_llm.call_llm.call_count == 3
        assert batch_count == 3
        assert len(result) == 120

    def test_gate_titles_fail_open_on_none_result(self, config):
        jobs = [
            (10, RawJob(title="VP Eng", company="Co", url="https://co.com",
                        description="desc", source="hn")),
            (11, RawJob(title="EM", company="Co2", url="https://co2.com",
                        description="desc", source="hn")),
        ]
        mock_llm = MagicMock()
        mock_llm.call_llm.return_value = None

        with patch.object(title_gate_mod, "llm", mock_llm):
            result, batch_count = gate_titles(jobs, config)

        assert result[10] == (True, "")
        assert result[11] == (True, "")
        assert batch_count == 1

    def test_gate_titles_mixed_pass_fail_mapping(self, config):
        jobs = [
            (201, RawJob(title="VP Eng", company="A", url="https://a.com",
                         description="vp role", source="hn")),
            (202, RawJob(title="Software Engineer", company="B", url="https://b.com",
                         description="ic role", source="hn")),
            (203, RawJob(title="Engineering Manager", company="C", url="https://c.com",
                         description="em role", source="hn")),
        ]
        mock_llm = MagicMock()
        mock_llm.call_llm.return_value = json.dumps({
            "decisions": [
                {"id": 1, "pass": True, "reason": "vp matches"},
                {"id": 2, "pass": False, "reason": "ic rejected"},
                {"id": 3, "pass": True, "reason": "em matches"},
            ]
        })

        with patch.object(title_gate_mod, "llm", mock_llm):
            result, batch_count = gate_titles(jobs, config)

        assert result[201] == (True, "vp matches")
        assert result[202] == (False, "ic rejected")
        assert result[203] == (True, "em matches")
        assert batch_count == 1
