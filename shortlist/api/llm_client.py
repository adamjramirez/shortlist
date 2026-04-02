"""LLM client for profile generation.

Production: calls provider APIs via httpx.
Tests: returns canned response via dependency override.
"""
import asyncio
import json
import logging
import re
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_BACKOFF_BASE = 2.0  # seconds: 2s, 4s


class ProfileGenerator(Protocol):
    async def generate_profile(self, resume_text: str) -> dict: ...


SYSTEM_PROMPT = """You are analyzing a resume to set up an automated job search profile.

Given the resume below, generate a job search profile with:

1. **fit_context**: A detailed 3-4 paragraph description of what this person should be looking for. Write in first person as if the candidate wrote it. MUST include:
   - Years of experience and seniority level
   - Core technical and leadership skills (be specific, not generic)
   - Industries, company stages, and company sizes that fit
   - What kind of problems they want to solve (based on their career pattern)
   - Likely dealbreakers (e.g. "not interested in early-stage startups" or "no pure IC roles")
   - What makes them distinctive vs other candidates at their level
   Be thorough — this text is used to score every job they see.

2. **tracks**: 1-3 role types they should search for. Each track needs:
   - title: Human-readable role title (e.g. "Senior Backend Engineer")
   - search_queries: 3-5 realistic job board search strings

3. **filters**: Reasonable defaults based on the resume:
   - location.remote: true/false (default true)
   - location.local_cities: list of cities if location is apparent from the resume
   - salary.min_base: estimated minimum base salary in USD based on their experience level
   - salary.currency: "USD" (or appropriate currency if non-US)
   - role_type.reject_explicit_ic: true if they seem management-track, false otherwise

Respond with ONLY valid JSON matching this exact schema:
{
  "fit_context": "string",
  "tracks": {
    "track_key": {
      "title": "string",
      "search_queries": ["string"]
    }
  },
  "filters": {
    "location": {
      "remote": true,
      "local_zip": "",
      "max_commute_minutes": 30,
      "local_cities": []
    },
    "salary": {
      "min_base": 0,
      "currency": "USD"
    },
    "role_type": {
      "reject_explicit_ic": false
    }
  }
}"""

USER_PROMPT_TEMPLATE = """Here is the resume:

{resume_text}"""


# Provider API configs
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

PROVIDERS = {
    "gemini-2.0-flash": {"url": _GEMINI_URL.format(model="gemini-2.0-flash"), "auth": "query"},
    "gemini-2.5-flash": {"url": _GEMINI_URL.format(model="gemini-2.5-flash"), "auth": "query"},
    "gemini-2.5-pro": {"url": _GEMINI_URL.format(model="gemini-2.5-pro"), "auth": "query"},
    "gpt-4o": {"url": _OPENAI_URL, "auth": "bearer"},
    "gpt-4o-mini": {"url": _OPENAI_URL, "auth": "bearer"},
    "claude-sonnet-4-20250514": {"url": _ANTHROPIC_URL, "auth": "x-api-key"},
    "claude-3-5-haiku-latest": {"url": _ANTHROPIC_URL, "auth": "x-api-key"},
}


def _fix_json_escapes(s: str) -> str:
    """Fix invalid backslash escapes that LLMs produce (e.g. \\$ from LaTeX)."""
    # Replace invalid \X escapes with \\X (valid JSON escape)
    # Valid JSON escapes: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
    return re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Find the JSON blob
    json_str = None
    if text.startswith("{"):
        json_str = text
    else:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                json_str = text[start : end + 1]

    if not json_str:
        raise ValueError("No JSON found in LLM response")

    # Try direct parse, then fix escapes and retry
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return json.loads(_fix_json_escapes(json_str))


async def _call_gemini(api_key: str, model: str, resume_text: str) -> str:
    url = PROVIDERS[model]["url"]
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            params={"key": api_key},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [
                    {
                        "parts": [
                            {"text": USER_PROMPT_TEMPLATE.format(resume_text=resume_text)}
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
            },
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _call_openai(api_key: str, model: str, resume_text: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            PROVIDERS[model]["url"],
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT_TEMPLATE.format(resume_text=resume_text)},
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_anthropic(api_key: str, model: str, resume_text: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            PROVIDERS[model]["url"],
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": USER_PROMPT_TEMPLATE.format(resume_text=resume_text)},
                ],
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


_CALLERS = {
    "gemini-2.0-flash": _call_gemini,
    "gemini-2.5-flash": _call_gemini,
    "gemini-2.5-pro": _call_gemini,
    "gpt-4o": _call_openai,
    "gpt-4o-mini": _call_openai,
    "claude-sonnet-4-20250514": _call_anthropic,
    "claude-3-5-haiku-latest": _call_anthropic,
}


async def _retry_on_transient(coro_factory, description: str = "LLM call"):
    """Retry an async callable on 429/5xx with exponential backoff."""
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await coro_factory()
        except httpx.HTTPStatusError as e:
            last_exc = e
            status = e.response.status_code
            if status == 429 or status >= 500:
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "%s got %d, retrying in %.0fs (attempt %d/%d)",
                        description, status, wait, attempt + 1, _MAX_RETRIES + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
            raise  # non-retryable status (4xx other than 429)
    raise last_exc  # exhausted retries


class LLMProfileGenerator:
    """Production implementation — calls real LLM APIs."""

    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key

    async def generate_profile(self, resume_text: str) -> dict:
        caller = _CALLERS.get(self.model)
        if not caller:
            raise ValueError(f"Unsupported model: {self.model}")
        raw = await _retry_on_transient(
            lambda: caller(self.api_key, self.model, resume_text),
            f"Profile generation ({self.model})",
        )
        return _extract_json(raw)


class FakeProfileGenerator:
    """Test fake — returns canned response."""

    def __init__(self, response: dict | None = None):
        self.response = response or {
            "fit_context": "Generated fit context from resume.",
            "tracks": {
                "backend_engineer": {
                    "title": "Backend Engineer",
                    "search_queries": ["backend engineer python", "senior python developer"],
                }
            },
            "filters": {
                "location": {
                    "remote": True,
                    "local_zip": "",
                    "max_commute_minutes": 30,
                    "local_cities": ["San Francisco"],
                },
                "salary": {"min_base": 150000, "currency": "USD"},
                "role_type": {"reject_explicit_ic": False},
            },
        }
        self.last_resume_text: str | None = None

    async def generate_profile(self, resume_text: str) -> dict:
        self.last_resume_text = resume_text
        return self.response
