# Fix User Experience — Pipeline Bug, Location Scoring, User Recovery

**Date:** 2026-04-02  
**Goal:** Fix the three concrete problems discovered from user data investigation.

**Context:**
- Jeremiah's run (#27) crashed at interest note generation — `from_json()` called on a dict from PG JSON column
- Jeremiah got 3 US-only jobs despite being UK-based (Devon) — scorer prompt doesn't mention user's country/cities
- Mihai churned after 429s on profile analysis — now fixed, but needs personal outreach to bring back

---

## Problem 1: Pipeline crash — `from_json()` gets dict from PG JSON column

**Root cause:** `CompanyIntel.from_json(name, data)` calls `json.loads(data)`. The `enrichment` column on the `jobs` table is `JSON` type in PostgreSQL. When psycopg2 reads a JSON column, it auto-deserializes to a Python dict. So `data` is already a dict, and `json.loads(dict)` raises `TypeError: the JSON object must be str, bytes or bytearray, not dict`.

**Blast radius:** Every pipeline run that reaches the interest note generation phase will crash if any scored job has enrichment data. This affects all users.

**Same bug exists in:** `brief.py:221` (same `from_json` call on enrichment from DB).

### Task 1: Fix `from_json()` to accept both str and dict

**File:** `shortlist/processors/enricher.py` (modify)  
**Purpose:** Make `from_json()` handle both string (from SQLite/CLI) and dict (from PG JSON column).

Change:
```python
@classmethod
def from_json(cls, name: str, data: str) -> "CompanyIntel":
    d = json.loads(data)
```

To:
```python
@classmethod
def from_json(cls, name: str, data: str | dict) -> "CompanyIntel":
    d = data if isinstance(data, dict) else json.loads(data)
```

**Verify:**
```bash
.venv/bin/pytest tests/ -q -k "enricher or enrichment or intel"
```

### Task 2: Test both input types

**File:** `tests/test_enricher.py` (create or modify — check if exists)  
**Purpose:** Verify `from_json()` works with both string and dict input.

```python
def test_from_json_with_string():
    intel = CompanyIntel.from_json("Acme", '{"stage": "series_b", "headcount_estimate": 200}')
    assert intel.stage == "series_b"
    assert intel.headcount_estimate == 200

def test_from_json_with_dict():
    """PG JSON columns return dicts — from_json must handle both."""
    intel = CompanyIntel.from_json("Acme", {"stage": "series_b", "headcount_estimate": 200})
    assert intel.stage == "series_b"
    assert intel.headcount_estimate == 200
```

**Verify:**
```bash
.venv/bin/pytest tests/test_enricher.py -q
```

### Task 3: Add error handling around interest note loop

**File:** `shortlist/pipeline.py` (modify)  
**Purpose:** A single bad job shouldn't crash the entire pipeline. Wrap per-job processing in try/except so the run continues even if one interest note fails.

Change the interest note loop (line ~686):
```python
for i, row in enumerate(needs_notes, 1):
    _check_cancel()
    _emit(on_progress, ...)
    intel_json = row.get("enrichment")
    intel = CompanyIntel.from_json(row["company"], intel_json) if intel_json else None
    note = generate_interest_note(...)
    ...
```

To:
```python
for i, row in enumerate(needs_notes, 1):
    _check_cancel()
    _emit(on_progress, ...)
    try:
        intel_json = row.get("enrichment")
        intel = CompanyIntel.from_json(row["company"], intel_json) if intel_json else None
        note = generate_interest_note(
            row["company"], row["title"], row["description"] or "",
            config.fit_context, intel,
        )
        if note:
            pgdb.update_job(conn, row["id"], interest_note=note)
            llm_calls += 1
    except Exception as e:
        logger.error("Interest note failed for job %s (%s): %s", row["id"], row["company"], e)
```

Same wrapping for the enrichment loop (`_enrich_scored_jobs` inner loop, line ~639) — a single company failing enrichment shouldn't kill the run.

**Verify:**
```bash
.venv/bin/pytest tests/ -q -k "pipeline"
```

---

## Problem 2: UK user gets US-only jobs scored 75+

**Root cause:** The scoring prompt says `Location: Remote or within 30 min of {local_zip}` but doesn't include `local_cities`. Jeremiah's `local_zip` is `TQ13 8EH` (Devon, UK) and `local_cities` is `["London"]`. The LLM sees the UK postcode but jobs listing "Remote" that require US presence still score well because the prompt doesn't explicitly say "user is based in UK — penalize US-only remote roles."

The filter is working correctly — it passes "Remote" jobs through. The issue is the **scorer** not adequately penalizing geographic mismatches.

### Task 4: Add local_cities to scoring prompt

**File:** `shortlist/processors/scorer.py` (modify)  
**Purpose:** Include local_cities in the prompt so the LLM knows the user's country/region and can properly evaluate "Remote (US only)" style restrictions.

Change the hard requirements section in `SCORING_PROMPT_TEMPLATE`:
```
### Hard Requirements
- Location: Remote or within 30 min of {local_zip}
```

To:
```
### Hard Requirements
- Location: {location_requirement}
- If a role says "Remote" but restricts to a specific country/region the candidate is NOT in, score below 60.
```

And in `build_scoring_prompt()`, build a single clean location string:
```python
local_cities = config.filters.location.local_cities
local_zip = config.filters.location.local_zip
parts = []
if local_cities:
    parts.append(", ".join(local_cities))
if local_zip:
    parts.append(local_zip)
location_requirement = f"Remote or near {' / '.join(parts)}" if parts else "Remote"
```

This produces:
- Jeremiah (UK): `"Remote or near London / TQ13 8EH"`
- Adam (US): `"Remote or near 75098"`
- No location info: `"Remote"`

Replace `local_zip=config.filters.location.local_zip or ""` in the `.format()` call with `location_requirement=location_requirement`.

**Verify:**
```bash
.venv/bin/pytest tests/ -q -k "scorer"
```

### Task 5: Test location in scoring prompt

**File:** `tests/test_scorer.py` (modify)  
**Purpose:** Add tests verifying local_cities and the country-restriction instruction appear in the prompt.

Add to `TestBuildScoringPrompt`:
```python
def test_scoring_prompt_includes_local_cities(self, sample_job):
    """UK user's cities appear in prompt so LLM can penalize US-only roles."""
    config = Config(
        name="Test",
        filters=Filters(
            location=LocationFilter(
                remote=True,
                local_zip="TQ13 8EH",
                local_cities=["London"],
            ),
            salary=SalaryFilter(min_base=120000),
            role_type=RoleTypeFilter(),
        ),
    )
    prompt = build_scoring_prompt(sample_job, config)
    assert "London" in prompt
    assert "TQ13 8EH" in prompt
    assert "score below 60" in prompt.lower()

def test_scoring_prompt_zip_only(self, sample_job, config):
    """US user with zip but no cities still gets clean location line."""
    prompt = build_scoring_prompt(sample_job, config)
    assert "75098" in prompt
    assert "Remote or near" in prompt
```

**Verify:**
```bash
.venv/bin/pytest tests/test_scorer.py -q
```

---

## Problem 3: Bring Mihai back

**Not a code change.** Mihai (`mihai.leontescu@hotmail.com`) signed up Mar 18, tried profile analysis 4x with OpenAI, hit 429 every time, and left. He has an API key saved (gpt-4o-mini) but empty profile (no fit_context, no tracks).

### Task 6: Draft and send personal email

Short, honest, specific:

```
Subject: Fixed the issue you hit on Shortlist

Hi Mihai,

I'm Adam, the developer behind Shortlist. I saw you tried to analyze your 
resume on March 18th and hit rate limit errors from OpenAI — sorry about that.

I've fixed it: the system now retries automatically, and I've also added 
better error handling so it won't just fail silently. If you'd like to try 
again, your account is ready to go — just log in and hit "Analyze" on your 
resume.

Quick tip: Gemini 2.0 Flash works great and has generous free-tier limits 
if you'd prefer to switch from OpenAI.

Let me know if you run into anything.

Adam
```

No code needed. Just send it.

---

## Execution Order

| # | Task | Risk | Time |
|---|------|------|------|
| 1 | Fix `from_json()` str/dict | **Critical** — every run crashes | 5 min |
| 2 | Test both input types | Validates fix | 5 min |
| 3 | Try/except around enrichment loops | Prevents future pipeline crashes | 10 min |
| 4 | Add local_cities to scoring prompt | Improves match quality for non-US users | 10 min |
| 5 | Test scoring prompt | Validates prompt change | 5 min |
| 6 | Email Mihai | Human task | 5 min |

Then deploy (picks up both PostHog changes from earlier + these fixes).

## Files Changed

| File | Action |
|------|--------|
| `shortlist/processors/enricher.py` | Modify — `from_json()` accepts dict |
| `shortlist/pipeline.py` | Modify — try/except around enrichment loops |
| `shortlist/processors/scorer.py` | Modify — local_cities in prompt |
| `tests/test_enricher.py` | Create/modify — dict input test |
| `tests/` (scorer tests) | Modify — prompt content test |
