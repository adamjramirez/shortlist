# Real Pipeline Progress

**Goal:** The user sees exactly what's happening at every moment — not a frozen progress bar.

## Current problem

`run_pipeline()` uses `_progress()` which prints to stderr. The worker calls it via `asyncio.to_thread(_run_sync)` — one blocking call with no way to observe progress until it returns.

## Design

### Shared progress dict (not per-event DB writes)

The sync pipeline thread writes to a plain `dict`. An async flush loop reads it every 2 seconds and pushes to PostgreSQL. The frontend polls every 3 seconds.

This means:
- ~15 DB writes per run (not 60+)
- Frontend always has data within 3s of reality
- No `run_coroutine_threadsafe` complexity
- Thread-safe: CPython dict key assignment is atomic for simple values

```
[sync thread]  →  writes to shared dict  →  [async flush loop every 2s]  →  DB
                                                                            ↑
[frontend polls every 3s]  ←────────────────────────────────────────────────┘
```

### Progress callback in pipeline

Add `on_progress` to `run_pipeline()`:

```python
def run_pipeline(
    config, project_root, skip_collect=False,
    on_progress: Callable[[dict], None] | None = None,
)
```

The callback receives a dict and the worker's implementation just does `shared_progress.update(data)`. The existing `_progress()` stderr output is preserved — the callback is additive.

### Scoring per-job callback

`score_jobs_parallel` gets `on_scored: Callable[[int, int], None] | None`. Called after each `as_completed` future. The pipeline wires it to `on_progress({"scored": done, "total": total})` which updates the shared dict. The flush loop picks it up within 2s.

### Progress shape

```python
{"phase": "collecting", "detail": "Scraping LinkedIn…", "collected": 420}
{"phase": "filtering", "detail": "Filtering 520 jobs…"}
{"phase": "filtering", "detail": "380 passed, 140 rejected", "passed": 380, "rejected": 140}
{"phase": "scoring", "detail": "Scoring 50 jobs…", "scored": 12, "total": 50}
{"phase": "enriching", "detail": "Researching 10 companies…", "enriched": 3, "total": 10}
{"phase": "tailoring", "detail": "Tailoring 8 resumes…"}
{"phase": "finishing", "detail": "Generating brief…"}
{"phase": "done", "jobs_found": 520, "scored": 42}
```

### What the user sees

```
🔄 Scraping HN…                        (spinner)
🔄 Scraping LinkedIn… — 420 collected   (spinner + count)
🔄 Filtering 520 jobs…                  (spinner)
🔄 Scoring jobs… (12/50)                (progress bar 24%)
🔄 Scoring jobs… (37/50)                (progress bar 74%)
🔄 Researching companies…               (spinner)
🔄 Tailoring resumes…                   (spinner)
✓  Complete — 42 matches found          (done)
```

Progress bar shows real % only during scoring (the longest phase). All other phases show spinner + text.

## Tasks

### Task 1: Add `on_progress` to `run_pipeline`

**File:** `shortlist/pipeline.py`

- Add `on_progress: Callable[[dict], None] | None = None` parameter
- Create helper: `_emit(on_progress, **kwargs)` — calls `_progress(detail)` AND `on_progress(kwargs)` if set
- Replace every `_progress()` call with `_emit()` that includes structured data
- 12 progress points:
  1. Per-source start: `phase=collecting, detail="Scraping {name}…"`
  2. Per-source done: `phase=collecting, detail="{name}: {n} jobs", collected=running_total`
  3. Collection summary: `phase=collecting, detail="Found {n} jobs total", collected=n`
  4. Filter start: `phase=filtering, detail="Filtering {n} jobs…"`
  5. Filter done: `phase=filtering, detail="{passed} passed, {rejected} rejected"`
  6. Scoring start: `phase=scoring, detail="Scoring {n} jobs…", scored=0, total=n`
  7. Per-scored (via `on_scored` → `on_progress`): `phase=scoring, scored=k, total=n`
  8. Scoring done: `phase=scoring, detail="{n} scored ≥60"`
  9. Enriching: `phase=enriching, detail="Researching {n} companies…"`
  10. Tailoring: `phase=tailoring, detail="Tailoring {n} resumes…"`
  11. Brief: `phase=finishing, detail="Generating brief…"`
  12. Done: `phase=done, jobs_found=N, scored=M`

**Verify:** `python -m shortlist run` still works (callback is optional, defaults to None).

### Task 2: Add `on_scored` to `score_jobs_parallel`

**File:** `shortlist/processors/scorer.py`

- Add `on_scored: Callable[[int, int], None] | None = None` parameter
- After each `as_completed` result: `if on_scored: on_scored(len(results), len(jobs))`
- Pipeline passes lambda that calls `_emit(on_progress, phase="scoring", scored=done, total=total)`

**Verify:** Existing scorer tests still pass.

### Task 3: Worker uses shared dict + flush loop

**File:** `shortlist/api/worker.py`

Replace the current single `asyncio.to_thread` call with:

```python
progress = {}  # shared mutable dict

def on_progress(data: dict):
    progress.update(data)  # atomic in CPython for simple keys

# Flush loop: push progress to DB every 2s while pipeline runs
async def flush_progress():
    while True:
        await asyncio.sleep(2)
        if progress:
            await update_run(progress=dict(progress))

flush_task = asyncio.create_task(flush_progress())
try:
    brief_path = await asyncio.to_thread(
        run_pipeline, pipeline_config, project_root, on_progress=on_progress,
    )
finally:
    flush_task.cancel()
    # One final flush
    if progress:
        await update_run(progress=dict(progress))
```

- No `run_coroutine_threadsafe` needed
- Flush loop auto-cancels when pipeline completes
- Final flush ensures last state is persisted

**Verify:** Tests still pass (worker is mocked in run tests). Deploy and test manually.

### Task 4: Clear stale runs

**File:** `shortlist/api/worker.py` or `shortlist/api/app.py`

- On app startup, mark any `pending`/`running` runs as `failed` with error "Server restarted"
- Prevents zombie runs that block new runs forever

**Verify:** After deploy, old stuck runs don't block "Run now".

### Task 5: Frontend (no changes needed)

`RunButton.tsx` already:
- Reads `progress.scored` / `progress.total` for progress bar width
- Reads `progress.detail` for label text  
- Shows spinner during non-scoring phases
- Shows `jobs_found` count

Just verify `npm run build` is clean after all backend changes.

## Execution order

1 → 2 → 3 → 4 → 5 (linear, each depends on previous)

## Kill criteria

- If CPython dict assignment turns out not to be safe enough (race), switch to `threading.Lock` — but this shouldn't happen for simple key overwrites.
- If 2s flush interval feels too slow for scoring, drop to 1s. But 2s is fine given 3s frontend poll.
