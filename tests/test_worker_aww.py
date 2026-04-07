"""Tests for AWW slice integration in worker.py.

Verifies the supplement-not-replace behaviour and the use_aww_slice toggle.
"""
import pytest


def _build_config(fit_context="base context", aww_node_id="", use_aww_slice=True):
    return {
        "fit_context": fit_context,
        "aww_node_id": aww_node_id,
        "use_aww_slice": use_aww_slice,
        "tracks": {},
        "filters": {},
    }


def _resolve_fit_context(config: dict, aww_content: str | None) -> str:
    """Extract the fit_context resolution logic from worker.py for unit testing."""
    from shortlist.api.worker import resolve_fit_context
    return resolve_fit_context(config, aww_content)


class TestResolveFitContext:
    def test_no_aww_returns_base(self):
        config = _build_config(fit_context="base context", aww_node_id="")
        result = _resolve_fit_context(config, aww_content=None)
        assert result == "base context"

    def test_aww_supplements_not_replaces(self):
        config = _build_config(fit_context="base context", aww_node_id="abc123")
        result = _resolve_fit_context(config, aww_content="aww context")
        assert "base context" in result
        assert "aww context" in result

    def test_aww_supplement_ordering(self):
        """Base context appears before AWW context."""
        config = _build_config(fit_context="base context", aww_node_id="abc123")
        result = _resolve_fit_context(config, aww_content="aww context")
        assert result.index("base context") < result.index("aww context")

    def test_aww_disabled_ignores_aww_content(self):
        config = _build_config(fit_context="base context", aww_node_id="abc123", use_aww_slice=False)
        result = _resolve_fit_context(config, aww_content="aww context")
        assert result == "base context"
        assert "aww context" not in result

    def test_aww_enabled_but_no_content_returns_base(self):
        config = _build_config(fit_context="base context", aww_node_id="abc123", use_aww_slice=True)
        result = _resolve_fit_context(config, aww_content=None)
        assert result == "base context"

    def test_aww_enabled_no_node_id_returns_base(self):
        config = _build_config(fit_context="base context", aww_node_id="", use_aww_slice=True)
        result = _resolve_fit_context(config, aww_content=None)
        assert result == "base context"

    def test_use_aww_slice_defaults_true(self):
        """If use_aww_slice is absent from config, AWW is used by default."""
        config = {"fit_context": "base", "aww_node_id": "abc123"}
        result = _resolve_fit_context(config, aww_content="aww context")
        assert "base" in result
        assert "aww context" in result

    def test_empty_base_context_aww_still_supplements(self):
        config = _build_config(fit_context="", aww_node_id="abc123", use_aww_slice=True)
        result = _resolve_fit_context(config, aww_content="aww context")
        assert "aww context" in result
