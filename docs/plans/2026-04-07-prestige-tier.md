# Job Prestige Tier

**Goal:** Add `prestige_tier` (A/B/C/D) to every scored job — a career-trajectory signal evaluated by the scorer relative to the candidate's profile, track, and seniority target.

**Approach:** Extend the existing scorer LLM call with one additional output field. No new LLM call. Pipeline writes it via the existing `update_job` **kwargs path. Store as a DB column for filtering/sorting. Display as a small inert mono badge in JobCard.

**Files affected:**
- `alembic/versions/012_prestige_tier.py` (create)
- `shortlist/processors/scorer.py` (modify)
- `shortlist/pipeline.py` (modify — add prestige_tier to updates dict)
- `shortlist/api/models.py` (modify)
- `shortlist/api/schemas.py` (modify)
- `shortlist/api/routes/jobs.py` (modify)
- `web/src/lib/types.ts` (modify)
- `web/src/components/JobCard.tsx` (modify)
- `tests/test_scorer.py` (modify)
- `tests/test_job_prestige.py` (create)

**Not touched:**
- `shortlist/pgdb.py` — `update_job` is a `**kwargs` passthrough; `fetch_jobs` uses `SELECT *`. No changes needed.

---

## Tier Definitions

The LLM evaluates 4 criteria relative to the candidate:

1. **Role level fit** — Is this a step up, lateral, or step back for this candidate's target? VP/CTO = right level, Manager/IC = step back.
2. **Company prestige** — Well-known brand in tech? Does the name open doors 5 years from now?
3. **Domain momentum** — Hot, growing, important space? (AI/security/cloud-native = hot, legacy enterprise/non-profit = not)
4. **Upside** — Real equity and scope growth? (Pre-IPO venture = high, PE-backed = limited, public = liquid but priced in)

| Tier | Label | Meaning |
|------|-------|---------|
| A | Career-defining | Right level, strong brand, hot domain, real upside. Pursue hard. |
| B | Solid | Most criteria met. Worth engaging seriously. |
| C | Fine | Lateral or one-off criteria. Passive interest only. |
| D | Deprioritize | Step back, no brand, slow domain, or capped upside. |

---

## Task 1: Migration — add prestige_tier column

**File:** `alembic/versions/012_prestige_tier.py` (create)
**Purpose:** Add `prestige_tier VARCHAR(1)` to jobs table. Nullable — null means not yet scored with this feature.

### Steps

1. Create the migration file:
```python
# alembic/versions/012_prestige_tier.py
"""Add prestige_tier to jobs.

Revision ID: 012
Revises: 011
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('prestige_tier', sa.String(1), nullable=True))
    op.create_index('ix_jobs_prestige_tier', 'jobs', ['prestige_tier'])


def downgrade() -> None:
    op.drop_index('ix_jobs_prestige_tier', table_name='jobs')
    op.drop_column('jobs', 'prestige_tier')
```

2. Verify it parses:
```bash
cd /Users/adam1/Code/shortlist
python3 -c "import alembic.versions.v012_prestige_tier; print('ok')" 2>/dev/null || python3 -c "from alembic.config import Config; print('alembic ok')"
```

---

## Task 2: Scorer — add prestige_tier to ScoreResult, prompt, schema, parser

**File:** `shortlist/processors/scorer.py` (modify)
**Purpose:** Add `prestige_tier` as a scorer output. One field added to the dataclass, prompt, schema, and parser.

### Steps

1. Write failing tests in `tests/test_scorer.py`:
```python
def test_score_result_has_prestige_tier():
    from shortlist.processors.scorer import ScoreResult
    r = ScoreResult(fit_score=80, matched_track="vp")
    assert hasattr(r, 'prestige_tier')
    assert r.prestige_tier == ""

def test_parse_score_response_extracts_prestige_tier():
    from shortlist.processors.scorer import parse_score_response
    response = '''{
        "fit_score": 85, "matched_track": "vp", "reasoning": "Strong.",
        "yellow_flags": [], "salary_estimate": "200k-300k USD",
        "salary_confidence": "medium", "corrected_title": "VP Engineering",
        "corrected_company": "Acme", "corrected_location": "Remote",
        "prestige_tier": "A"
    }'''
    result = parse_score_response(response)
    assert result is not None
    assert result.prestige_tier == "A"

def test_parse_score_response_rejects_invalid_prestige_tier():
    from shortlist.processors.scorer import parse_score_response
    response = '''{
        "fit_score": 75, "matched_track": "vp", "reasoning": "OK.",
        "yellow_flags": [], "salary_estimate": "150k USD",
        "salary_confidence": "low", "corrected_title": "Dir",
        "corrected_company": "Corp", "corrected_location": "Remote",
        "prestige_tier": "X"
    }'''
    result = parse_score_response(response)
    assert result is not None
    assert result.prestige_tier == ""

def test_parse_score_response_defaults_prestige_tier_when_missing():
    from shortlist.processors.scorer import parse_score_response
    response = '''{
        "fit_score": 75, "matched_track": "vp", "reasoning": "OK.",
        "yellow_flags": [], "salary_estimate": "150k USD",
        "salary_confidence": "low", "corrected_title": "Dir",
        "corrected_company": "Corp", "corrected_location": "Remote"
    }'''
    result = parse_score_response(response)
    assert result is not None
    assert result.prestige_tier == ""
```

2. Verify tests fail:
```bash
cd /Users/adam1/Code/shortlist
python3 -m pytest tests/test_scorer.py::test_score_result_has_prestige_tier tests/test_scorer.py::test_parse_score_response_extracts_prestige_tier tests/test_scorer.py::test_parse_score_response_rejects_invalid_prestige_tier tests/test_scorer.py::test_parse_score_response_defaults_prestige_tier_when_missing -q
```
Expected: FAIL

3. Implement — four changes to `shortlist/processors/scorer.py`:

**a) `ScoreResult` dataclass** — add field after `corrected_location`:
```python
prestige_tier: str = ""  # A / B / C / D — relative to candidate profile
```

**b) `SCORING_PROMPT_TEMPLATE`** — in the JSON output block, add after `corrected_location`:
```
    "prestige_tier": "<A|B|C|D — see below>"
```
Add this section immediately before "Return ONLY the JSON object":
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

**c) `SCORE_SCHEMA`** — add to properties:
```python
"prestige_tier": {"type": "STRING", "enum": ["A", "B", "C", "D"]},
```
Add `"prestige_tier"` to the `"required"` list.

**d) `parse_score_response`** — extract and validate:
```python
prestige_tier = data.get("prestige_tier", "")
if prestige_tier not in ("A", "B", "C", "D"):
    prestige_tier = ""
```
Pass `prestige_tier=prestige_tier` to `ScoreResult(...)`.

4. Verify tests pass:
```bash
python3 -m pytest tests/test_scorer.py::test_score_result_has_prestige_tier tests/test_scorer.py::test_parse_score_response_extracts_prestige_tier tests/test_scorer.py::test_parse_score_response_rejects_invalid_prestige_tier tests/test_scorer.py::test_parse_score_response_defaults_prestige_tier_when_missing -q
```
Expected: 4 passed

---

## Task 3: Pipeline — write prestige_tier via update_job

**File:** `shortlist/pipeline.py` (modify)
**Purpose:** Add `prestige_tier` to the `updates` dict in `run_pipeline_pg`'s scoring loop. `update_job` is a `**kwargs` passthrough — no change to pgdb.py needed.

### Steps

1. Write failing test in `tests/test_job_prestige.py` (new file):
```python
"""Tests for prestige_tier pipeline integration."""
import pytest


def test_update_job_writes_prestige_tier(pg_conn):
    """update_job can write prestige_tier — kwargs passthrough works."""
    from shortlist.collectors.base import RawJob
    from shortlist.pgdb import upsert_job, update_job, fetch_jobs

    job = RawJob(
        title="VP Engineering", company="Chainguard",
        url="https://test.example.com/vp1",
        description="desc", source="greenhouse", location="Remote",
    )
    upsert_job(pg_conn, job=job, user_id=1)
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE url = %s AND user_id = 1",
                    ("https://test.example.com/vp1",))
        row = cur.fetchone()
    job_id = row["id"]

    update_job(pg_conn, job_id, fit_score=88, prestige_tier="A")
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT prestige_tier FROM jobs WHERE id = %s", (job_id,))
        result = cur.fetchone()
    assert result["prestige_tier"] == "A"


def test_update_job_prestige_tier_null_when_not_set(pg_conn):
    """prestige_tier is NULL when job is inserted but not yet scored."""
    from shortlist.collectors.base import RawJob
    from shortlist.pgdb import upsert_job

    job = RawJob(
        title="Director", company="OMG",
        url="https://test.example.com/dir1",
        description="desc", source="greenhouse", location="Remote",
    )
    upsert_job(pg_conn, job=job, user_id=1)
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT prestige_tier FROM jobs WHERE url = %s AND user_id = 1",
                    ("https://test.example.com/dir1",))
        result = cur.fetchone()
    assert result["prestige_tier"] is None
```

2. Verify tests fail:
```bash
python3 -m pytest tests/test_job_prestige.py -q
```
Expected: FAIL (column doesn't exist yet — migration hasn't run locally)

   > Note: These tests require the migration to have run. If running against SQLite fake, they will fail differently. Skip and verify after migration runs in prod, or run against a local PG instance if available.

3. Implement in `shortlist/pipeline.py` — find the PG scoring loop (`_score_jobs` inner function, around line 638). Add to the `updates` dict:
```python
if score_result.prestige_tier:
    updates["prestige_tier"] = score_result.prestige_tier
```
Add after the `salary_confidence` line, before the `if run_id` block.

4. Verify the change looks right — read the modified section:
```bash
grep -A 20 '"salary_confidence"' /Users/adam1/Code/shortlist/shortlist/pipeline.py | head -25
```

5. Run full suite:
```bash
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass (pgdb tests use fake SQLite which won't have prestige_tier column — they should still pass since upsert_job doesn't touch prestige_tier)

---

## Task 4: API — model, schema, route

**Files:** `shortlist/api/models.py`, `shortlist/api/schemas.py`, `shortlist/api/routes/jobs.py` (modify)
**Purpose:** Expose `prestige_tier` in the API response.

### Steps

1. Write failing test in `tests/test_job_prestige.py`:
```python
def test_job_summary_has_prestige_tier():
    """JobSummary schema includes prestige_tier field (Pydantic v2)."""
    from shortlist.api.schemas import JobSummary
    assert 'prestige_tier' in JobSummary.model_fields
```

2. Verify fails:
```bash
python3 -m pytest tests/test_job_prestige.py::test_job_summary_has_prestige_tier -q
```
Expected: FAIL

3. Implement:

**`shortlist/api/models.py`** — add column to `Job` model after `closed_reason`:
```python
prestige_tier = Column(String(1), nullable=True)
```

**`shortlist/api/schemas.py`** — add field to `JobSummary` after `closed_reason`:
```python
prestige_tier: str | None = None
```

**`shortlist/api/routes/jobs.py`** — add to `_job_to_summary()` after `closed_reason=job.closed_reason`:
```python
prestige_tier=job.prestige_tier,
```

4. Verify:
```bash
python3 -m pytest tests/test_job_prestige.py::test_job_summary_has_prestige_tier -q
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass

---

## Task 5: Frontend — types + JobCard badge

**Files:** `web/src/lib/types.ts`, `web/src/components/JobCard.tsx` (modify)
**Purpose:** Show prestige tier as a small inert mono badge on the collapsed job card. Only A and B shown — C/D are noise at rest.

### Steps

1. **`web/src/lib/types.ts`** — add field to `Job` interface:
```typescript
prestige_tier: string | null;
```

2. **`web/src/components/JobCard.tsx`** — add tier badges in the badges row. Tier badge is a system badge (inert `<span>`, not a button). Add before the `{isClosed && ...}` badge:

```tsx
{job.prestige_tier === "A" && (
  <span className="font-mono text-[10px] uppercase tracking-widest text-emerald-600 border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 rounded">
    Tier A
  </span>
)}
{job.prestige_tier === "B" && (
  <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500 border border-gray-200 px-1.5 py-0.5 rounded">
    Tier B
  </span>
)}
```

3. Build check:
```bash
cd /Users/adam1/Code/shortlist/web && npm run build
```
Expected: clean build

---

## Task 6: Deploy

```bash
cd /Users/adam1/Code/shortlist
fly deploy --app shortlist-web
```

Verify migration ran:
```bash
fly logs --app shortlist-web --no-tail 2>/dev/null | grep -E "012|prestige"
```
Expected: `Running upgrade 011 -> 012`

After next pipeline run, verify new jobs get prestige_tier:
```bash
# In fly ssh console (base64-encode this script first)
python3 << 'EOF'
import os, psycopg2, psycopg2.extras
conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()
cur.execute("SELECT title, company, fit_score, prestige_tier FROM jobs WHERE user_id = 2 AND prestige_tier IS NOT NULL ORDER BY prestige_tier, fit_score DESC LIMIT 10")
for r in cur.fetchall():
    print(f"[{r['prestige_tier']}] [{r['fit_score']}] {r['title'][:40]} @ {r['company'][:25]}")
conn.close()
EOF
```

---

## Not in scope (future)

- Filter pill by tier in job list UI
- Sort by tier in the API
- Backfill prestige_tier on existing scored jobs (requires a re-score pass)
