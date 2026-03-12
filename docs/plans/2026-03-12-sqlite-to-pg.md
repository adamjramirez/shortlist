# Plan: Migrate Pipeline from SQLite to Direct PostgreSQL

## Problem
The pipeline (`pipeline.py`) writes to a temporary SQLite DB, then the worker (`worker.py`) copies results to PostgreSQL. This adds:
- A fragile copy step with cross-thread SQLite issues
- ~5s delay before results appear in the UI
- Dual schemas to maintain (SQLite in `db.py`, SQLAlchemy in `api/models.py`)
- SQLite's single-writer blocks parallelism

## Goal
Pipeline writes directly to PostgreSQL. No SQLite. Results appear in the UI immediately.

## Architecture Decision
**Use sync `psycopg2` connection in the pipeline thread** (not async SQLAlchemy).

Why:
- Pipeline runs in `asyncio.to_thread()` — it's a sync context
- Async SQLAlchemy from a sync thread causes the same issues as httpx/urllib
- `psycopg2` is battle-tested for sync PG access
- Raw SQL stays similar to current SQLite SQL (minimal rewrite)
- PG handles concurrent writes, so future parallelism is unblocked

## CLI Decision
**Freeze SQLite for CLI. Don't maintain both.**

The CLI (`cli.py`, `brief.py`) keeps its SQLite path as-is. It's a separate product surface that works. We don't touch it, don't update it, don't try to share a DB layer with the web pipeline. If CLI ever needs PG, that's a future decision.

The web pipeline gets its own PG-native code path. No shared abstraction between CLI and web.

## Scope

### Files to change

| File | Change | Size |
|------|--------|------|
| `requirements.txt` | Add `psycopg2-binary` | Trivial |
| `shortlist/pipeline.py` | Accept PG conn + `user_id`, adapt all 35 queries, remove `on_jobs_ready`, batch scorer updates | **Large** |
| `shortlist/api/worker.py` | Remove `_copy_rows_to_pg`, `on_jobs_ready`, final copy block, temp dir; pass PG conn to pipeline | **Large** (net deletion) |
| `shortlist/processors/enricher.py` | 3 functions: adapt `?` → `%s`, add `user_id` | Small |
| `shortlist/collectors/nextplay.py` | `probe_cache` reads/writes: adapt SQL | Small |
| `shortlist/api/models.py` | Rename `jobs_web` → `jobs`, `companies_web` → `companies` | Small |
| `alembic/versions/` | New migration: rename tables | Small |
| Tests | Reuse existing PG test fixture from `tests/api/conftest.py` | Medium |

### Files NOT changed (frozen)
- `shortlist/db.py` — SQLite schema + helpers, CLI only
- `shortlist/brief.py` — reads from local SQLite, CLI only
- `shortlist/cli.py` — uses SQLite via `db.py`, CLI only

### SQL syntax changes (SQLite → PostgreSQL)

| SQLite | PostgreSQL |
|--------|-----------|
| `INTEGER PRIMARY KEY` | `SERIAL PRIMARY KEY` |
| `DATETIME DEFAULT CURRENT_TIMESTAMP` | `TIMESTAMP DEFAULT NOW()` |
| `?` parameter | `%s` parameter |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `json_extract()` | `->` / `->>` operators |
| `GROUP_CONCAT()` | `STRING_AGG()` |
| `conn.row_factory = sqlite3.Row` | `cursor_factory=psycopg2.extras.RealDictCursor` |

### What gets deleted
- `worker.py`: `_copy_rows_to_pg()` (~50 lines)
- `worker.py`: `on_jobs_ready` callback + SQLite row→dict conversion (~20 lines)
- `worker.py`: final SQLite copy block (~15 lines)
- `worker.py`: `tempfile.TemporaryDirectory` + SQLite import
- `pipeline.py`: `on_jobs_ready` parameter and `_notify_jobs_ready()` (~10 lines)

### Queries requiring `user_id` scoping

Every query in `pipeline.py` that touches `jobs` or `companies` must add `AND user_id = %s`. Full list:

| Function/location | Query | Notes |
|---|---|---|
| `_filter_new_jobs()` | `SELECT * FROM jobs WHERE status = 'new'` | Add `AND user_id = %s` |
| `_filter_new_jobs()` | `UPDATE jobs SET status = 'filtered' WHERE id = ?` | Safe (by id), but verify id belongs to user |
| `_filter_new_jobs()` | `UPDATE jobs SET status = 'rejected', reject_reason = ? WHERE id = ?` | Same |
| `_fetch_descriptions()` | `SELECT id, url FROM jobs WHERE status = 'filtered' AND description IS NULL ...` | Add `AND user_id = %s` |
| `_fetch_descriptions()` | `UPDATE jobs SET description = ? WHERE id = ?` | By id, safe |
| `_score_filtered()` | `SELECT * FROM jobs WHERE status = 'filtered' ORDER BY ...` | Add `AND user_id = %s` |
| `_score_filtered()` | `UPDATE jobs SET status = ?, fit_score = ?, ... WHERE id = ?` | By id, safe |
| scored_count | `SELECT COUNT(*) FROM jobs WHERE status = 'scored'` | Add `AND user_id = %s` |
| enrichment loop | `SELECT * FROM jobs WHERE status = 'scored' AND enrichment IS NULL ...` | Add `AND user_id = %s` |
| enrichment update | `UPDATE jobs SET enrichment = ?, ... WHERE id = ?` | By id, safe |
| rescore update | `UPDATE jobs SET fit_score = ?, ... WHERE id = ?` | By id, safe |
| companies_to_probe | `SELECT ... FROM companies WHERE domain IS NOT NULL ...` | Add `AND user_id = %s` |
| company updates | `UPDATE companies SET ats_platform = ? ... WHERE id = ?` | By id, safe |
| tailoring loop | `SELECT * FROM jobs WHERE status = 'scored' ...` | Add `AND user_id = %s` |
| tailoring update | `UPDATE jobs SET tailored_resume_path = ? WHERE id = ?` | By id, safe |
| run_logs insert | `INSERT INTO run_logs ...` | Add `user_id` column or remove (use `runs` table) |
| `upsert_job()` | `SELECT ... FROM jobs WHERE description_hash = ?` | Add `AND user_id = %s` |
| `upsert_job()` | `INSERT INTO jobs ...` | Add `user_id` value |
| `_log_source_run()` | `INSERT INTO sources/source_runs ...` | Add `user_id` or scope differently |
| enricher: `get_cached_enrichment()` | `SELECT ... FROM companies WHERE name_normalized = ?` | Add `AND user_id = %s` |
| enricher: `cache_enrichment()` | `INSERT INTO companies ...` | Add `user_id` value |
| nextplay: probe cache | `SELECT/INSERT FROM probe_cache ...` | Probe cache is global (not per-user), keep as-is or move to PG shared table |

### Race condition note
`_filter_new_jobs()` and `_score_filtered()` query by `status` column. Currently safe because processing runs on a single thread (main thread processes results sequentially from the queue). If we later parallelize the processing step, these queries would need `source` scoping or row-level locking. **Not a problem now — just don't parallelize processing without addressing this.**

## Implementation Steps

### Step 0: Spike test (do first, 10 minutes)
Confirm `psycopg2` works from inside `asyncio.to_thread()` on Fly.io.

```python
# Add to debug endpoint temporarily
import psycopg2
def test_pg_sync():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    conn.close()
    return {"result": result[0]}
```

Deploy, hit endpoint, confirm it returns `{"result": 1}`. If this crashes/hangs → stop, keep SQLite.

**Kill criterion met if:** psycopg2 hangs or crashes from asyncio.to_thread on Fly shared-cpu.

### Step 1: Table rename migration (Alembic)
Rename tables before changing any code. This is safe because:
- Alembic runs on deploy before the app starts
- Old code doesn't exist yet (we haven't changed it)

```python
# alembic/versions/NNN_rename_tables.py
def upgrade():
    op.rename_table('jobs_web', 'jobs')
    op.rename_table('companies_web', 'companies')

def downgrade():
    op.rename_table('jobs', 'jobs_web')
    op.rename_table('companies', 'companies_web')
```

Update `api/models.py`:
- `Job.__tablename__ = "jobs"`
- `Company.__tablename__ = "companies"`

**Verify:** Deploy, confirm app works with renamed tables, existing data intact.

### Step 2: DB layer for pipeline
Add `psycopg2-binary` to `requirements.txt`.

Create `shortlist/pgdb.py` (new file, separate from `db.py`):
- `get_pg_connection(db_url: str)` → `psycopg2.connection` with `RealDictCursor`
- `upsert_job(conn, user_id, job)` → PG-native upsert with `ON CONFLICT (user_id, description_hash)`
- `_log_source_run(conn, ...)` → PG-native insert

Keep it simple: functions that take a connection + user_id, return dicts. No ORM. No classes.

**Verify:** Unit test `upsert_job` and `_log_source_run` against test PG.

### Step 3: Pipeline migration (`shortlist/pipeline.py`)
- New entry point: `run_pipeline_pg(config, db_url, user_id, ...)` alongside existing `run_pipeline()`
- Uses `pgdb.get_pg_connection()` instead of `init_db()`
- All queries adapted: `?` → `%s`, add `user_id` scoping per table above
- Batch scorer updates: collect all `(status, fit_score, ..., id)` tuples, execute single `executemany()`
- Remove `on_jobs_ready` parameter — results are already in PG
- Remove `_notify_jobs_ready()` function
- Keep `on_progress` and `cancel_event` unchanged

**Verify:** Run full pipeline against test PG, confirm:
- Jobs appear in `jobs` table with correct `user_id`
- Enrichment data populates
- No SQLite files created
- Existing `run_pipeline()` still works for CLI

### Step 4: Worker simplification (`shortlist/api/worker.py`)
- Delete `_copy_rows_to_pg()` function entirely
- Delete `on_jobs_ready` callback and SQLite row conversion
- Delete final SQLite copy block
- Delete `tempfile.TemporaryDirectory`
- Call `run_pipeline_pg(config, db_url, user_id, ...)` instead of `run_pipeline()`
- Progress flush loop stays unchanged (async SQLAlchemy for `runs` table)
- Final `update_run(status="completed", ...)` uses count from PG directly

**Verify:** End-to-end on Fly: start run → HN results appear on dashboard in ~30s → NextPlay/LinkedIn results appear as they complete → enrichment runs → done.

### Step 5: Enricher + NextPlay
- `enricher.py`: `get_cached_enrichment(conn, user_id, company)` and `cache_enrichment(conn, user_id, ...)` — adapt `?` → `%s`, add `user_id`
- `nextplay.py`: probe cache — decide: move to PG shared table (no user_id, it's global), or keep as a simple dict cache in memory for the run duration

**Verify:** Enrichment populates company intel on scored jobs. NextPlay probe cache avoids redundant ATS probes.

### Step 6: Test updates
- Pipeline tests: use test PG from `tests/api/conftest.py` fixture
- Create `sync_pg_connection` fixture that gives a `psycopg2` connection to the test DB
- Remove any SQLite temp file cleanup from pipeline tests
- Verify scorer, enricher, filter tests work against PG

**Verify:** `pytest tests/ -x` — all pass.

### Step 7: Cleanup
- Remove dead imports (`sqlite3`, `tempfile`) from `pipeline.py` and `worker.py`
- Remove `on_jobs_ready` from `run_pipeline()` signature (or keep for CLI compat)
- Update `docs/WEB_UI_PLAN.md` to reflect new architecture
- Update this plan with actual outcomes

## Kill Criteria
- **Step 0 fails:** psycopg2 hangs/crashes from asyncio.to_thread on Fly → stop, keep SQLite
- **Step 3 perf:** Pipeline takes >2x longer due to PG network latency → investigate batching before continuing
- **Step 4 data:** Jobs don't appear incrementally on dashboard → debug before proceeding

## Dependencies
- `psycopg2-binary` added to `requirements.txt`

## Estimated Effort
- Step 0: 10 minutes
- Step 1: 15 minutes
- Step 2: 30 minutes
- Step 3: 90 minutes (largest — 35 queries to adapt)
- Step 4: 30 minutes (net deletion)
- Step 5: 20 minutes
- Step 6: 30 minutes
- Step 7: 15 minutes
- **Total: ~4 hours**
