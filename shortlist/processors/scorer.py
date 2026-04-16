"""LLM-based job scoring."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from shortlist.collectors.base import RawJob
from shortlist.collectors.linkedin import REGION_COUNTRIES
from shortlist.config import Config
from shortlist import llm

logger = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    fit_score: int
    matched_track: str
    reasoning: str = ""
    yellow_flags: list[str] = field(default_factory=list)
    salary_estimate: str = ""
    salary_confidence: str = "low"
    salary_basis: str = ""
    corrected_title: str = ""
    corrected_company: str = ""
    corrected_location: str = ""
    prestige_tier: str = ""  # A / B / C / D — relative to candidate profile


def build_prestige_criteria(config: Config) -> str:
    """Derive prestige tier criteria from the user's track configuration.

    Pulls target role titles, org stage preferences, and minimum scope
    from config.tracks so criteria stay in sync with the user's profile.
    """
    tracks = config.tracks or {}

    titles = [t.title for t in tracks.values() if t.title]
    target_orgs = list(dict.fromkeys(
        t.target_orgs for t in tracks.values()
        if t.target_orgs and t.target_orgs != "any"
    ))
    min_reports = max((t.min_reports or 0) for t in tracks.values()) if tracks else 0

    parts = []
    if titles:
        parts.append(f"Target role levels: {', '.join(titles)}")
    if target_orgs:
        parts.append(f"Preferred org stage: {', '.join(target_orgs)}")
    if min_reports:
        parts.append(f"Minimum team size: {min_reports}+ direct reports")

    if not parts:
        parts.append("Target: senior engineering leadership (VP, Director, CTO)")

    return "\n".join(parts)


PRESTIGE_PROMPT_TEMPLATE = """You are evaluating a job listing as a career move for a specific candidate.

## Candidate Context
{fit_context}

## Candidate's Target
{prestige_criteria}

## Job
Title: {title}
Company: {company}
Location: {location}
Description:
{description}

## Task
Return a JSON object with a single field: the prestige tier of this job as a career move for this candidate.

Four evaluation criteria:
1. **Role level** \u2014 Does this match or exceed the candidate's target level?
2. **Company prestige** \u2014 Well-known brand in tech? Does the name open doors?
3. **Domain momentum** \u2014 Hot, growing, important space? (AI/security/cloud-native = hot)
4. **Upside** \u2014 Real equity and scope growth potential?

Tier definitions:
- **A**: Career-defining. Matches target level, strong brand, hot domain, real upside.
- **B**: Solid. Most criteria met. Worth engaging seriously.
- **C**: Fine. One step below target, limited brand, or slow domain.
- **D**: Deprioritize. Multiple steps below target, no brand, capped upside.

Return ONLY this JSON:
{{"prestige_tier": "<A|B|C|D>"}}"""


PRESTIGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "prestige_tier": {"type": "STRING", "enum": ["A", "B", "C", "D"]},
    },
    "required": ["prestige_tier"],
}


def score_prestige(job: RawJob, config: Config) -> str:
    """Score prestige tier for a single job. Returns A/B/C/D or '' on failure.

    Standalone function \u2014 safe to call without re-scoring fit.
    Used for backfill and future re-evaluation.
    """
    prompt = PRESTIGE_PROMPT_TEMPLATE.format(
        fit_context=config.fit_context or "Senior engineering leader.",
        prestige_criteria=build_prestige_criteria(config),
        title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        description=job.description,
    )
    result = llm.call_llm(prompt, json_schema=PRESTIGE_SCHEMA)
    if not result:
        return ""
    try:
        data = llm.parse_json(result)
        tier = data.get("prestige_tier", "")
        return tier if tier in ("A", "B", "C", "D") else ""
    except (json.JSONDecodeError, ValueError):
        return ""


SCORING_PROMPT_TEMPLATE = """You are a job search assistant scoring job listings for fit.

## Candidate Profile

Name: {name}

### What This Person Is Best At
{fit_context}

### Target Role Tracks
{tracks_description}

### Hard Requirements
- Location: {location_requirement}
- If a role says "Remote" but restricts to a specific country/region the candidate is NOT in, score below 60.
- Salary: Minimum {min_salary:,} {currency} base. If the job lists salary in a different currency, convert approximately.
- Must be a management/leadership role with direct reports
- Prefer ~20+ reports (adjusted for company size/stage)

### Preferences (soft scoring)
- Equity: nice to have, depends on company stage + salary + growth potential
- Travel: less is better
- Series A with fresh funding: yellow flag (score down, don't reject)
- Company growth trajectory: higher is better
- Engineering culture signals: blog, OSS, Glassdoor, tech talks
- Bigger scope relative to company size = better
- Career growth potential: upward trajectory visible

## Job Listing

**Title:** {title}
**Company:** {company}
**Location:** {location}
**Salary (if listed):** {salary_text}
**Source:** {source}

**Full Description:**
{description}

## Instructions

Score this job for fit with the candidate profile. Return a JSON object with exactly these fields:

```json
{{
    "fit_score": <0-100 integer>,
    "matched_track": "<one of: {track_keys}>",
    "reasoning": "<2-3 sentences explaining the score>",
    "yellow_flags": ["<list of concerns, empty if none>"],
    "salary_estimate": "<format as XXXk-XXXk {currency}, e.g. 200k-300k {currency}>",
    "salary_confidence": "<low|medium|high>",
    "salary_basis": "<one sentence explaining what drove the estimate and its confidence, e.g. 'Public comp data for Director+ roles at Series C security companies in SF' or 'Stealth-stage startup, limited data on comp norms at this size'>",
    "corrected_title": "<the actual job title, e.g. 'VP of Engineering'>",
    "corrected_company": "<the actual company name>",
    "corrected_location": "<the actual location, e.g. 'Remote' or 'San Francisco, CA'>",
    "prestige_tier": "<A|B|C|D — see below>"
}}
```

The title/company/location fields above may be wrong due to parsing errors. Use the full description to determine the correct values.

### Scoring Guide
- **90-100:** Exceptional fit. Right level, right scope, right company, right location, salary meets minimum.
- **80-89:** Strong fit. Most criteria met, maybe one minor gap.
- **70-79:** Good fit with caveats. Might be slightly below scope, or salary uncertain.
- **60-69:** Worth reviewing. Some fit but significant unknowns or trade-offs.
- **40-59:** Weak fit. Missing multiple criteria.
- **0-39:** Poor fit. Wrong level, wrong location, IC role, or clearly below salary range.

### Important
- If the role is clearly IC (no management), score below 40.
- If salary is not listed, infer from company stage, role level, and location. Note confidence.
- "Engineering Manager" at a 10-person startup managing 3 people is different from EM at a large org managing 20+. Score accordingly.
- Series A with fresh funding = yellow flag, not disqualifier.

### Job Prestige Tier
Evaluate this specific job as a career move for THIS candidate. Return A, B, C, or D.

**Candidate's target:**
{prestige_criteria}

Four evaluation criteria:
1. **Role level** — Does this match or exceed the candidate's target level?
2. **Company prestige** — Well-known brand in tech? Does the name open doors?
3. **Domain momentum** — Hot, growing, important space? (AI/security/cloud-native = hot)
4. **Upside** — Real equity and scope growth potential?

- **A**: Career-defining. Matches target level, strong brand, hot domain, real upside.
- **B**: Solid. Most criteria met. Worth engaging seriously.
- **C**: Fine. One step below target, limited brand, or slow domain. Passive interest only.
- **D**: Deprioritize. Multiple steps below target, no brand, capped upside.

Return ONLY the JSON object, no other text."""


def _build_location_requirement(config: Config) -> str:
    """Build a clean location requirement string from user config."""
    loc = config.filters.location
    local_cities = loc.local_cities
    local_zip = loc.local_zip
    # Expand region names (e.g. "DACH") to concrete country list for the LLM
    country = loc.country
    if country in REGION_COUNTRIES:
        names = REGION_COUNTRIES[country]
        if len(names) == 1:
            country = names[0]
        elif len(names) == 2:
            country = f"{names[0]} or {names[1]}"
        else:
            country = ", ".join(names[:-1]) + f", or {names[-1]}"
    remote = loc.remote

    parts = []
    if local_cities:
        parts.append(", ".join(local_cities))
    if local_zip:
        parts.append(local_zip)

    near = " / ".join(parts) if parts else ""

    if remote and near and country:
        return f"Remote or near {near} in {country}"
    elif remote and near:
        return f"Remote or near {near}"
    elif remote and country:
        return f"Remote in {country}"
    elif remote:
        return "Remote"
    elif near and country:
        return f"Near {near} in {country}"
    elif near:
        return f"Near {near}"
    elif country:
        return f"In {country}"
    else:
        return "Any location"


def build_scoring_prompt(job: RawJob, config: Config) -> str:
    """Build the scoring prompt for a job."""
    tracks_desc = []
    for key, track in config.tracks.items():
        tracks_desc.append(
            f"- **{key}**: {track.title} "
            f"(target: {track.target_orgs}, min reports: {track.min_reports})"
        )

    track_keys = ", ".join(config.tracks.keys()) or "default"

    currency = config.filters.salary.currency or "USD"

    return SCORING_PROMPT_TEMPLATE.format(
        name=config.name or "Candidate",
        fit_context=config.fit_context or "No additional context provided.",
        tracks_description="\n".join(tracks_desc),
        track_keys=track_keys,
        location_requirement=_build_location_requirement(config),
        min_salary=config.filters.salary.min_base or 250000,
        currency=currency,
        title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        salary_text=job.salary_text or "Not listed",
        source=job.source,
        description=job.description,
        prestige_criteria=build_prestige_criteria(config),
    )


def parse_score_response(response_text: str) -> ScoreResult | None:
    """Parse the LLM response into a ScoreResult."""
    try:
        data = llm.parse_json(response_text)
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"Could not parse score response: {response_text[:200]}")
        return None

    fit_score = data.get("fit_score", 0)
    fit_score = max(0, min(100, int(fit_score)))

    return ScoreResult(
        fit_score=fit_score,
        matched_track=data.get("matched_track", ""),
        reasoning=data.get("reasoning", ""),
        yellow_flags=data.get("yellow_flags", []),
        salary_estimate=data.get("salary_estimate", ""),
        salary_confidence=data.get("salary_confidence", "low"),
        salary_basis=data.get("salary_basis", ""),
        corrected_title=data.get("corrected_title", ""),
        corrected_company=data.get("corrected_company", ""),
        corrected_location=data.get("corrected_location", ""),
        prestige_tier=data.get("prestige_tier", "") if data.get("prestige_tier") in ("A", "B", "C", "D") else "",
    )


SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fit_score": {"type": "INTEGER"},
        "matched_track": {"type": "STRING"},
        "reasoning": {"type": "STRING"},
        "yellow_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "salary_estimate": {"type": "STRING"},
        "salary_confidence": {"type": "STRING", "enum": ["low", "medium", "high"]},
        "salary_basis": {"type": "STRING"},
        "corrected_title": {"type": "STRING"},
        "corrected_company": {"type": "STRING"},
        "corrected_location": {"type": "STRING"},
        "prestige_tier": {"type": "STRING", "enum": ["A", "B", "C", "D"]},
    },
    "required": ["fit_score", "matched_track", "reasoning", "yellow_flags",
                  "salary_estimate", "salary_confidence", "salary_basis",
                  "corrected_title", "corrected_company", "corrected_location",
                  "prestige_tier"],
}


def score_job(job: RawJob, config: Config) -> ScoreResult | None:
    """Score a single job. Returns None on API failure."""
    prompt = build_scoring_prompt(job, config)
    result = llm.call_llm(prompt, json_schema=SCORE_SCHEMA)
    if not result:
        return None
    return parse_score_response(result)


class ScoringCancelledError(Exception):
    """Raised when scoring is cancelled mid-run."""
    pass


def score_jobs_parallel(
    jobs: list[tuple[int, RawJob]],
    config: Config,
    max_workers: int = 10,
    on_scored: callable = None,
    cancel_event: "threading.Event | None" = None,
) -> list[tuple[int, ScoreResult | None]]:
    """Score multiple jobs in parallel using a thread pool.

    Args:
        jobs: list of (row_id, RawJob) tuples
        config: scoring config
        max_workers: number of concurrent LLM calls
        on_scored: optional callback(done, total) after each job is scored
        cancel_event: if set, stop scoring and return partial results

    Returns:
        list of (row_id, ScoreResult | None) tuples
    """
    import threading
    results: list[tuple[int, ScoreResult | None]] = []

    if not jobs:
        return results

    def _score_one(item: tuple[int, RawJob]) -> tuple[int, ScoreResult | None]:
        row_id, job = item
        if cancel_event and cancel_event.is_set():
            return row_id, None
        result = score_job(job, config)
        return row_id, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_score_one, item): item for item in jobs}
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                # Cancel remaining futures and return what we have
                for f in futures:
                    f.cancel()
                break
            row_id, job = futures[future]
            try:
                results.append(future.result(timeout=90))
            except TimeoutError:
                logger.error(f"Scoring timed out for job {row_id}")
                results.append((row_id, None))
            except Exception as e:
                logger.error(f"Scoring thread failed for job {row_id}: {e}")
                results.append((row_id, None))
            if on_scored:
                on_scored(len(results), len(jobs))

    return results
