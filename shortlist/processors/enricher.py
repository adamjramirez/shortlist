"""Company enrichment and post-enrichment re-scoring.

Uses Gemini to gather company intel, caches in the companies table,
and optionally re-scores jobs when enrichment reveals material info.
"""
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dotenv import load_dotenv

from shortlist import http
from shortlist.config import Config

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_DOMAIN = "generativelanguage.googleapis.com"
CACHE_DAYS = 30  # Don't re-enrich within this window

# Job boards / aggregators — don't enrich these, they're not the real employer
JOB_BOARD_COMPANIES = {
    # Job board aggregators
    "jobgether", "hired", "otta", "wellfound", "angellist", "triplebyte",
    "underdog.io", "underdog", "a]leet", "leet", "cord", "turing",
    "toptal", "braintrust", "andela", "crossover", "remote.co",
    "weworkremotely", "remoteok", "flexjobs", "dice",
    # Staffing / recruiting firms
    "hays", "robert half", "robert walters", "randstad", "adecco",
    "kforce", "insight global", "tek systems", "teksystems",
    "seneca creek", "seneca creek es",
    "method recruiting", "missionhires", "talener", "lhh",
    "storm4", "on data staffing", "madison-davis",
    "confidential",
}


@dataclass
class CompanyIntel:
    name: str
    stage: str = "unknown"
    last_funding: str = "unknown"
    headcount_estimate: int | None = None
    growth_signal: str = "unknown"
    glassdoor_rating: float | None = None
    eng_blog_url: str | None = None
    website_domain: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    oss_presence: str = "unknown"
    domain_description: str = ""
    hq_location: str = "unknown"

    def to_json(self) -> str:
        return json.dumps({
            "stage": self.stage,
            "last_funding": self.last_funding,
            "headcount_estimate": self.headcount_estimate,
            "growth_signal": self.growth_signal,
            "glassdoor_rating": self.glassdoor_rating,
            "eng_blog_url": self.eng_blog_url,
            "website_domain": self.website_domain,
            "tech_stack": self.tech_stack,
            "oss_presence": self.oss_presence,
            "domain_description": self.domain_description,
            "hq_location": self.hq_location,
        })

    @classmethod
    def from_json(cls, name: str, data: str) -> "CompanyIntel":
        d = json.loads(data)
        return cls(
            name=name,
            stage=d.get("stage", "unknown"),
            last_funding=d.get("last_funding", "unknown"),
            headcount_estimate=d.get("headcount_estimate"),
            growth_signal=d.get("growth_signal", "unknown"),
            glassdoor_rating=d.get("glassdoor_rating"),
            eng_blog_url=d.get("eng_blog_url"),
            website_domain=d.get("website_domain"),
            tech_stack=d.get("tech_stack", []),
            oss_presence=d.get("oss_presence", "unknown"),
            domain_description=d.get("domain_description", ""),
            hq_location=d.get("hq_location", "unknown"),
        )

    def has_material_info(self) -> bool:
        """Does this enrichment have info worth re-scoring for?"""
        material = 0
        if self.stage not in ("unknown", ""):
            material += 1
        if self.glassdoor_rating is not None:
            material += 1
        if self.growth_signal in ("growing", "shrinking"):
            material += 1
        if self.headcount_estimate is not None:
            material += 1
        return material >= 2

    def summary(self) -> str:
        """One-line summary for the brief."""
        parts = []
        if self.stage != "unknown":
            parts.append(self.stage)
        if self.headcount_estimate:
            parts.append(f"~{self.headcount_estimate} people")
        if self.last_funding != "unknown":
            parts.append(self.last_funding)
        if self.glassdoor_rating:
            parts.append(f"Glassdoor {self.glassdoor_rating}")
        if self.growth_signal != "unknown":
            parts.append(self.growth_signal)
        if self.oss_presence in ("strong", "moderate"):
            parts.append(f"OSS: {self.oss_presence}")
        return " | ".join(parts) if parts else "No enrichment data"


ENRICH_PROMPT = """Return a JSON object with what you know about this company. Be factual — say "unknown" if unsure. Do not guess or hallucinate.

Company: {company}
Context from job listing: {context}

```json
{{
    "stage": "<seed/A/B/C/D/E/public/private/PE-backed or unknown>",
    "last_funding": "<amount and date if known, or unknown>",
    "headcount_estimate": <number or null>,
    "growth_signal": "<growing/stable/shrinking/unknown>",
    "glassdoor_rating": <number 1.0-5.0 or null>,
    "eng_blog_url": "<url or null>",
    "website_domain": "<company's main website domain, e.g. 'atlassian.com' or null>",
    "tech_stack": ["<known technologies>"],
    "oss_presence": "<strong/moderate/weak/unknown>",
    "domain_description": "<what they do in one line>",
    "hq_location": "<city, state or unknown>"
}}
```

Return ONLY the JSON object."""


RESCORE_PROMPT = """A job was scored before company enrichment data was available. Review whether the score should change.

## Original Score
- **Score:** {score}/100
- **Reasoning:** {reasoning}
- **Yellow flags:** {yellow_flags}

## Company Enrichment
{enrichment_summary}

## Candidate Fit Context
{fit_context}

## Re-Score Rules
- Series A with fresh funding → score down 5-10 points (yellow flag)
- Glassdoor < 3.0 → score down 10-15 points
- Glassdoor > 4.2 → score up 3-5 points
- Company shrinking → score down 10-15 points
- Strong OSS/eng culture → score up 3-5 points
- PE-backed needing transformation → score up 5-10 if VP track
- ML research company → score down 10-20 (not a fit)
- If enrichment doesn't reveal anything material, keep the score the same.

Return ONLY a JSON object:
```json
{{
    "new_score": <0-100>,
    "score_delta": <change from original, e.g. -5 or +3 or 0>,
    "reasoning": "<one sentence explaining why score changed or didn't>"
}}
```"""


def _normalize_company(name: str) -> str:
    """Normalize company name for cache lookup."""
    name = name.lower().strip()
    # Strip trailing punctuation first
    name = name.rstrip(".,;")
    # Strip common suffixes (repeat to catch "Inc." after comma)
    for _ in range(3):
        prev = name
        name = name.rstrip(".,; ")
        for suffix in (" inc", " llc", " corp", " co", " ltd", " limited",
                       " company", " technologies", " labs", " gmbh", " pbc"):
            name = name.removesuffix(suffix)
        if name == prev:
            break
    return name.strip()


def get_cached_enrichment(db: sqlite3.Connection, company: str) -> CompanyIntel | None:
    """Check if we have recent enrichment for this company."""
    normalized = _normalize_company(company)
    row = db.execute(
        "SELECT * FROM companies WHERE name_normalized = ? "
        "AND enriched_at > datetime('now', ?)",
        (normalized, f"-{CACHE_DAYS} days"),
    ).fetchone()

    if row and row["growth_signals"]:
        return CompanyIntel.from_json(company, row["growth_signals"])
    return None


def is_job_board(company: str) -> bool:
    """Check if this company is a job board/aggregator, not a real employer."""
    normalized = _normalize_company(company)
    if normalized in JOB_BOARD_COMPANIES:
        return True
    # Check if any known recruiter name is a prefix
    # (handles "Method Recruiting, a 3x Inc. 5000 company" matching "method recruiting")
    return any(normalized.startswith(name) for name in JOB_BOARD_COMPANIES)


def enrich_company(company: str, job_description: str) -> CompanyIntel | None:
    """Enrich a company using Gemini. Returns None on failure or for job boards."""
    if is_job_board(company):
        logger.info(f"Skipping enrichment for job board: {company}")
        return None

    context = job_description[:500] if job_description else ""
    prompt = ENRICH_PROMPT.format(company=company, context=context)

    result = _call_gemini(prompt)
    if not result:
        return None

    try:
        data = _parse_json(result)
        intel = CompanyIntel(
            name=company,
            stage=data.get("stage", "unknown"),
            last_funding=data.get("last_funding", "unknown"),
            headcount_estimate=data.get("headcount_estimate"),
            growth_signal=data.get("growth_signal", "unknown"),
            glassdoor_rating=data.get("glassdoor_rating"),
            eng_blog_url=data.get("eng_blog_url"),
            website_domain=data.get("website_domain"),
            tech_stack=data.get("tech_stack", []),
            oss_presence=data.get("oss_presence", "unknown"),
            domain_description=data.get("domain_description", ""),
            hq_location=data.get("hq_location", "unknown"),
        )
        return intel
    except Exception as e:
        logger.error(f"Failed to parse enrichment for {company}: {e}")
        return None


def cache_enrichment(db: sqlite3.Connection, company: str, intel: CompanyIntel) -> None:
    """Cache enrichment data in the companies table."""
    normalized = _normalize_company(company)
    db.execute(
        "INSERT INTO companies (name, name_normalized, domain, stage, headcount, "
        "growth_signals, glassdoor_rating, eng_blog_url, enriched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(name_normalized, domain) DO UPDATE SET "
        "stage = excluded.stage, headcount = excluded.headcount, "
        "growth_signals = excluded.growth_signals, "
        "glassdoor_rating = excluded.glassdoor_rating, "
        "eng_blog_url = excluded.eng_blog_url, "
        "domain = excluded.domain, "
        "enriched_at = datetime('now')",
        (company, normalized, intel.website_domain, intel.stage,
         intel.headcount_estimate, intel.to_json(), intel.glassdoor_rating,
         intel.eng_blog_url),
    )
    db.commit()


def rescore_with_enrichment(
    original_score: int, reasoning: str, yellow_flags: str,
    intel: CompanyIntel, config: Config,
) -> tuple[int, int, str] | None:
    """Re-score a job based on enrichment data.

    Returns (new_score, delta, reasoning) or None if no change needed.
    """
    if not intel.has_material_info():
        return None

    prompt = RESCORE_PROMPT.format(
        score=original_score,
        reasoning=reasoning,
        yellow_flags=yellow_flags,
        enrichment_summary=intel.summary(),
        fit_context=config.fit_context or "No additional context.",
    )

    result = _call_gemini(prompt)
    if not result:
        return None

    try:
        data = _parse_json(result)
        new_score = max(0, min(100, int(data.get("new_score", original_score))))
        delta = new_score - original_score
        reason = data.get("reasoning", "")

        if delta == 0:
            return None
        return new_score, delta, reason
    except Exception as e:
        logger.error(f"Failed to parse rescore response: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    """Call Gemini API with rate limiting."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return None

    client = genai.Client(api_key=api_key)
    try:
        http._wait(GEMINI_DOMAIN)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return None


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM response."""
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
