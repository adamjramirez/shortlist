# Prestige Tier Refactor

**Goal:** Fix two structural problems with the current prestige_tier implementation:
1. Criteria are hardcoded strings — not derived from the user's track configuration
2. No standalone prestige function — backfill and re-evaluation require a separate prompt that can drift

**Approach:**
- `build_prestige_criteria(config)` — derives tier criteria from `config.tracks` (titles, target_orgs, min_reports). Pure function.
- `score_prestige(job, config)` — standalone LLM function, own prompt/schema/parser. Used for backfill and future re-evaluation.
- Main `score_job()` keeps its single LLM call — no extra cost — but uses `build_prestige_criteria()` to populate the prestige section. One source of truth.
- Backfill script runs `score_prestige()` on all visible jobs with `prestige_tier IS NULL`.

**Files affected:**
- `shortlist/processors/scorer.py` (modify)
- `scripts/backfill_prestige.py` (create)
- `tests/test_scorer.py` (modify)
- `tests/test_job_prestige.py` (modify)

---

## Task 1: `build_prestige_criteria(config)` — derive from tracks

**File:** `shortlist/processors/scorer.py` (modify)
**Purpose:** Replace the hardcoded tier criteria string in the prompt with a function that derives it from `config.tracks`.

### Steps

1. Write failing tests in `tests/test_job_prestige.py`:
```python
def test_build_prestige_criteria_includes_track_titles():
    """Criteria string includes track titles from config."""
    from shortlist.processors.scorer import build_prestige_criteria
    from shortlist.config import Config, Track
    config = Config(tracks={
        "vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10),
        "cto": Track(title="CTO", target_orgs="scale-up", min_reports=15),
    })
    result = build_prestige_criteria(config)
    assert "VP of Engineering" in result
    assert "CTO" in result

def test_build_prestige_criteria_includes_min_reports():
    """Criteria string includes the maximum min_reports across tracks."""
    from shortlist.processors.scorer import build_prestige_criteria
    from shortlist.config import Config, Track
    config = Config(tracks={
        "vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10),
    })
    result = build_prestige_criteria(config)
    assert "10" in result

def test_build_prestige_criteria_empty_tracks():
    """Returns a sensible fallback when no tracks configured."""
    from shortlist.processors.scorer import build_prestige_criteria
    from shortlist.config import Config
    config = Config()
    result = build_prestige_criteria(config)
    assert isinstance(result, str)
    assert len(result) > 0
```

2. Verify tests fail:
```bash
cd /Users/adam1/Code/shortlist
python3 -m pytest tests/test_job_prestige.py::test_build_prestige_criteria_includes_track_titles tests/test_job_prestige.py::test_build_prestige_criteria_includes_min_reports tests/test_job_prestige.py::test_build_prestige_criteria_empty_tracks -q
```
Expected: FAIL (function doesn't exist)

3. Implement `build_prestige_criteria(config)` in `shortlist/processors/scorer.py` — add before `SCORING_PROMPT_TEMPLATE`:
```python
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
```

4. Verify tests pass:
```bash
python3 -m pytest tests/test_job_prestige.py::test_build_prestige_criteria_includes_track_titles tests/test_job_prestige.py::test_build_prestige_criteria_includes_min_reports tests/test_job_prestige.py::test_build_prestige_criteria_empty_tracks -q
```
Expected: 3 passed

---

## Task 2: Wire `build_prestige_criteria` into the main scoring prompt

**File:** `shortlist/processors/scorer.py` (modify)
**Purpose:** Replace the hardcoded prestige criteria block in `SCORING_PROMPT_TEMPLATE` with a `{prestige_criteria}` placeholder populated from `build_prestige_criteria(config)`.

### Steps

1. Write failing test in `tests/test_scorer.py`:
```python
def test_build_scoring_prompt_includes_prestige_criteria_from_config():
    """Main scoring prompt derives prestige criteria from config tracks."""
    from shortlist.processors.scorer import build_scoring_prompt
    from shortlist.collectors.base import RawJob

    # Use the existing config fixture's track titles
    config = Config(
        name="Test",
        fit_context="Engineering leader",
        tracks={"vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10)},
        filters=Filters(
            salary=SalaryFilter(min_base=200000, currency="USD"),
            location=LocationFilter(remote=True),
        ),
    )
    job = RawJob(title="VP Eng", company="Acme", url="https://example.com",
                 description="desc", source="linkedin", location="Remote")
    prompt = build_scoring_prompt(job, config)
    assert "VP of Engineering" in prompt
```

2. Verify fails:
```bash
python3 -m pytest tests/test_scorer.py::test_build_scoring_prompt_includes_prestige_criteria_from_config -q
```
Expected: FAIL

3. Implement — two changes to `shortlist/processors/scorer.py`:

**a) `SCORING_PROMPT_TEMPLATE`** — replace the hardcoded prestige block:

Old:
```
### Job Prestige Tier
Evaluate this specific job as a career move for THIS candidate. Return A, B, C, or D.

Consider these four criteria relative to the candidate's profile and seniority target:
1. **Role level** — Is this a step up or right level? (VP/CTO = good, Manager/IC = step back)
2. **Company prestige** — Well-known brand in tech? Does the name open doors?
3. **Domain momentum** — Hot, growing, important space? (AI/security/cloud-native = hot)
4. **Upside** — Real equity and scope growth potential?

- **A**: Career-defining. Right level, strong brand, hot domain, real upside.
- **B**: Solid. Most criteria met. Worth engaging seriously.
- **C**: Fine. Lateral move, limited brand, or slow domain. Passive interest only.
- **D**: Deprioritize. Step back in level, no brand, capped upside.
```

New (use single braces — this is a `.format()` parameter, not an escaped literal):
```
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
```

**b) `build_scoring_prompt()`** — add `prestige_criteria=build_prestige_criteria(config)` to the `.format()` call.

4. Verify:
```bash
python3 -m pytest tests/test_scorer.py::test_build_scoring_prompt_includes_prestige_criteria_from_config -q
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass

---

## Task 3: Standalone `score_prestige(job, config)` function

**File:** `shortlist/processors/scorer.py` (modify)
**Purpose:** A focused LLM function that returns only `prestige_tier` for a job. Used for backfill and future re-evaluation. Reuses `build_prestige_criteria()` — single source of truth.

### Steps

1. Write failing tests in `tests/test_scorer.py`:
```python
def test_score_prestige_returns_valid_tier(monkeypatch):
    """score_prestige returns A/B/C/D from LLM response."""
    from shortlist.processors.scorer import score_prestige
    import shortlist.llm as llm_mod

    monkeypatch.setattr(llm_mod, "call_llm", lambda *a, **kw: '{"prestige_tier": "B"}')

    config = Config(
        fit_context="Engineering leader",
        tracks={"vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10)},
    )
    job = RawJob(title="VP Eng", company="Acme", url="https://example.com",
                 description="desc", source="linkedin", location="Remote")
    assert score_prestige(job, config) == "B"

def test_score_prestige_returns_empty_on_llm_failure(monkeypatch):
    """score_prestige returns empty string when LLM call fails."""
    from shortlist.processors.scorer import score_prestige
    import shortlist.llm as llm_mod

    monkeypatch.setattr(llm_mod, "call_llm", lambda *a, **kw: None)

    config = Config(
        fit_context="Engineering leader",
        tracks={"vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10)},
    )
    job = RawJob(title="VP Eng", company="Acme", url="https://example.com",
                 description="desc", source="linkedin", location="Remote")
    assert score_prestige(job, config) == ""
```

2. Verify tests fail:
```bash
python3 -m pytest tests/test_scorer.py::test_score_prestige_returns_valid_tier tests/test_scorer.py::test_score_prestige_returns_empty_on_llm_failure -q
```
Expected: FAIL

3. Implement in `shortlist/processors/scorer.py` — add after `build_prestige_criteria()`, before `SCORING_PROMPT_TEMPLATE`:

```python
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
1. **Role level** — Does this match or exceed the candidate's target level?
2. **Company prestige** — Well-known brand in tech? Does the name open doors?
3. **Domain momentum** — Hot, growing, important space? (AI/security/cloud-native = hot)
4. **Upside** — Real equity and scope growth potential?

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

    Standalone function — safe to call without re-scoring fit.
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
```

4. Verify tests pass:
```bash
python3 -m pytest tests/test_scorer.py::test_score_prestige_returns_valid_tier tests/test_scorer.py::test_score_prestige_returns_empty_on_llm_failure -q
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass

---

## Task 4: Backfill script

**File:** `scripts/backfill_prestige.py` (create)
**Purpose:** Fetch all visible jobs with `prestige_tier IS NULL`, score each with `score_prestige()`, write tier back. Runs once.

**Note:** Uses `config/profile.yaml` (local CLI config), not the DB profile. Acceptable for a one-time run against Adam's single account.

### Steps

1. Create the script:
```python
#!/usr/bin/env python3
"""Backfill prestige_tier for all visible jobs that don't have one yet.

Run once after deploying the prestige refactor:
    DATABASE_URL=<url> python3 scripts/backfill_prestige.py

Requires DATABASE_URL and config/profile.yaml.
"""
import os
import sys
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras

from shortlist.config import load_config
from shortlist.collectors.base import RawJob
from shortlist.processors.scorer import score_prestige
from shortlist.pgdb import update_job


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    config = load_config(Path("config/profile.yaml"))
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, title, company, url, description, location,
                   salary_text, sources_seen
            FROM jobs
            WHERE fit_score >= 75
              AND NOT is_closed
              AND prestige_tier IS NULL
            ORDER BY fit_score DESC
        """)
        rows = cur.fetchall()

    logger.info(f"Found {len(rows)} jobs to backfill")

    scored = 0
    failed = 0
    for row in rows:
        sources = row["sources_seen"] or []
        source = (sources[0] if isinstance(sources, list) else sources) if sources else "unknown"

        job = RawJob(
            title=row["title"],
            company=row["company"],
            url=row["url"] or "",
            description=row["description"] or "",
            source=source,
            location=row["location"] or "",
            salary_text=row["salary_text"],
        )

        tier = score_prestige(job, config)
        if tier:
            update_job(conn, row["id"], prestige_tier=tier)
            conn.commit()
            scored += 1
            logger.info(f"  [{tier}] {row['title'][:45]} @ {row['company'][:25]}")
        else:
            failed += 1
            logger.warning(f"  [?] Failed: {row['title'][:45]} @ {row['company'][:25]}")

        time.sleep(0.5)  # rate limit — 2 req/s

    logger.info(f"\nDone. {scored} scored, {failed} failed.")
    conn.close()


if __name__ == "__main__":
    main()
```

2. Verify it parses:
```bash
cd /Users/adam1/Code/shortlist
python3 -c "import ast; ast.parse(open('scripts/backfill_prestige.py').read()); print('syntax ok')"
```

3. Get DATABASE_URL and run:
```bash
fly proxy 5432 --app shortlist-db &
sleep 2
DATABASE_URL="postgresql://shortlist_web:<password>@localhost:5432/shortlist_web" \
python3 scripts/backfill_prestige.py
```

---

## Task 5: Full verification

```bash
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass, ≥590 tests

Spot-check that the prompt contains your real track titles:
```bash
cd /Users/adam1/Code/shortlist
python3 -c "
from pathlib import Path
from shortlist.config import load_config
from shortlist.processors.scorer import build_prestige_criteria
config = load_config(Path('config/profile.yaml'))
print(build_prestige_criteria(config))
"
```
Expected: lists your actual track titles from `config/profile.yaml`

---

## What this fixes

| Problem | Before | After |
|---------|--------|-------|
| Criteria source | Hardcoded strings in prompt | Derived from `config.tracks` |
| Backfill | Needs a separate ad-hoc prompt | `score_prestige()` — same logic as main scorer |
| Criteria drift | Two prompts can diverge | One `build_prestige_criteria()` used by both |
| Updating criteria | Edit Python string in scorer.py | Update your profile tracks |
