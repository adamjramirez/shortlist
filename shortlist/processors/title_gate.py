"""LLM-based title gate: batch pre-filter that runs before full scorer.

Jobs that fail the gate are moved to status='title_rejected'.
Gate is always fail-open — any LLM error passes the job through.
"""
import json
import logging

from shortlist.collectors.base import RawJob
from shortlist.config import Config
from shortlist import llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini structured output schema
# ---------------------------------------------------------------------------

TITLE_GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "pass": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "pass"],
            },
        }
    },
    "required": ["decisions"],
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_target_role_levels(config: Config) -> str:
    """Return comma-separated track titles; fallback when none configured."""
    titles = [t.title for t in config.tracks.values() if t.title]
    if not titles:
        return "senior engineering leadership"
    return ", ".join(titles)


def build_title_gate_prompt(config: Config, batch: list[tuple[int, RawJob]]) -> str:
    """Build a compact gate prompt for a batch of (row_id, RawJob) pairs.

    Items are numbered 1..N so the LLM can reference them by index.
    fit_context is intentionally excluded — the gate only looks at titles.
    """
    role_levels = build_target_role_levels(config)

    lines = [
        "You are a job title filter. Your job is to decide whether each role title",
        "is plausibly relevant for a candidate targeting specific leadership roles.",
        "",
        f"Target role levels: {role_levels}",
        "",
        "For each job below, decide: Pass iff the title plausibly matches one of the",
        "target role levels AT A COMPATIBLE SCOPE. When in doubt, pass.",
        "",
        "Jobs to evaluate:",
    ]

    for i, (row_id, job) in enumerate(batch, 1):
        location = job.location or "unknown"
        lines.append(f"{i}. {job.title} at {job.company} ({location})")

    lines += [
        "",
        'Return JSON: {"decisions": [{"id": 1, "pass": true, "reason": "..."}, ...]}',
        "where id is the job number (1-based), pass is true/false, reason is brief.",
        "Include one entry per job.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_title_gate_response(
    raw: str | None,
    batch: list[tuple[int, RawJob]],
) -> dict[int, tuple[bool, str]]:
    """Parse LLM response into {row_id: (passed, reason)} mapping.

    Always fail-open: any error or missing entry defaults to (True, "").
    IDs in the response are 1-based indices into the batch (not DB row_ids).
    """
    # Build lookup: 1-based index → actual DB row_id
    index_to_row = {i + 1: row_id for i, (row_id, _) in enumerate(batch)}

    # Initialise all to pass (fail-open default)
    result: dict[int, tuple[bool, str]] = {row_id: (True, "") for row_id, _ in batch}

    if raw is None:
        return result

    try:
        data = json.loads(raw)
        decisions = data["decisions"]
    except (json.JSONDecodeError, ValueError, KeyError):
        return result

    for d in decisions:
        try:
            idx = int(d.get("id", 0))
        except (ValueError, TypeError):
            continue

        row_id = index_to_row.get(idx)
        if row_id is None:
            continue

        passed = bool(d.get("pass", True))
        reason = str(d.get("reason", ""))[:200]
        result[row_id] = (passed, reason)

    return result


# ---------------------------------------------------------------------------
# Main gate function
# ---------------------------------------------------------------------------

def gate_titles(
    batch_all: list[tuple[int, RawJob]],
    config: Config,
) -> tuple[dict[int, tuple[bool, str]], int]:
    """Run the title gate on a list of (row_id, RawJob) pairs.

    Returns (decisions_dict, batch_count) where decisions_dict maps
    row_id → (passed, reason). Gate is always fail-open.
    """
    if not batch_all:
        return {}, 0

    chunk_size = config.llm.title_gate_batch_size or 50
    out: dict[int, tuple[bool, str]] = {}
    batch_count = 0

    for start in range(0, len(batch_all), chunk_size):
        chunk = batch_all[start : start + chunk_size]
        prompt = build_title_gate_prompt(config, chunk)
        raw = llm.call_llm(prompt, json_schema=TITLE_GATE_SCHEMA)
        out.update(parse_title_gate_response(raw, chunk))
        batch_count += 1

    return out, batch_count
