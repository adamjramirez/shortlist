"""LLM client for profile generation.

Production: calls provider APIs via httpx.
Tests: returns canned response via dependency override.
"""
import json
import re
from typing import Protocol

import httpx


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


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    # Extract from ```json ... ``` blocks
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Last resort: find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError("No JSON found in LLM response")


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


class LLMProfileGenerator:
    """Production implementation — calls real LLM APIs."""

    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key

    async def generate_profile(self, resume_text: str) -> dict:
        caller = _CALLERS.get(self.model)
        if not caller:
            raise ValueError(f"Unsupported model: {self.model}")
        raw = await caller(self.api_key, self.model, resume_text)
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
