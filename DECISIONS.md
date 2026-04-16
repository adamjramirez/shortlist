# DECISIONS — Shortlist

Architectural and product decisions with rationale. Most recent first.

Inherits: `~/Code/DECISIONS.md` (T1 — agency-level decisions)

---

## D-SL-015: Salary estimates from LLM training data only — no external comp sources (2026-04-16)

**Chose:** Salary estimates come from Gemini's self-assessment during the scoring call. Inputs: role title + company + location. Output: range + confidence (low/medium/high) + one-sentence basis.

**Over:** External comp data integrations:
- **levels.fyi** — no public API; scraping is fragile and legally ambiguous. Strong for FAANG + big tech, patchy for startups (which is most of what we score).
- **Glassdoor** — no API since 2021. Wide coverage but noisy self-reports; hard to tie to a specific role level.
- **BLS / OccInfo** — authoritative for US occupations but bucketed by SOC code ("Computer and Information Systems Managers"), not by title/level/stage. Too coarse for VP-vs-Director distinctions.
- **Payscale / Salary.com** — similar issues to Glassdoor, plus paywalls.

**Why:** For the current user base (1) and scale (~200 visible jobs), the integration + maintenance cost of any of these is not justified. The LLM-inferred estimate + transparency layer (listed-vs-estimated visual split, confidence dots, per-job basis sentence, methodology page) is cheap and directionally useful.

**Evidence:** Plan at `docs/plans/2026-04-16-salary-transparency.md`. 99.8% of scored jobs have `salary_text IS NULL` from the source, so we were already relying on inference — the change is making it honest, not grounding it.

**Revisit when:**
- Scale grows past ~1000 users or the UX signal for salary becomes load-bearing for retention
- A consumer-friendly comp API emerges (e.g., levels.fyi opens up)
- Users give feedback that estimates are systematically wrong in a direction we can fix with grounded data

**Cheapest fallback if grounding becomes necessary:** a static table of role-level-by-region-by-stage comp medians (scraped quarterly, held in `data/comp_reference.json`) — replaces the LLM inference without a live integration.

---

## D-SL-014: Scoring parallelism at 4 workers after VM upgrade (2026-04-07)

**Chose:** `max_workers=4` for LLM scoring in the PG pipeline.

**Over:** 2 workers (previous default), or higher counts.

**Why:** VM scaled from 512MB to 1024MB. 4 workers is the safe ceiling for Gemini free tier rate limits. Each job gets an isolated LLM call — no batching, no cross-contamination. Beyond 4-6 workers risks 429s on the free tier.

**Evidence:** VM scaled 2026-04-07 after OOM. Rate limit headroom tested empirically.

**Revisit when:** Gemini tier changes, or rate limit testing shows headroom for 6+ workers.

---

## D-SL-013: App VM and DB VM are separate machines (2026-04-07)

**Chose:** Treat app VM and DB VM as independently scalable Fly machines.

**Over:** Assuming they share resources or scale together.

**Why:** Two separate Fly machines — scaling one does not scale the other. `fly machine update [machineID] --vm-memory [mb] --app shortlist-db` required for DB. Discovered after OOM on DB machine while app was fine.

**Evidence:** Both scaled to 1024MB on 2026-04-07 after OOM kills.

**Revisit when:** Traffic grows enough to consider managed Postgres.

---

## D-SL-012: CLI frozen on SQLite (no active development) (2026-04)

**Chose:** Freeze CLI development. All active work goes to the web app.

**Over:** Maintaining CLI and web in parallel.

**Why:** CLI uses SQLite, web uses PostgreSQL. Keeping both in sync doubles the surface area with no user value. Web is the primary development path.

**Evidence:** CLAUDE.md explicitly marks CLI as "frozen on SQLite — don't maintain alongside web."

**Revisit when:** A specific CLI use case can't be addressed by the web API.

---

## D-SL-011: `is_closed` separate from `user_status` (2026-04)

**Chose:** Two independent fields: `is_closed` (boolean, job availability) and `user_status` (enum: saved/applied/skipped/null, user intent).

**Over:** Single status field encoding both job state and user intent.

**Why:** A job can be saved AND closed. Combining these means a job closing silently removes it from saved, or a user can't track their intent after a job closes. The PUT endpoint handles both states on the same endpoint with different values (`"clear"` resets user_status, `"closed"` toggles is_closed).

**Evidence:** CLAUDE.md Common Mistakes pattern.

**Revisit when:** Never — these are fundamentally different axes.

---

## D-SL-010: subprocess+curl for Gemini instead of httpx (2026-04)

**Chose:** `subprocess+curl` for all Gemini API calls in `llm.py`.

**Over:** httpx, urllib, or any sync HTTP library called from asyncio threads.

**Why:** httpx sync and urllib crash when called inside `asyncio.to_thread()` on Fly.io. Root cause is event loop conflict in the thread context. subprocess+curl sidesteps this entirely — the subprocess runs in its own process with no event loop.

**Evidence:** CLAUDE.md stack notes. Discovered in production.

**Revisit when:** Fly.io fixes the threading context, or Gemini has an official async client that's stable.

---

## D-SL-009: Orphan drain at pipeline start (2026-04)

**Chose:** Drain all jobs stuck in `status='new'` from prior runs BEFORE collection begins.

**Over:** Draining after collection, or leaving orphans indefinitely.

**Why:** `upsert_job` only updates `last_seen` — it never resets status. Jobs from failed/cancelled runs stay `new` forever, accumulating silently. Draining at start clears the backlog before new jobs compete for scoring budget. Running after collection would mean orphans miss the filter/score pass for this run.

**Evidence:** CLAUDE.md Key Patterns ("Orphan drain at pipeline start").

**Revisit when:** `upsert_job` is changed to reset status on existing rows.

---

## D-SL-008: Backlog scoring pass after all sources complete (2026-04)

**Chose:** Run a final `_score_filtered(budget_override=remaining)` after all sources complete.

**Over:** Only scoring per-source when that source produces new filtered jobs.

**Why:** `_score_filtered()` is triggered per-source only when `passed > 0`. Jobs from the orphan drain or prior runs that land in `filtered` are never scored without this explicit pass. Without it, backlogged jobs accumulate indefinitely in `filtered`.

**Evidence:** CLAUDE.md Key Patterns ("Backlog scoring pass after collection").

**Revisit when:** Per-source triggers are changed to also handle orphan jobs.

---

## D-SL-007: Per-source scoring budget with 20-job minimum (2026-04)

**Chose:** `remaining // sources_left` budget per source, minimum 20 per source. Score newest jobs first (`ORDER BY first_seen DESC`).

**Over:** Equal fixed budget, or scoring all jobs regardless of count.

**Why:** Prevents any single large source from consuming the entire scoring budget. Minimum 20 ensures every source gets meaningful coverage even when budget is tight. Scoring newest first means recent jobs are always seen; old low-scoring jobs drain out over multiple runs.

**Evidence:** CLAUDE.md Key Patterns ("Per-source scoring budget").

**Revisit when:** Source count or job volume changes significantly.

---

## D-SL-006: Zombie run reaper at scheduler tick start (2026-04)

**Chose:** `reap_zombie_runs()` runs at the start of every scheduler tick, marking runs stuck in `running` for >45 min as `failed`.

**Over:** Relying on the pipeline's finally block to clean up, or manual intervention.

**Why:** OOM kills prevent `finally` blocks from running. Without an external watchdog, runs stay in `running` permanently, and the scheduler's `NOT EXISTS` check blocks all future runs. 45 min is generous — normal runs complete in minutes.

**Evidence:** CLAUDE.md Key Patterns ("Zombie run reaping"). OOM kills observed in production.

**Revisit when:** Fly.io adds OOM-safe process cleanup.

---

## D-SL-005: Score thresholds: SAVED=60, VISIBLE=75, STRONG=85 (2026-04)

**Chose:** Three-tier scoring: save to DB at 60, show to user at 75, highlight as strong at 85.

**Over:** Single threshold, or scoring stored = scoring shown.

**Why:** Storing at 60 preserves borderline jobs for potential re-scoring in future runs with different context. The 75 visibility threshold prevents low-quality results from cluttering the user's inbox. 85 identifies standout roles for stronger presentation.

**Evidence:** CLAUDE.md Key Patterns ("Score threshold 75 for visibility").

**Revisit when:** User feedback suggests threshold is too tight (missing good jobs) or too loose (noise).

---

## D-SL-004: Design system: zinc neutrals, emerald-600 accent, no blue/emoji (2026-04)

**Chose:** Zinc for neutrals, emerald-600 for accent, Outfit + JetBrains Mono typography. No blue, no stone, no emoji, no framer-motion.

**Over:** Generic Tailwind defaults or blue-based design.

**Why:** Consistent, distinctive aesthetic. Blue is overused in SaaS. Zinc reads as neutral without stone's warmth. Emerald is distinctive for the accent without feeling like a generic success green. JetBrains Mono for code/scores adds technical credibility.

**Evidence:** `web/DESIGN.md` is canonical. Any design decision not in DESIGN.md must be added immediately.

**Revisit when:** User research shows the palette creates accessibility issues.

---

## D-SL-003: Favorites in localStorage only (no accounts) (2026-04)

**Chose:** ♥ toggle persists to localStorage. No server-side favorite storage, no accounts required.

**Over:** Server-side favorites with user accounts.

**Why:** Premature before product-market fit. Accounts add significant complexity for zero proven value at current user count.

**Evidence:** CLAUDE.md Key Patterns ("Favorites are localStorage only").

**Revisit when:** Multiple active users request cross-device sync or sharing.

---

## D-SL-002: First-run detection by counting scored jobs (2026-04)

**Chose:** Detect first run by counting `status IN ('scored', 'low_score')` jobs. Zero = first run → wider collection window.

**Over:** `brief_count == 0` (old approach, now deprecated).

**Why:** `brief_count` was incremented inconsistently and didn't survive job re-scoring. Counting actual scored jobs is the ground truth for whether the user has seen results. Wrap in `try/except Exception` with safe default so mock-based tests don't crash on comparison operators.

**Evidence:** CLAUDE.md Key Patterns ("First-run detection").

**Revisit when:** Never — this is the correct semantic.

---

## D-SL-001: `is_new` based on `run_id` match, not `brief_count` (2026-04)

**Chose:** Job's `run_id` matches user's latest non-failed/cancelled run = "new" job.

**Over:** `brief_count == 0` (deprecated field, still in schema but no longer incremented).

**Why:** `brief_count` didn't survive re-scoring and was incremented in multiple places. `run_id` is a natural join that survives re-scoring correctly: if the job was seen in the latest run, it's new; if it predates the run, it's not.

**Evidence:** CLAUDE.md Key Patterns ("`is_new` based on `run_id`").

**Revisit when:** Run model changes fundamentally.
