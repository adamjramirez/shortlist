# Plan: Systematic Job Expiry Detection

**Date:** 2026-04-07  
**Problem:** Jobs become stale quickly but sit in the inbox forever. Users waste time on roles that are already filled.  
**Goal:** Proactively detect and mark expired jobs in the background, continuously between pipeline runs.

---

## Two-Layer Approach

**Layer 1 — Proactive URL checks (scheduler background task)**  
Runs every scheduler tick (60s). Checks a small batch of jobs by hitting their URL directly. Fast, definitive signal. Covers LinkedIn, Greenhouse, Lever, Ashby.

**Layer 2 — Age/staleness pass (end of every pipeline run)**  
Catches anything the URL checker misses — HN (no URL signal), jobs not yet checked, network errors. Simple SQL, runs once per pipeline.

---

## Layer 1: Proactive URL Checker

### Signals by source (verified by manual testing)

| Source | Method | Proxy? | Signal |
|--------|--------|--------|--------|
| LinkedIn | `HEAD {url}` via `shortlist.http` | ✅ auto (PROXY_DOMAINS) | 404 = gone, 200 = active |
| Greenhouse | `HEAD {api_url}` if on greenhouse.io, else `HEAD {stored_url}` | ❌ | 404 = gone, 200 = active |
| Lever | `HEAD https://api.lever.co/v0/postings/{slug}/{job_id}` | ❌ | 404 = gone, 200 = active |
| Ashby | `GET {url}` + title check | ❌ | `<title>X @ Company` = active, `<title>Jobs` = expired |
| HN | ❌ No proactive check | — | Age/staleness only (Layer 2) |

**LinkedIn**: HEAD request. `shortlist.http` auto-routes through Decodo proxy. 404 = expired, 200 = active. Tested and confirmed.

**Greenhouse**: `absolute_url` from the Greenhouse API is often on custom company domains (e.g., `samsara.com/company/careers/roles/7644634?gh_jid=7644634`), not always `greenhouse.io`. Two paths:
- URL contains `greenhouse.io` → parse slug + job_id → HEAD `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}`
- Custom domain URL → HEAD the stored URL directly (company career pages return 404 for closed jobs)

**Lever**: Job URLs are always on `jobs.lever.co/{slug}/{job_id}`. Parse slug + job_id → HEAD `https://api.lever.co/v0/postings/{slug}/{job_id}`.

**Ashby**: Always returns HTTP 200 — even for fake job IDs. Signal is in the `<title>`: active jobs show `{title} @ {company}`, expired shows just `Jobs`. Fetch with a short timeout (5s); title is in the first ~200 bytes of any SSR response. No `Range` header needed.

**HN**: Items are never marked expired via HN's API. Firebase API returns `null` for deleted items only (extremely rare). Age/staleness is the only real signal — handled in Layer 2.

### Source identification — always use `sources_seen`

Identify which checker to dispatch by `sources_seen`, not URL patterns. URL patterns are unreliable (Greenhouse custom domains). `sources_seen` is authoritative — set by the collector at ingest time.

- `"linkedin" in sources_seen` → LinkedIn checker  
- `"greenhouse" in sources_seen` → Greenhouse checker (then inspect URL to choose API vs direct)  
- `"lever" in sources_seen` → Lever checker  
- `"ashby" in sources_seen` → Ashby checker  

In SQL, match JSON array elements exactly with quotes: `sources_seen::text LIKE '%"linkedin"%'` (not `%linkedin%`, which would false-positive on company names or job titles).

### All HTTP calls go through `shortlist.http`

`shortlist.http` already has rate limits for every relevant domain and auto-routes LinkedIn through the proxy. `expiry.py` uses `http.head()` and `http.get()` exclusively — no direct `requests`/`httpx`/`urllib` calls.

```
DOMAIN_LIMITS already registered:
  boards-api.greenhouse.io: 2.0s
  api.lever.co:             2.0s  
  jobs.ashbyhq.com:         2.0s
  www.linkedin.com:         3.0s (proxy auto-applied via PROXY_DOMAINS)
```

If `PROXY_URL` is not set (local dev), `shortlist.http` returns no proxy — LinkedIn checks return `None` (unknown) and are skipped. No error.

### Scheduler integration

The scheduler already ticks every 60 seconds. Add `check_expiry_batch()` to each tick:

```
Scheduler tick
  ├── reap_zombie_runs()          (existing)
  ├── trigger_due_users()         (existing)
  └── check_expiry_batch()        (NEW) — runs via asyncio.to_thread
```

Checks **20 jobs per tick** across all users. At 187 scored jobs, full cycle in ~10 minutes. Continuous thereafter.

**Priority order for checking:**
1. Jobs never checked (`expiry_checked_at IS NULL`)
2. Jobs checked longest ago (`expiry_checked_at ASC`)
3. Highest `fit_score` first within the batch

### New DB columns — Migration 011

```sql
ALTER TABLE jobs ADD COLUMN closed_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN closed_reason VARCHAR;
ALTER TABLE jobs ADD COLUMN expiry_checked_at TIMESTAMPTZ;

-- Backfill: existing user-toggled closes
UPDATE jobs SET closed_reason = 'user' WHERE is_closed = true;
```

`closed_reason` values: `'user'` | `'url_check'` | `'age_expired'` | `'last_seen_stale'`

### New `pgdb` functions

**`get_jobs_for_expiry_check(conn, limit=20) -> list[dict]`**

Cross-user query — this is a system-level operation, not per-user. One batch covers all users efficiently.

```sql
SELECT id, url, sources_seen, fit_score, expiry_checked_at
FROM jobs
WHERE is_closed = false
  AND fit_score >= 75
  AND (
    sources_seen::text LIKE '%"linkedin"%'
    OR sources_seen::text LIKE '%"greenhouse"%'
    OR sources_seen::text LIKE '%"lever"%'
    OR sources_seen::text LIKE '%"ashby"%'
  )
ORDER BY expiry_checked_at ASC NULLS FIRST, fit_score DESC
LIMIT {limit}
```

**`mark_expiry_checked(conn, job_id, is_closed, closed_reason=None)`**  
Always sets `expiry_checked_at = NOW()`. If `is_closed=True`: also sets `is_closed`, `closed_at`, `closed_reason`.

### New `shortlist/expiry.py` module

```python
def check_job_url(url: str, sources_seen: list[str]) -> bool | None:
    """
    Check if a job URL is still active.
    Returns True = active, False = expired, None = unknown (error/no proxy — skip, don't close).
    All HTTP calls go through shortlist.http.
    """
```

Dispatch logic (based on `sources_seen`, not URL):
```
"linkedin" in sources_seen  → http.head(url) → 404=False, 200=True, error=None
"greenhouse" in sources_seen →
    if "greenhouse.io" in url: parse slug+job_id → http.head(api_url)
    else: http.head(url)  ← custom domain (e.g. samsara.com)
    → 404=False, 200=True, error=None
"lever" in sources_seen     → parse slug+job_id → http.head(api_url) → 404=False, 200=True
"ashby" in sources_seen     → http.get(url, timeout=5) → check <title> → "@"=True, "Jobs"=False
```

**URL parsing helpers** (only needed for Greenhouse/Lever API endpoint construction):

```python
def _parse_greenhouse_api_url(url: str) -> str | None:
    """
    Returns API URL if job is on greenhouse.io, else None (use stored URL directly).
    Handles:
      https://job-boards.greenhouse.io/{slug}/jobs/{job_id}
      https://boards.greenhouse.io/{slug}/jobs/{job_id}
    Returns: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}
    """

def _parse_lever_api_url(url: str) -> str | None:
    """
    https://jobs.lever.co/{slug}/{job_id}
    Returns: https://api.lever.co/v0/postings/{slug}/{job_id}
    """
```

**`check_expiry_batch(db_url, limit=20) -> dict`**  
Opens its own DB connection (closed in `finally`). Calls `get_jobs_for_expiry_check`, runs `check_job_url` for each sequentially (rate limiting is in `shortlist.http`), calls `mark_expiry_checked`. Returns `{checked: N, closed: N, errors: N}`.

```python
def check_expiry_batch(db_url: str, limit: int = 20) -> dict:
    conn = pgdb.get_pg_connection(db_url)
    try:
        jobs = pgdb.get_jobs_for_expiry_check(conn, limit=limit)
        checked = closed = errors = 0
        for job in jobs:
            sources = job["sources_seen"] if isinstance(job["sources_seen"], list) else json.loads(job["sources_seen"])
            try:
                result = check_job_url(job["url"], sources)
                if result is None:
                    errors += 1
                    pgdb.mark_expiry_checked(conn, job["id"], is_closed=False)
                else:
                    pgdb.mark_expiry_checked(conn, job["id"], is_closed=not result,
                                             closed_reason="url_check" if not result else None)
                    if not result:
                        closed += 1
                checked += 1
            except Exception as e:
                logger.warning(f"Expiry check failed for job {job['id']}: {e}")
                errors += 1
        conn.commit()
        return {"checked": checked, "closed": closed, "errors": errors}
    finally:
        conn.close()
```

### Scheduler change (`scheduler.py`)

```python
async def run_scheduler() -> None:
    ...
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        try:
            async with async_session() as session:
                async with session.begin():
                    await reap_zombie_runs(session)
                    pending = await trigger_due_users(session)

            for meta in pending:
                asyncio.create_task(_fire_and_update(...))

            # Proactive job expiry check
            result = await asyncio.to_thread(check_expiry_batch, db_url)
            if result["closed"] > 0:
                logger.info("Expiry check: %d closed, %d checked", result["closed"], result["checked"])

        except Exception:
            logger.exception("Scheduler tick failed")
```

---

## Layer 2: Pipeline Staleness Pass

Runs at the end of every `run_pipeline_pg()`. Catches HN and anything the URL checker hasn't gotten to yet. All source identification uses quoted JSON matching (`'%"hn"%'` not `'%hn%'`).

### New `pgdb.mark_stale_jobs(conn, user_id, run_started_at) -> int`

Five passes. Each skips `closed_reason = 'user'`. Returns total rows affected.

**Pass 1 — ATS staleness** (Greenhouse/Lever/Ashby not seen in 3 days):
```sql
UPDATE jobs SET is_closed=true, closed_at=NOW(), closed_reason='last_seen_stale'
WHERE user_id=%s AND is_closed=false
  AND (sources_seen::text LIKE '%"greenhouse"%'
    OR sources_seen::text LIKE '%"lever"%'
    OR sources_seen::text LIKE '%"ashby"%')
  AND last_seen < %s::timestamptz - INTERVAL '3 days'
  AND (closed_reason IS NULL OR closed_reason != 'user')
```

**Pass 2 — LinkedIn age** (posted > 30 days ago):
```sql
UPDATE jobs SET is_closed=true, closed_at=NOW(), closed_reason='age_expired'
WHERE user_id=%s AND is_closed=false
  AND sources_seen::text LIKE '%"linkedin"%'
  AND posted_at IS NOT NULL
  AND posted_at < NOW() - INTERVAL '30 days'
  AND (closed_reason IS NULL OR closed_reason != 'user')
```

**Pass 3 — HN age** (posted > 45 days ago):
```sql
UPDATE jobs SET is_closed=true, closed_at=NOW(), closed_reason='age_expired'
WHERE user_id=%s AND is_closed=false
  AND sources_seen::text LIKE '%"hn"%'
  AND posted_at IS NOT NULL
  AND posted_at < NOW() - INTERVAL '45 days'
  AND (closed_reason IS NULL OR closed_reason != 'user')
```

**Pass 4 — HN with no `posted_at`** (fallback via `last_seen`):
```sql
UPDATE jobs SET is_closed=true, closed_at=NOW(), closed_reason='last_seen_stale'
WHERE user_id=%s AND is_closed=false
  AND sources_seen::text LIKE '%"hn"%'
  AND posted_at IS NULL
  AND last_seen < NOW() - INTERVAL '45 days'
  AND (closed_reason IS NULL OR closed_reason != 'user')
```

**Pass 5 — Generic staleness** (all other sources, not seen in 7 days):
```sql
UPDATE jobs SET is_closed=true, closed_at=NOW(), closed_reason='last_seen_stale'
WHERE user_id=%s AND is_closed=false
  AND sources_seen::text NOT LIKE '%"greenhouse"%'
  AND sources_seen::text NOT LIKE '%"lever"%'
  AND sources_seen::text NOT LIKE '%"ashby"%'
  AND sources_seen::text NOT LIKE '%"linkedin"%'
  AND sources_seen::text NOT LIKE '%"hn"%'
  AND last_seen < NOW() - INTERVAL '7 days'
  AND (closed_reason IS NULL OR closed_reason != 'user')
```

### Pipeline integration

Capture `run_started_at = datetime.now(timezone.utc)` at the very top of `run_pipeline_pg`. At the end, before `conn.close()`:

```python
closed_count = pgdb.mark_stale_jobs(conn, user_id, run_started_at)
if closed_count:
    logger.info(f"Marked {closed_count} stale jobs as closed")
    _emit(on_progress, f"Closed {closed_count} expired listings",
          phase="done", detail=f"Closed {closed_count} expired listings")
conn.commit()
```

Include in return dict: `"closed_count": closed_count`.

---

## Re-open on Re-appearance

In `upsert_job`, on conflict (existing job) update branch, add:
```sql
UPDATE jobs SET last_seen=%s, sources_seen=%s, posted_at=COALESCE(posted_at, %s),
    is_closed = CASE WHEN closed_reason = 'user' THEN is_closed ELSE false END,
    closed_at = CASE WHEN closed_reason = 'user' THEN closed_at ELSE NULL END,
    closed_reason = CASE WHEN closed_reason = 'user' THEN closed_reason ELSE NULL END
WHERE id=%s
```

Auto-closed jobs (`url_check`, `age_expired`, `last_seen_stale`) reset if the source sees them again. User-closed jobs (`user`) never reset.

---

## Status Endpoint Update

When user toggles `is_closed` via `PUT /api/jobs/{id}/status` with `"closed"`:
```python
if req.status == "closed":
    job.is_closed = not job.is_closed
    if job.is_closed:
        job.closed_reason = "user"
        job.closed_at = datetime.now(timezone.utc)
    else:
        job.closed_reason = None
        job.closed_at = None
```

---

## API Changes

**Schema** — add to `JobSummary`:
```python
closed_reason: str | None = None
```

**Jobs list** — filter closed from Inbox and unfiltered view:
```python
if user_status == "new" or user_status is None:
    filters.append(Job.is_closed == False)
```
Saved and Applied tabs keep showing closed jobs — user may have applied before it closed.

**Counts** — exclude closed from `new` count:
```python
func.count().filter(Job.user_status.is_(None), Job.is_closed == False).label("new"),
```

---

## Frontend Changes

Minimal — closed badge already exists. Two small additions:

1. **`closed_reason` sub-text** on closed badge in expanded view:
   - `url_check` → "No longer listed"
   - `age_expired` → "Listing expired"
   - `last_seen_stale` → "Not seen recently"
   - `user` → (no sub-text)

2. **Run completion message** — if `closed_count > 0`: "Found X matches · Y expired listings removed"

---

## Files Changed

| File | Change |
|------|--------|
| `alembic/versions/011_job_expiry.py` | Add `closed_at`, `closed_reason`, `expiry_checked_at`; backfill `closed_reason='user'` |
| `shortlist/expiry.py` | New: `check_job_url()`, `_parse_greenhouse_api_url()`, `_parse_lever_api_url()`, `check_expiry_batch()` |
| `shortlist/pgdb.py` | `get_jobs_for_expiry_check()`, `mark_expiry_checked()`, `mark_stale_jobs()`, update `upsert_job` |
| `shortlist/pipeline.py` | Capture `run_started_at`, call `mark_stale_jobs()`, include `closed_count` in return dict |
| `shortlist/scheduler.py` | Call `check_expiry_batch()` each tick via `asyncio.to_thread` |
| `shortlist/api/routes/jobs.py` | Set `closed_reason='user'` on toggle, filter closed from inbox |
| `shortlist/api/schemas.py` | Add `closed_reason` to `JobSummary` |
| `web/src/components/JobCard.tsx` | `closed_reason` sub-text, run completion message |
| `tests/test_job_expiry.py` | Full test suite |

---

## Tests

| Test | Covers |
|------|--------|
| `test_check_linkedin_404` | HEAD 404 → returns False |
| `test_check_linkedin_200` | HEAD 200 → returns True |
| `test_check_linkedin_no_proxy` | PROXY_URL unset → returns None (skip) |
| `test_check_linkedin_error` | Network error → returns None |
| `test_check_greenhouse_native_404` | greenhouse.io URL, API 404 → False |
| `test_check_greenhouse_native_200` | greenhouse.io URL, API 200 → True |
| `test_check_greenhouse_custom_domain` | samsara.com URL → HEAD stored URL → 404 = False |
| `test_check_lever_404` | API 404 → False |
| `test_check_lever_200` | API 200 → True |
| `test_check_ashby_active` | Title contains `@` → True |
| `test_check_ashby_expired` | Title is `Jobs` → False |
| `test_parse_greenhouse_api_url_native` | Extracts slug+job_id, returns API URL |
| `test_parse_greenhouse_api_url_custom` | Custom domain → returns None |
| `test_parse_lever_api_url` | Extracts slug+job_id |
| `test_mark_expiry_checked_closed` | Sets `is_closed`, `closed_at`, `closed_reason`, `expiry_checked_at` |
| `test_mark_expiry_checked_alive` | Only sets `expiry_checked_at`, leaves `is_closed=false` |
| `test_mark_expiry_checked_error` | None result → sets `expiry_checked_at` only, job stays open |
| `test_get_jobs_for_expiry_check` | Returns eligible jobs ordered by `expiry_checked_at ASC NULLS FIRST` |
| `test_get_jobs_skips_already_closed` | `is_closed=true` jobs not returned |
| `test_check_expiry_batch_closes_connection` | Connection closed even on exception |
| `test_mark_stale_ats_3_days` | Greenhouse/Lever/Ashby not seen 3+ days → closed |
| `test_mark_stale_ats_under_threshold` | Not seen 2 days → still open |
| `test_mark_stale_linkedin_30_days` | LinkedIn `posted_at` 30+ days → closed |
| `test_mark_stale_linkedin_29_days` | 29 days → still open |
| `test_mark_stale_hn_with_posted_at` | HN `posted_at` 45+ days → closed |
| `test_mark_stale_hn_null_posted_at` | HN `posted_at=NULL`, `last_seen` 45+ days → closed |
| `test_mark_stale_hn_null_recent` | HN `posted_at=NULL`, `last_seen` recent → still open |
| `test_mark_stale_generic_7_days` | Other source, 7+ days stale → closed |
| `test_user_closed_protected` | `closed_reason='user'` not overridden by any pass |
| `test_upsert_reopens_auto_closed` | Auto-closed job reappears → `is_closed=false`, reason=None |
| `test_upsert_preserves_user_closed` | User-closed job reappears → stays closed |
| `test_pipeline_includes_closed_count` | Pipeline return dict has `closed_count` |

---

## Execution Order

1. Migration 011 — `closed_at`, `closed_reason`, `expiry_checked_at`, backfill
2. `shortlist/expiry.py` — TDD: tests first, then `check_job_url()` + helpers + `check_expiry_batch()`
3. `pgdb` additions — `get_jobs_for_expiry_check()`, `mark_expiry_checked()`, `mark_stale_jobs()`, update `upsert_job`
4. Pipeline integration — capture `run_started_at`, call `mark_stale_jobs()` at end
5. Scheduler integration — `check_expiry_batch()` per tick via `asyncio.to_thread`
6. Status endpoint — set `closed_reason='user'` on toggle
7. API schema + route — expose `closed_reason`, filter inbox, fix counts
8. Frontend — badge sub-text + run completion message
9. Deploy + monitor

---

## Decisions Made

- **Source identification always via `sources_seen`** — not URL patterns. URL LIKE is fragile; Greenhouse `absolute_url` is often on custom company domains (`samsara.com`, etc.). `sources_seen` is set by the collector and is authoritative.
- **All HTTP via `shortlist.http`** — rate limits already registered for all four domains, proxy auto-applied for LinkedIn.
- **Greenhouse two-path check** — greenhouse.io URLs get the clean API endpoint; custom domain URLs get a HEAD on the stored URL directly.
- **No `Range` header for Ashby** — SSR servers don't honour byte-range on HTML. Short timeout (5s) is sufficient; title is always in the first response chunk.
- **DB connection owned by `check_expiry_batch`** — opened at start, closed in `finally`. Scheduler calls via `asyncio.to_thread`, no connection shared across async boundary.
- **HN needs two passes** — Pass 3 catches HN with `posted_at`, Pass 4 catches HN where `posted_at IS NULL` (common; our DB confirmed all current HN jobs have null `posted_at`).
- **`None` from `check_job_url` = skip** — network errors, missing proxy, unexpected responses do not mark a job closed. Always err toward keeping open.
- **Proactive checker is cross-user** — `get_jobs_for_expiry_check` queries all users. Efficient: one batch of 20 covers the whole system.
- **Saved/Applied keep showing closed** — a job you applied to that later closed is useful history. Only Inbox hides closed jobs.
- **`closed_reason='user'` is sacred** — never overridden by proactive checks, staleness passes, or re-appearance in a feed.

## Kill Criteria

- If `check_expiry_batch` closes >10% of a user's scored jobs in one cycle → threshold too aggressive, investigate before adjusting
- If Decodo proxy blocks expiry HEAD checks (rate limit or ban) → fall back to LinkedIn age-based only, remove LinkedIn from `get_jobs_for_expiry_check`
- If Ashby changes their title format → tests catch it; fall back to `last_seen` staleness
