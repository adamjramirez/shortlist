# CONSTRAINTS — Shortlist

Technical limits and business boundaries that shape what we build.

Inherits: `~/Code/CONSTRAINTS.md` (T1 — agency-level rules)

---

## SL-001: subprocess+curl required for Gemini on Fly.io [greppable]

**Impact:** `httpx` sync and `urllib` crash when called inside `asyncio.to_thread()` on Fly.io. Any direct HTTP call to Gemini outside subprocess will fail silently or raise runtime errors in production.

**Mitigation:** Always use `subprocess+curl` for Gemini LLM calls (implemented in `llm.py`). Never replace with httpx or urllib in async thread contexts.

*Source: CLAUDE.md stack notes. Discovered when httpx/urllib crashed in asyncio.to_thread on Fly.io production.*

---

## SL-002: gemini-2.5-flash hangs on scoring [greppable]

**Impact:** Extended thinking in gemini-2.5-flash causes 60s+ hangs on scoring calls. Scoring pipeline stalls indefinitely.

**Mitigation:** Use `gemini-2.0-flash` for all scoring and pipeline LLM calls. 2.5-flash may only be used for non-scoring contexts if hang behavior is acceptable.

*Source: CLAUDE.md "Common Mistakes to Avoid". Discovered in production — scoring pipeline hung 60s+ per job.*

---

## SL-003: `flag_modified()` required for SQLAlchemy JSON column mutations [greppable]

**Impact:** SQLAlchemy does not detect in-place dict/list mutations on JSON columns. Changes are silently dropped on `session.commit()`.

**Mitigation:** Always call `flag_modified(instance, "column_name")` after mutating any JSON column value. This applies to `profiles.config` and any other JSON/JSONB columns.

*Source: CLAUDE.md Key Patterns and Common Mistakes. Silent data loss in production.*

---

## SL-004: Score visibility threshold is 75, not 60 [greppable]

**Impact:** SCORE_SAVED=60 (stored in DB), SCORE_VISIBLE=75 (returned from API), SCORE_STRONG=85. Returning jobs with score < 75 to users exposes low-quality results.

**Mitigation:** Enforce `SCORE_VISIBLE=75` at the API layer. Never filter by SCORE_SAVED in user-facing endpoints. Jobs scoring 60-74 are saved to DB but must not appear in API responses.

*Source: CLAUDE.md Key Patterns ("Score threshold 75 for visibility").*

---

## SL-005: NextPlay cache is system-wide — filter after caching only [greppable]

**Impact:** `nextplay_cache` is shared across all users. Applying per-user title filters BEFORE caching poisons the cache for other users with different role targets.

**Mitigation:** Filter NextPlay results AFTER caching, on in-memory objects only before extending `all_jobs`. The `NextPlayCollector(title_filter=...)` applies to both step 1 (sequential ATS URL loop) and steps 2/3 (`_probe_homepages`) — a filter in one path does not protect the other.

*Source: CLAUDE.md Common Mistakes. Would silently remove valid jobs for other users.*

---

## SL-006: LaTeX JSON unescape order — `\\` before `\n` [greppable]

**Impact:** Unescaping `\n` before `\\` in the JSON fallback parser splits `\\noindent` into `\` + newline + `oindent`. The resulting LaTeX is broken and tectonic compilation fails.

**Mitigation:** In `_extract_tailor_fields()` and any JSON fallback parser: unescape `\\` → `\` BEFORE `\n` → newline.

*Source: CLAUDE.md Common Mistakes. LaTeX compilation breaks when backslash sequences are split.*

---

## SL-007: `callable` cannot be used as a type annotation [greppable]

**Impact:** `callable | None` raises `TypeError` at class definition time (not runtime). The class fails to load entirely.

**Mitigation:** Use bare `= None` with no annotation, or `from typing import Callable` and use `Callable | None`.

*Source: CLAUDE.md Common Mistakes.*

---

## SL-008: `Config.__new__(Config)` bypasses __init__ [greppable]

**Impact:** Constructing test configs with `Config.__new__(Config)` leaves all fields unset — no `filters`, `brief`, `llm`, etc. Any access raises `AttributeError`. Fails silently if the field access is inside a try/except.

**Mitigation:** Always use `Config(tracks={...})` with the regular constructor in tests.

*Source: CLAUDE.md Common Mistakes.*

---

## SL-009: Zombie runs block the scheduler [operational]

**Impact:** OOM kills prevent `finally` blocks from running, leaving pipeline runs in `running` status permanently. The scheduler's `NOT EXISTS` check prevents new runs from starting — the pipeline stalls indefinitely.

**Mitigation:** `reap_zombie_runs()` runs at the start of every scheduler tick. It marks any run stuck in `running` for >45 min as `failed`. Never remove or disable the zombie reaper.

*Source: CLAUDE.md Key Patterns ("Zombie run reaping").*

---

## SL-010: Orphan drain must run at pipeline start [operational]

**Impact:** Jobs stuck in `status='new'` from prior failed/cancelled runs are never re-evaluated. `upsert_job` only updates `last_seen` — it does not reset status. Backlog grows silently across runs.

**Mitigation:** `run_pipeline_pg` drains all `status='new'` orphan jobs (from prior runs) before collection begins. Filters and moves them to `filtered` or `rejected`. Do not remove or move the drain to after collection.

*Source: CLAUDE.md Key Patterns ("Orphan drain at pipeline start").*

---

## SL-011: Backlog scoring pass must run after all sources complete [operational]

**Impact:** `_score_filtered()` is triggered per-source only when that source produces new filtered jobs. Jobs from the orphan drain or prior runs that stay in `filtered` are never scored without an explicit backlog pass.

**Mitigation:** Pipeline runs a final `_score_filtered(budget_override=remaining)` after all sources complete. Do not remove this pass.

*Source: CLAUDE.md Key Patterns ("Backlog scoring pass after collection").*

---

## SL-012: Per-source scoring budget minimum 20 [greppable]

**Impact:** If a source gets 0 budget (due to integer division), no jobs are scored from that source regardless of how many are available.

**Mitigation:** Per-source budget formula: `remaining // sources_left`, with a minimum of 20 per source. Scores newest jobs first (`ORDER BY first_seen DESC`).

*Source: CLAUDE.md Key Patterns ("Per-source scoring budget").*

---

## SL-013: Scoring parallelism capped at 4 workers [operational]

**Impact:** Increasing `max_workers` beyond 4-6 risks hitting Gemini rate limits on free tier. Each job gets its own isolated LLM call.

**Mitigation:** PG pipeline uses `max_workers=4`. Do not increase without verifying Gemini rate limit headroom.

*Source: CLAUDE.md Key Patterns ("Scoring parallelism"). VM scaled to 1GB 2026-04-07.*

---

## SL-014: `is_closed` is separate from `user_status` [greppable]

**Impact:** A job can be both saved AND closed. Conflating the two fields means a user's saved jobs silently disappear when a role closes, or closed jobs can't be saved.

**Mitigation:** `user_status` = user intent (saved/applied/skipped). `is_closed` = job availability. Toggle via separate code paths. The PUT endpoint handles both via `"clear"` (resets user_status) and `"closed"` (toggles is_closed).

*Source: CLAUDE.md Key Patterns and Common Mistakes.*

---

## SL-015: `CancelledError` must not be caught by bare `except Exception` in cancel loops [greppable]

**Impact:** `CancelledError` inherits from `Exception`. If a cancel check is inside a try/except Exception block, the cancellation is swallowed and the loop never terminates.

**Mitigation:** Always put `_check_cancel()` calls outside try blocks.

*Source: CLAUDE.md Common Mistakes.*

---

## SL-016: psycopg2 auto-deserializes JSON columns [greppable]

**Impact:** Calling `json.loads()` on a value from a PG JSON column that psycopg2 already deserialized causes a `TypeError` (already a dict, not a string).

**Mitigation:** Use `isinstance(data, dict)` guard in any `from_json()` method that handles PG JSON column values.

*Source: CLAUDE.md Common Mistakes.*

---

## SL-017: `uvicorn --limit-max-requests` must be ≥ 10000 [operational]

**Impact:** Health checks fire every 10s and count toward the request limit. Setting 1000 = recycle every 3 hours, causing unnecessary worker restarts that interrupt in-flight requests.

**Mitigation:** Use `--limit-max-requests 10000` or higher. Current setting: 10000.

*Source: CLAUDE.md Common Mistakes. Discovered when health check traffic caused frequent restarts.*

---

## SL-018: No HTTP calls outside `shortlist.http` [greppable]

**Impact:** Bypasses rate limiting. External calls made directly (not through `shortlist.http`) are not rate-limited and risk IP bans or API quota exhaustion.

**Mitigation:** All HTTP calls must go through `shortlist.http`. No direct `requests`, `httpx`, or `urllib` calls for external resources.

*Source: CLAUDE.md Common Mistakes (top entry).*

---

## SL-019: HTTP health checks — only explicit gone signals close [greppable]

**Impact:** Treating any non-200 response as "gone" silently destroys data. Proxy transients (502/timeout), bot challenges (403), rate limits (429), and redirects to login (302) are not closure signals — the resource is almost certainly still live.

**Incident:** 2026-04-16. `expiry.py:61` pre-fix: `return resp.status_code == 200` — any non-200 → False → job closed. 73 live jobs across 2 users falsely closed in 7 days, including jobs returning 200 when re-tested hours later. User-visible inbox dropped 54 → 3 over ~4 hours.

**Mitigation:**
- Every health/expiry checker must return tri-state: `True` (explicit live), `False` (explicit gone), `None` (unknown). Callers close only on explicit `False`.
- Per source, define what "explicit gone" means:
  - HTTP APIs: 404 only
  - Page-based (e.g., Ashby): source-specific body signal (e.g., title === "Jobs")
  - If no explicit signal exists: return `None`, not `False`
- Add a recency skip before the HTTP call: if the resource was successfully collected within the last 24h, skip the check entirely — transient errors are vastly more likely than genuine removal on fresh data.
- `last_seen_stale`-style sweeps remain the safety net for truly old resources.

**Greppable:** `return resp.status_code == 200` or equivalent in any checker, absent a 404-specific branch, is the bug pattern.

*Source: PROJECT_LOG.md 2026-04-16 session 3. Plan at `docs/plans/2026-04-16-url-check-false-positives.md`.*
