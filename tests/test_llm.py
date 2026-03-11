"""Tests for the unified LLM client."""
import json
import os
from unittest.mock import patch, MagicMock

import pytest

from shortlist.llm import (
    detect_provider, configure, call_llm, parse_json, reset,
    GeminiProvider, OpenAIProvider, AnthropicProvider,
    _ENV_KEYS, _make_provider,
)


@pytest.fixture(autouse=True)
def clean_singleton():
    """Reset the LLM singleton between tests."""
    reset()
    yield
    reset()


class TestDetectProvider:
    def test_gemini_models(self):
        assert detect_provider("gemini-2.5-flash") == "gemini"
        assert detect_provider("gemini-1.5-pro") == "gemini"

    def test_openai_models(self):
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("gpt-4o-mini") == "openai"
        assert detect_provider("o1-preview") == "openai"
        assert detect_provider("o3-mini") == "openai"

    def test_anthropic_models(self):
        assert detect_provider("claude-sonnet-4-20250514") == "anthropic"
        assert detect_provider("claude-3-haiku-20240307") == "anthropic"

    def test_unknown_defaults_to_gemini(self):
        assert detect_provider("some-random-model") == "gemini"


class TestParseJson:
    def test_raw_json(self):
        assert parse_json('{"a": 1}') == {"a": 1}

    def test_markdown_block(self):
        assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_in_text(self):
        assert parse_json('Here: {"a": 1} done') == {"a": 1}

    def test_raises_on_no_json(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_json("no json here")


class TestMakeProvider:
    def test_raises_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
                _make_provider("gemini")

    def test_raises_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            _make_provider("llama")

    @patch("shortlist.llm.GeminiProvider")
    def test_creates_gemini(self, mock_cls):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            _make_provider("gemini")
            mock_cls.assert_called_once_with("test-key")

    @patch("shortlist.llm.OpenAIProvider")
    def test_creates_openai(self, mock_cls):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            _make_provider("openai")
            mock_cls.assert_called_once_with("sk-test")

    @patch("shortlist.llm.AnthropicProvider")
    def test_creates_anthropic(self, mock_cls):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            _make_provider("anthropic")
            mock_cls.assert_called_once_with("sk-ant-test")


class TestConfigureAndCall:
    def test_call_without_configure_raises(self):
        with pytest.raises(RuntimeError, match="LLM not configured"):
            call_llm("hello")

    @patch("shortlist.llm._make_provider")
    def test_configure_and_call(self, mock_make):
        mock_provider = MagicMock()
        mock_provider.call.return_value = "response text"
        mock_make.return_value = mock_provider

        configure("gemini-2.5-flash")
        result = call_llm("hello")

        assert result == "response text"
        mock_provider.call.assert_called_once_with("hello", "gemini-2.5-flash")

    @patch("shortlist.llm._make_provider")
    def test_call_returns_none_on_error(self, mock_make):
        mock_provider = MagicMock()
        mock_provider.call.side_effect = Exception("API error")
        mock_make.return_value = mock_provider

        configure("gemini-2.5-flash")
        result = call_llm("hello")

        assert result is None
