"""Unified LLM client supporting Gemini, OpenAI, and Anthropic.

All LLM calls go through `call_llm(prompt)` which routes to the
configured provider. Provider is determined by config + environment:

  Provider   | Config model prefix  | Env var needed
  -----------|---------------------|----------------
  Gemini     | gemini-*            | GEMINI_API_KEY
  OpenAI     | gpt-* / o1-* / o3-*| OPENAI_API_KEY
  Anthropic  | claude-*            | ANTHROPIC_API_KEY
"""
import json
import logging
import os
import re
from typing import Protocol

from dotenv import load_dotenv

from shortlist import http

load_dotenv()

logger = logging.getLogger(__name__)

# Rate-limit domains
_RATE_LIMIT_DOMAINS = {
    "gemini": "generativelanguage.googleapis.com",
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
}

# Singleton — set once via configure(), used by call_llm()
_provider: "LLMProvider | None" = None
_model: str = ""


class LLMProvider(Protocol):
    def call(self, prompt: str, model: str) -> str | None: ...


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class GeminiProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def call(self, prompt: str, model: str) -> str | None:
        import httpx
        http._wait(_RATE_LIMIT_DOMAINS["gemini"])
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = httpx.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "") if parts else None


class OpenAIProvider:
    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=60.0)

    def call(self, prompt: str, model: str) -> str | None:
        http._wait(_RATE_LIMIT_DOMAINS["openai"])
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content


class AnthropicProvider:
    def __init__(self, api_key: str):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key, timeout=60.0)

    def call(self, prompt: str, model: str) -> str | None:
        http._wait(_RATE_LIMIT_DOMAINS["anthropic"])
        response = self.client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def detect_provider(model: str) -> str:
    """Detect provider from model name. Returns 'gemini', 'openai', or 'anthropic'."""
    model_lower = model.lower()
    if model_lower.startswith(("gemini-", "gemini/")):
        return "gemini"
    if model_lower.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "openai"
    if model_lower.startswith("claude-"):
        return "anthropic"
    # Default to gemini for backwards compatibility
    logger.warning(f"Unknown model prefix '{model}', defaulting to Gemini provider")
    return "gemini"


_ENV_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _make_provider(provider_name: str) -> LLMProvider:
    """Create a provider instance. Raises if API key is missing."""
    if provider_name not in _ENV_KEYS:
        raise ValueError(f"Unknown provider: {provider_name}")

    env_key = _ENV_KEYS[provider_name]
    api_key = os.environ.get(env_key, "")
    if not api_key:
        raise ValueError(
            f"{env_key} not set in .env. Required for model provider '{provider_name}'."
        )

    if provider_name == "gemini":
        return GeminiProvider(api_key)
    elif provider_name == "openai":
        return OpenAIProvider(api_key)
    else:
        return AnthropicProvider(api_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def configure(model: str) -> None:
    """Configure the LLM client. Call once at startup (e.g., from CLI)."""
    global _provider, _model
    provider_name = detect_provider(model)
    _provider = _make_provider(provider_name)
    _model = model
    logger.info(f"LLM configured: provider={provider_name}, model={model}")


def call_llm(prompt: str) -> str | None:
    """Call the configured LLM. Returns response text or None on failure.

    Raises RuntimeError if configure() hasn't been called.
    """
    if _provider is None or not _model:
        raise RuntimeError(
            "LLM not configured. Call llm.configure(model) before using call_llm()."
        )
    try:
        import time
        start = time.monotonic()
        logger.info(f"LLM call starting ({_model})…")
        result = _provider.call(prompt, _model)
        elapsed = time.monotonic() - start
        logger.info(f"LLM call completed in {elapsed:.1f}s")
        if elapsed > 30:
            logger.warning(f"LLM call took {elapsed:.1f}s (slow)")
        return result
    except Exception as e:
        import time
        elapsed = time.monotonic() - start
        logger.error(f"LLM API error after {elapsed:.1f}s ({type(e).__name__}): {e}")
        return None


def parse_json(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def reset() -> None:
    """Reset the singleton (for testing)."""
    global _provider, _model
    _provider = None
    _model = ""
