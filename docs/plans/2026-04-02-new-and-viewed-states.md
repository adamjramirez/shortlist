# Plan: New + Viewed Job States

## Problem

Users can't distinguish two things:
1. **Which run did this job come from?** — "New" currently means `brief_count == 0`, which only increments when a *subsequent pipeline run* completes. Not meaningful.
2. **Have I looked at this job?** — No tracking at all. Expanding a card leaves no trace.

## Design

Two independent visual signals, email-inbox pattern:

| State | Visual treatment | Data |
|-------|-----------------|------|
| **New** (from latest run) | `New` pill (emerald, existing style) | `run_id` on Job matches user's latest non-failed run |
| **Unread** (never expanded) | **Bold title, darker text** | `viewed_at IS NULL` |
| **Read** (expanded at least once) | Normal weight, muted text | `viewed_at` has timestamp |

### How they combine

| Scenario | Title | Company/meta | Badge | Example |
|----------|-------|-------------|-------|---------|
| New + Unread | `font-semibold text-gray-900` | `text-gray-700` | `New` | Just found this run, haven't clicked |
| New + Read | `font-normal text-gray-600` | `text-gray-500` | `New` | Clicked it this run |
| Old + Unread | `font-semibold text-gray-900` | `text-gray-700` | — | From a previous run, somehow missed |
| Old + Read | `font-normal text-gray-600` | `text-gray-500` | — | Reviewed previously |

The read/unread treatment also applies to:
- Score number: `font-bold` → `font-semibold`
- Score reasoning one-liner: `text-gray-600` → `text-gray-400`
- Condensed intel: `text-gray-400` → `text-gray-300`

### Tab rename (display only)

| Current label | New label | Wire format | Behavior |
|---------------|-----------|-------------|----------|
| `New (14)` | `Inbox (14)` | `?user_status=new` (unchanged) | Filters `user_status IS NULL` (unchanged) |
| Summary: `14 new` | `14 to review` | `counts.new` (unchanged) | Same query |

"Inbox" = untriaged jobs. The `New` pill on individual cards means "from latest run." These are orthogonal. Wire format stays `new` — it's a display-only rename.

### What `brief_count` becomes

Deprecated. We stop incrementing it in the worker. The `viewed_at` column replaces its intent. No migration to drop it — just stop using it.

### Re-scored jobs become unread again

When a job is re-found and re-scored in a new run, its score/reasoning may have changed. We reset `viewed_at = None` and update `run_id` during scoring. The job becomes "New + Unread" again — fresh content deserves fresh eyes.

## Changes

### Task 1: Migration — add `viewed_at` and `run_id` columns

**File:** `shortlist/api/models.py` (modify)
- Add `viewed_at = Column(DateTime(timezone=True), nullable=True)` to Job
- Add `run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)` to Job

**File:** `alembic/versions/008_add_viewed_at_and_run_id.py` (create)
- Add `viewed_at` column (nullable datetime)
- Add `run_id` column (nullable integer, FK to runs.id)
- Add index on `(user_id, run_id)` for the "latest run" query

### Task 2: Set `run_id` during scoring + stop incrementing `brief_count`

**File:** `shortlist/pipeline.py` (modify)
- `run_pipeline_pg()`: accept `run_id` param
- `_score_filtered()`: add `run_id` and `viewed_at=None` to the updates dict when scoring a job. This means re-scored jobs get the new run_id and become unread.

No changes to `pgdb.py` — scoring already uses `pgdb.update_job(conn, row_id, **updates)`.

**File:** `shortlist/api/worker.py` (modify)
- Pass `run_id` into `run_pipeline_pg()` call
- Remove the `brief_count` increment block at end of run

### Task 3: Update job serialization — `is_new` based on `run_id`

**File:** `shortlist/api/routes/jobs.py` (modify)
- `list_jobs()`: query latest run_id once: `SELECT MAX(id) FROM runs WHERE user_id = :uid AND status NOT IN ('failed', 'cancelled')`
- `_job_to_summary()`: accept `latest_run_id` param, compute `is_new = (job.run_id == latest_run_id)` instead of `brief_count == 0`
- Add `viewed_at` to JobSummary serialization
- `get_job()`: also needs `latest_run_id` for the detail endpoint

**File:** `shortlist/api/schemas.py` (modify)
- Add `viewed_at: str | None = None` to JobSummary
- Everything else stays the same (`is_new` field name preserved, `JobStatusCounts.new` preserved)

### Task 4: Add `PATCH /api/jobs/{job_id}/view` endpoint

**File:** `shortlist/api/routes/jobs.py` (modify)
- New endpoint: sets `viewed_at = now()` if not already set (idempotent)
- Returns 204 No Content (fire-and-forget from frontend)

### Task 5: Frontend — mark viewed on expand, read/unread styling

**File:** `web/src/lib/api.ts` (modify)
- Add `markViewed(jobId: number)` — PATCH, fire-and-forget (no await)

**File:** `web/src/lib/types.ts` (modify)
- Add `viewed_at: string | null` to JobSummary type

**File:** `web/src/components/JobCard.tsx` (modify)
- In `handleExpand()`: call `api.markViewed(job.id)` fire-and-forget, set local `isViewed` state immediately
- Derive `isUnread = !job.viewed_at && !isViewed` (local state overrides server state)
- Apply read/unread classes:

  | Element | Unread | Read |
  |---------|--------|------|
  | Title | `font-semibold text-gray-900` | `font-normal text-gray-600` |
  | Company/location/age | `text-gray-700` | `text-gray-500` |
  | Score | `font-bold` | `font-semibold` |
  | Score reasoning | `text-gray-600` | `text-gray-400` |
  | Condensed intel | `text-gray-400` | `text-gray-300` |

- Keep `New` pill exactly as-is (emerald bg, same style)

### Task 6: Frontend — rename "New" tab label to "Inbox"

**File:** `web/src/app/page.tsx` (modify)
- Change pill label: `"New"` → `"Inbox"` (display only)
- Change summary: `"{n} new"` → `"{n} to review"`
- Wire format unchanged: still sends `?user_status=new`, still reads `counts.new`

### Task 7: Tests

**New tests:**
- `test_viewed_at_set_on_view` — PATCH endpoint sets timestamp, second call is idempotent
- `test_is_new_based_on_run_id` — job from latest run = new, older run = not new
- `test_is_new_no_runs` — graceful when no completed runs (all jobs `is_new=False`)
- `test_is_new_running_run` — job scored in an in-progress run still shows as new
- `test_viewed_at_in_job_response` — field appears in list and detail responses

**Existing tests to update:**
- `test_list_jobs_counts` — key is still `new`, just verify it still works
- `test_list_jobs_filter_new` — still uses `?user_status=new`, verify unchanged
- `test_job_closed.py` — `is_new=False` assertions still valid (no run_id = not new)

## Edge Cases

1. **No runs yet** — `latest_run_id` is None → `job.run_id (NULL) == None` could match. Guard: if `latest_run_id is None`, all jobs are `is_new=False`.
2. **Run in progress** — Jobs being scored mid-run get the new `run_id`. Query uses `MAX(id) WHERE status NOT IN ('failed', 'cancelled')`, which includes 'running'. They show as New. Correct.
3. **Job re-scored in new run** — `run_id` updates, `viewed_at` resets to NULL. Becomes New + Unread. Correct — content changed.
4. **Job found but not re-scored** — `upsert_job` only updates `last_seen`/`sources_seen`. `run_id` stays from previous scoring. Job stays Old. Correct — nothing changed for the user.
5. **User never expands a card** — `viewed_at` stays NULL, title stays bold forever. Correct.
6. **Race: expand while pipeline running** — `viewed_at` set via API endpoint, `run_id` set via pipeline thread. Different rows/columns, no conflict.
7. **Jobs from before migration** — `run_id` is NULL, `viewed_at` is NULL. Shows as Old + Unread. After user expands, becomes Old + Read. Reasonable — we don't know when they were scored, but we can track views going forward.

## Risks

- **Subtle styling** — if `font-normal text-gray-600` vs `font-semibold text-gray-900` doesn't register, we can go harder (opacity, background tint). Start subtle, adjust.
- **Fire-and-forget PATCH fails silently** — if the viewed call fails, the card looks read locally but server still thinks unread. On refresh it'll be bold again. Acceptable for v1.

## Kill Criteria

UI clarity improvement, not speculative. No kill criteria needed — if the visual treatment feels wrong we adjust styling, not the data model.
