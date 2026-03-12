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

## Scope

### Files to change

| File | Change | Size |
|------|--------|------|
| `shortlist/db.py` | Replace SQLite with psycopg2 PG connection, adapt SQL syntax | **Large** |
| `shortlist/pipeline.py` | Remove `init_db`/`get_db`, accept PG conn, remove SQLite imports | Medium |
| `shortlist/api/worker.py` | Remove `_copy_rows_to_pg`, `on_jobs_ready`, pass PG conn to pipeline | **Large** (simplifies) |
| `shortlist/processors/enricher.py` | 3 calls: `get_cached_enrichment`, `cache_enrichment` — adapt SQL | Small |
| `shortlist/collectors/nextplay.py` | `probe_cache` table reads/writes — adapt SQL | Small |
| `shortlist/brief.py` | `BriefData.from_db` — adapt SQL (CLI only, can keep SQLite or switch) |
| `shortlist/cli.py` | Pass PG URL or keep SQLite for local CLI use | Small |
| `shortlist/api/models.py` | Rename `jobs_web` → `jobs`, `companies_web` → `companies` | Small |
| `alembic/versions/` | New migration: rename tables, add missing columns | Small |
| Tests | Update fixtures, remove SQLite temp files | Medium |

### SQL syntax changes (SQLite → PostgreSQL)

| SQLite | PostgreSQL |
|--------|-----------|
| `INTEGER PRIMARY KEY` | `SERIAL PRIMARY KEY` |
| `DATETIME DEFAULT CURRENT_TIMESTAMP` | `TIMESTAMP DEFAULT NOW()` |
| `?` parameter | `%s` parameter |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `json_extract()` | `->` / `->>` operators |
| `GROUP_CONCAT()` | `STRING_AGG()` |
| No `RETURNING` (old ver) | `RETURNING id` |
| `conn.row_factory = sqlite3.Row` | `cursor_factory=psycopg2.extras.RealDictCursor` |

### What gets deleted
- `worker.py`: `_copy_rows_to_pg()` (~50 lines)
- `worker.py`: `on_jobs_ready` callback + SQLite row→dict conversion (~20 lines)
- `worker.py`: final SQLite copy block (~15 lines)
- `pipeline.py`: `on_jobs_ready` parameter and `_notify_jobs_ready()` (~10 lines)
- `db.py`: SQLite `SCHEMA` constant (~100 lines) — replaced with PG equivalent or removed (use Alembic)

### What stays
- `brief.py` can keep SQLite for CLI-only use (reads from local `jobs.db`)
- `cli.py` can offer both: `--db-url` for PG, default to local SQLite
- All SQLAlchemy models and async routes stay unchanged

## Implementation Steps

### Step 1: DB layer (`shortlist/db.py`)
- Add `get_pg_connection(db_url: str)` → returns `psycopg2.connection` with `RealDictCursor`
- Adapt `upsert_job()`: `?` → `%s`, `INSERT OR IGNORE` → `ON CONFLICT`
- Add `user_id` parameter to all functions (PG is multi-tenant)
- Keep `init_db()` / `get_db()` for CLI backward compat

**Verify:** Unit test `upsert_job` against PG test database

### Step 2: Pipeline (`shortlist/pipeline.py`)
- Accept `db_url: str` and `user_id: int` instead of `project_root: Path`
- Open `psycopg2` connection at start, close at end
- Replace all `db.execute("...", (...))` with PG-compatible SQL
- Remove `on_jobs_ready` parameter entirely
- Add `user_id` to all job inserts/queries
- Results are immediately visible in PG — no copy step needed

**Verify:** Run pipeline against test PG, check jobs appear in `jobs` table

### Step 3: Worker (`shortlist/api/worker.py`)
- Remove `_copy_rows_to_pg()` function
- Remove `on_jobs_ready` callback
- Remove final SQLite copy block
- Remove `tempfile.TemporaryDirectory` — no more temp SQLite
- Pass `db_url` and `user_id` to `run_pipeline()`
- Progress flush loop stays (writes to `runs` table via async SQLAlchemy)

**Verify:** End-to-end: start run → jobs appear on dashboard incrementally

### Step 4: Table rename migration
- Alembic migration: `jobs_web` → `jobs`, `companies_web` → `companies`
- Update `api/models.py` table names
- Update any raw SQL referencing old names

**Verify:** `fly deploy`, run migration, existing data preserved

### Step 5: Enricher + NextPlay (`shortlist/processors/enricher.py`, `shortlist/collectors/nextplay.py`)
- Adapt 3 enricher functions to use `%s` params
- Adapt NextPlay probe cache to PG
- Both receive PG connection from pipeline

**Verify:** Enrichment runs, probe cache works

### Step 6: CLI compatibility (`shortlist/cli.py`)
- Add `--db-url` flag (default: local SQLite for backward compat)
- When PG URL provided, use PG connection throughout

**Verify:** `shortlist run` still works locally with SQLite

### Step 7: Cleanup
- Remove dead code from worker
- Update tests to use PG fixtures where appropriate  
- Delete SQLite schema from `db.py` if CLI is fully migrated

## Kill Criteria
- If PG sync connection from `asyncio.to_thread` has the same issues as httpx → stop, keep SQLite
- If pipeline performance degrades >2x due to PG network latency → stop, investigate

## Dependencies
- `psycopg2-binary` (add to requirements.txt)

## Estimated Effort
~3-4 focused hours across 6 steps. Steps 1-3 are the core change. Steps 4-7 are cleanup.
