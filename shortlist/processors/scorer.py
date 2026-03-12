"""LLM-based job scoring."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from shortlist.collectors.base import RawJob
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
    corrected_title: str = ""
    corrected_company: str = ""
    corrected_location: str = ""


SCORING_PROMPT_TEMPLATE = """You are a job search assistant scoring job listings for fit.

## Candidate Profile

Name: {name}

### What This Person Is Best At
{fit_context}

### Target Role Tracks
{tracks_description}

### Hard Requirements
- Location: Remote or within 30 min of {local_zip}
- Salary: Minimum ${min_salary:,} base
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
    "salary_estimate": "<format as $XXXk-$XXXk, e.g. $200k-$300k>",
    "salary_confidence": "<low|medium|high>",
    "corrected_title": "<the actual job title, e.g. 'VP of Engineering'>",
    "corrected_company": "<the actual company name>",
    "corrected_location": "<the actual location, e.g. 'Remote' or 'San Francisco, CA'>"
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

Return ONLY the JSON object, no other text."""


def build_scoring_prompt(job: RawJob, config: Config) -> str:
    """Build the scoring prompt for a job."""
    tracks_desc = []
    for key, track in config.tracks.items():
        tracks_desc.append(
            f"- **{key}**: {track.title} "
            f"(target: {track.target_orgs}, min reports: {track.min_reports})"
        )

    track_keys = ", ".join(config.tracks.keys()) or "default"

    return SCORING_PROMPT_TEMPLATE.format(
        name=config.name or "Candidate",
        fit_context=config.fit_context or "No additional context provided.",
        tracks_description="\n".join(tracks_desc),
        track_keys=track_keys,
        local_zip=config.filters.location.local_zip or "",
        min_salary=config.filters.salary.min_base or 250000,
        title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        salary_text=job.salary_text or "Not listed",
        source=job.source,
        description=job.description,
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
        corrected_title=data.get("corrected_title", ""),
        corrected_company=data.get("corrected_company", ""),
        corrected_location=data.get("corrected_location", ""),
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
        "corrected_title": {"type": "STRING"},
        "corrected_company": {"type": "STRING"},
        "corrected_location": {"type": "STRING"},
    },
    "required": ["fit_score", "matched_track", "reasoning", "yellow_flags",
                  "salary_estimate", "salary_confidence", "corrected_title",
                  "corrected_company", "corrected_location"],
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
