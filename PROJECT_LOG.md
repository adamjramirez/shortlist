# PROJECT_LOG.md — Shortlist

Session-by-session progress log. Read this first when resuming work.

---

## Current Focus

Pipeline recovered + hardened (2026-07-03). App was down 2 weeks (DB machine stopped June 18); restarted. Then a cascade of reliability + data-quality fixes made runs actually complete for the first time (run 203, ~19 min). Headline: **6,949 LinkedIn jobs had been silently false-closed on age** by `mark_stale_jobs` Pass 2 — removed it (LinkedIn closure is now owned by the evidence-based expiry checker); reopened them → Adam's visible inbox went 2 → 70 real VP/CTO roles. See 2026-07-03 entry.

## 2026-07-03 — Full pipeline recovery: OOM, reaper, curated speed, LinkedIn data quality, 6,949 false-closes

**Why:** Resuming the job hunt. App was 503 (DB stopped June 18). Beyond that, runs had been failing/never-completing for weeks, and the inbox was full of wrong-company / stale / mis-dated jobs.

**Shipped (12 commits, deployed):**
- **Infra:** restarted DB; app VM 1GB→2GB (OOM); zombie-reaper 45→150 min (real runs take ~90 min, were reaped mid-flight).
- **Run completion:** parallelized curated-source fetch (ThreadPoolExecutor, serial DB writes) + dropped ATS API rate limits 2.0s→0.3s (per-domain limiter was re-serializing ~40 Ashby cos on one domain). Curated went from 2+ hrs → minutes. Run 203 completed in 19 min.
- **LinkedIn data quality:** per-card parser (was mislabeling company, e.g. Honeywell→Oracle, via zipped global `re.findall`); `posted_at` clamped to `first_seen` (reposts showed "1d ago" on 4-mo-old jobs); closure detection via guest API "No longer accepting applications" banner; custom-domain Greenhouse closure via real board API (SPA 200 was masking closures); recency-skip now re-checks old reposts.
- **`age_expired` removal (biggest impact):** `mark_stale_jobs` Pass 2 closed every LinkedIn job with `posted_at>30d` on age alone — 6,949 false-closes for user 2 (incl. live Anthropic/Five9/Zeta/Blooming VP roles). Removed; reopened all; evidence-based expiry checker now owns LinkedIn closure. Inbox 2→70.
- **Sources:** +29 VC-portfolio startups via ATS auto-detect (`discover_ats_from_domain`, not slug-guessing) → 44→73 active curated sources. `data/career_pages/vc_portfolio_2026-07-04.json` + `talentguy_2026-06` committed.

**Open:** levels.fyi collector blocked on user's DevTools cURL capture (rich data confirmed — 26k jobs w/ comp; API is a client-side call). Decodo proxy broken (407, LinkedIn on datacenter IP) — user deferred. Follow-ups: trim curated `all_jobs` memory → scale VM back to 1GB; make reaper progress-aware; verify inbox settles after scheduler prunes the 70.

**Principle reinforced:** never close on age/last_seen alone when a real signal exists (SL-019 extended from ATS to LinkedIn).

## Earlier — Evergreen-warning feature (2026-05-17)

Evergreen-warning feature shipped (2026-05-17). CSVFirst-based per-company stats surface a candidate-protection badge ("X% jobs open 6+ mo") on `JobCard`. Phase A live with 50-company coverage; Phase B (scoring downweight + hide toggle) deferred. Tri-state `last_seen_stale` sweep deployed alongside — closed a 1,610-row silent-data-loss bug class. Both decisions recorded as D-SL-018 and D-SL-019.

## 2026-05-17 — Evergreen-warning feature + tri-state stale-close fix

**Why:** External QA against CSVFirst (independent observer of ~35k greenhouse jobs at 200+ companies) surfaced 1,610+ live jobs across 7 companies (Anthropic, Anduril, Figma, Workato, Airbnb, Five9, Samsara) that we'd silently closed. Root cause: `mark_stale_jobs` Pass 1 closed based on `last_seen` alone, but these companies had been batch-seeded once with no recurring observer — `last_seen` never refreshed, sweep fired against rows nothing was refreshing. Same failure mode class as the 2026-04-16 expiry-checker incident. Reframing CSVFirst from "potential collector" to "candidate-protection signal" turned the cleanup into a shipped feature.

**What got done:**
- New `scripts/qa_against_csvfirst.py` cross-checks CSVFirst snapshots against our DB (false closes, coverage gaps, age drift, stale-company audit). First report: `docs/qa/csvfirst_2026-05-17.md`.
- Seeded 7 affected companies into `career_page_sources` (4 canonical greenhouse via CSVFirst URLs, 3 proxied via slug discovery). Bulk-reopen script (`scripts/bulk_reopen_false_closes.py`) restored 383 user-2 rows; remaining 778 were legitimate closures (URLs no longer in vendor feeds).
- **Tri-state Pass 1** in `pgdb.mark_stale_jobs`: closure now requires an active CPS observer that fetched non-empty within 7 days. 3 new unit tests in `tests/test_job_expiry.py`. Existing tests updated to insert an observer first. CLAUDE.md anti-pattern added.
- **Evergreen-warning feature** (Phase A): new `company_hiring_stats` table (alembic 014) + `EvergreenSignal` API model. Click-toggle popover badge on `JobCard` for jobs at companies where >40% of reqs stay open 6+ months. Extracted shared popover state into `usePopover()` hook; refactored `SalaryEstimate` to use it (DRY). 50-company snapshot ingested via `scripts/ingest_csvfirst_hiring_stats.py`.
- Plan doc: `docs/plans/2026-05-17-csvfirst-qa-and-stale-close-remediation.md`. Decisions: D-SL-018 (tri-state sweep), D-SL-019 (CSVFirst usage).
- Archived per `~/Code/ARCHIVE_SYSTEM.md` — sessions before 2026-04-05 moved to `docs/archive/sessions/`; implemented decisions D-SL-001 through D-SL-015 (excluding open D-SL-012, D-SL-016, D-SL-017) moved to `docs/archive/decisions/2026.md`.

**Commits:** `9f81475` (QA tooling), `341ed95` (tri-state sweep), `ec68902` (evergreen badge), `f64163f` (badge copy), `001d1d8` (popover refactor), `1569622` (session doc), archive commit pending.

**Test count:** 652 non-API tests pass (+3 new). 12 pre-existing errors in `test_career_page_sources.py` (need local PG, unrelated).

**What's next:**
- Phase B (scoring downweight for evergreen companies + user toggle to hide) — deferred until live signal is observed for a few days.
- Request CSVFirst API access → bulk-seed remaining ~250 companies into `career_page_sources` and ingest full hiring-stats snapshot (Tier 4 of plan).

## 2026-05-05 — DB migration for missing late columns

**Why:** First `shortlist run` after #22 crashed with `sqlite3.OperationalError: no such column: salary_basis`. The schema in `shortlist/db.py` had been updated with `salary_basis` previously, but `CREATE TABLE IF NOT EXISTS` doesn't reconcile column lists, so any DB created before that change was missing it. `prestige_tier` was also referenced by `pipeline.py` but missing entirely from the schema.

**What got done:**
- Added `prestige_tier TEXT` to the `jobs` CREATE TABLE in `shortlist/db.py`.
- Introduced `_JOBS_LATE_COLUMNS` registry + `_ensure_jobs_columns()` helper that walks `PRAGMA table_info` and `ALTER TABLE ADD COLUMN`s any missing entries. Runs at the tail of `init_db()`.
- Updated `tests/test_db.py`: required-columns set now includes `salary_basis` + `prestige_tier`; new test simulates an old DB (drops the late columns) and asserts they're added back on re-init without losing data; new idempotency test for double-init.

**Pattern recorded:** `_JOBS_LATE_COLUMNS` is a deliberately small migration ledger — additive-only (`TEXT` columns), no data backfill. The web/Postgres path uses Alembic; the CLI/SQLite path stays light.

**Files changed:** `shortlist/db.py`, `tests/test_db.py`, `PROJECT_LOG.md`.

## 2026-05-05 — Senior-IC track scoring (PR #22)

**Why:** Shortlist scoring was leadership-only. `reject_explicit_ic: true` filtered IC roles before scoring, and the prompt unconditionally said "Must be management." Adam's job hunt now includes senior-IC roles at AI-frontier companies (OpenAI, Anthropic, etc.) where the upside is real.

**What got done:**
- New `staff_ai` track example in `config/example-profile.yaml` (Senior Staff / Principal SE / Forward Deployed Engineer / Applied AI Engineer; `min_reports: 0`).
- `reject_explicit_ic` made non-blocking (default still `true` for new users; user opts in).
- New `_build_track_rules(config)` helper in `shortlist/processors/scorer.py` derives per-track requirements from each track's `min_reports`. `>=1` → leadership rule; `0` → senior-IC rule.
- `SCORING_PROMPT_TEMPLATE` rewritten: per-track requirements injected, hard exclusions added, AI-builder domain signals weighted positively, yellow flags called out separately.
- Removed the unconditional "score IC below 40" rule.
- `scripts/seed_ai_frontier_companies.py`: idempotent seed for 26 companies. Domain-only, lets the discovery loop auto-detect ATS.
- `tests/test_scorer.py`: `TestTrackAwareRules` adds 6 cases.

**Validated:** First `shortlist run` post-PR scored 65 jobs across both tracks (125 EM, 30 staff_ai). 16 of 26 seeded companies got their ATS auto-detected. Top-of-brief: Posit PBC VP Eng (100), Atlassian Head of Eng DX (98), Upbound Director Control Planes (98).

**Pattern recorded:** Track config is the single source of truth for scoring rules. The prompt template stays static; `_build_track_rules` derives per-track text.

**Files changed:** `config/example-profile.yaml`, `scripts/seed_ai_frontier_companies.py`, `shortlist/processors/scorer.py`, `tests/test_scorer.py`, `tests/test_seed_ai_frontier_companies.py`.

## 2026-04-29 — Deprecated model auto-upgrade

**What got done:**
- User 10 hit `profile_analysis_failed` Apr 27 — same `gemini-2.0-flash` deprecation as Apr 20, but his saved profile config still had the old model.
- Added `DEPRECATED_MODELS = {"gemini-2.0-flash": "gemini-2.5-flash"}` in `routes/profile.py`. Any user with a deprecated model saved in their config gets silently upgraded at generate time.
- `model_upgraded_from: str | None` on `GenerateProfileResponse` schema so frontend knows when a remap happened.
- Frontend: on both generate paths, if `model_upgraded_from` is set: updates the model dropdown and shows an 8-second toast prompting save.
- Fixed stale `"gemini-2.0-flash"` fallback in `app/page.tsx`.
- Removed `gemini-2.0-flash` from `JobCard.tsx` cover-letter model picker.
- `showToast` duration-configurable (default 3s, upgrade notice 8s).

**Files changed:** `shortlist/api/schemas.py`, `shortlist/api/routes/profile.py`, `web/src/lib/api.ts`, `web/src/app/profile/page.tsx`, `web/src/app/page.tsx`, `web/src/components/JobCard.tsx`

## 2026-04-26 — Decodo proxy traffic throttled

**What got done:**
- Diagnosed continuous LinkedIn HEAD traffic. Real driver: `expiry.check_expiry_batch` firing 20 jobs every 60s against 3000+ open LinkedIn rows older than the 24h recency-skip threshold.
- Shipped `expiry._run_batch(limit=5)` (commit 9056e29) and `scheduler.TICK_INTERVAL=300` (commit 18878a9). Combined: ~20× reduction.
- Closed 61 jobs at `last_seen >30d` with `closed_reason='stale_30d'` — small impact, but cleared the long-stale tail.

**Key decisions:** D-SL-016 (throttle), D-SL-017 (defer the "should expiry run at all?" question).

**Lesson:** Initial proposal to mass-close stale rows looked like a major lever; sampling the distribution showed it was 61 rows, not thousands. Added to root `CLAUDE.md` Quality Standards: "Sample the distribution before proposing a cleanup as a fix."

**Follow-ups:**
- Watch Decodo dashboard to confirm rate dropped as expected.
- If we keep the loop, consider adding `last_check_at` separate from `last_seen` so the LinkedIn long tail self-throttles.

## 2026-04-20 — Analyze resume: 5 prod bugs fixed for user 10

**What got done:**
Five bugs discovered live via `fly logs` while debugging user 10's failed "Analyze my resume" attempts.

1. **`gemini-2.0-flash` removed from UI + all defaults changed to `gemini-2.5-flash`** — Google deprecated the non-versioned endpoint for new users with billing-enabled GCP projects. Changed defaults across `profile.py`, `tailor.py`, `worker.py`, `profile/page.tsx`.
2. **Cloudflare intercepts 502/503/504 → all LLM errors now 422** — Cloudflare replaces 5xx body with its own HTML. Client-side JSON errors now reach the user.
3. **`handleAnalyze` model-not-saving bug** — `saveApiKeyOrThrow()` was only called inside `if (apiKey)`. Removed the guard.
4. **generate endpoint ignored per-provider `api_keys`** — aligned with `tailor.py`'s pattern: `api_keys.get(provider) or llm_config.get("encrypted_api_key")`.
5. **429 with `limit: 0` = billing-enabled GCP project** — message fix: "Get a key from aistudio.google.com instead." Plus handlers for 403 (API not enabled) and 401 (wrong key type).

**Files changed:** `shortlist/api/routes/profile.py`, `shortlist/api/routes/tailor.py`, `shortlist/api/worker.py`, `web/src/app/profile/page.tsx`, `web/src/components/AiProviderForm.tsx`

**Key decisions:**
- 422 for all app-level errors that must reach the client as JSON when behind Cloudflare. 502 only for genuine upstream-unreachable.
- `saveApiKeyOrThrow()` always runs before generate — it's the sync point even with no new key.
- `gemini-2.5-flash` is the single default everywhere.

## 2026-04-16 (session 3) — url_check false-positive closures + salary basis field

**What got done:**
1. **Salary transparency shipped** (commit cab0fc2). Listed-vs-estimated visual split: listed = bold gray-900; estimated = `~` prefix + click-popover with confidence dots + per-job basis sentence + "How we estimate →" link to new `/about/estimates` methodology page. `is_listed_salary()` sanity-filters HN noise. New `salary_basis` field captured per job (migration 013). D-SL-015 rules out levels.fyi/Glassdoor/BLS/Payscale integrations. §9 Popover added to DESIGN.md.
2. **Inbox drop investigation** — user reported 54 → 25 → 3 over ~4 hours. 59 visible jobs auto-closed via `closed_reason='url_check'` in last 48h, 29 in the 4-hour window.
3. **Root cause** at `expiry.py:61` (pre-fix): `return resp.status_code == 200`. Any non-200 → closed. Live test confirmed transient non-200 was the false positive.
4. **Kill switch + reopen + fix** (commits 88a4ca9, 3acd4cf). Three-step: env-var gate to stop re-closures → SQL reopen (73 jobs across 2 users) → tri-state fix deployed with per-source signal handling + recency skip for last_seen < 24h.
5. **Post-fix signal:** 1 close / 5 checked / 16 skipped-or-unknown. Inbox held at 63.
6. **Stats cleanup:** `_run_batch` now returns `{checked, closed, live, unknown, skipped_recent, errors}`. Scheduler aggregate log updated.

**Key decisions:**
- Only explicit 404 (or Ashby title="Jobs") = gone. Everything else = unknown.
- Recency skip is primary defense (one line, zero schema).
- Kill switch pattern proved valuable for reopen-before-fix ordering.

**Verification:** `pytest tests/test_expiry.py tests/test_scheduler.py` → 67 passed. Prod: Adam inbox 3 → 63, user 6 inbox +12.

## 2026-04-16 — New-user analyze silent failure + step 3/4 UX

**What got done:**
1. **Error banner under AnalyzeButton** — `web/src/app/profile/page.tsx`. Gated on first-time-analyze failures only.
2. **`saveApiKeyOrThrow` early-abort** — `handleAnalyze` aborts with a proper error message if key-save fails.
3. **Step 3 "Most important" amber callout** — emerald was already taken by post-analyze success callout above. Amber matches existing `SaveBar` treatment.
4. **"Regenerate roles" button on step 4** — calls existing `/api/profile/generate` with optional `fit_context`, writes only `result.tracks`.
5. **Backend: optional `fit_context` on `POST /api/profile/generate`** — per-provider injection (Gemini prepend; OpenAI insert; Anthropic merge). `SYSTEM_PROMPT` byte-identical so future prompt caching isn't busted.
6. **Two new API tests** — `test_generate_profile_without_fit_context_unchanged`, `test_generate_profile_with_fit_context_forwarded`.

**Key decisions:**
- Amber for step 3 emphasis, not emerald — emerald is reserved for user-action/accent and collides with the existing success callout.
- Regenerate button discards the returned `fit_context` and `filters` — only overwrites tracks.
- Injection as extra user turn, never into `SYSTEM_PROMPT`.

**Process:** tiered-build (Opus plans → Opus reviews plan → Sonnet executes backend → Sonnet executes frontend → Opus reviews both batches). Plan at `docs/plans/2026-04-16-new-user-analyze-fix.md`.

**Verification:** 9 + 613 tests pass. Deployed (commit 1d7dc33).

## 2026-04-15 — Title gate + curated sources expansion

**What got done:**
1. **Fixed `apply_hard_filters` closure bug** — redundant local import inside `run_pipeline_pg` shadowed the module-level import, making it UnboundLocalError when orphan drain was empty. Runs had been failing for a week.
2. **Standardized curated-source seeding workflow** — `data/career_pages/raw/<name>.txt` (paste) → `scripts/parse_career_pages.py <name>` → `data/career_pages/<name>.json` → `scripts/seed_career_pages.py <name>`.
3. **Seeded 37 Ben Lang 2026-04-15 startups** — all landed `active`. Built `scripts/resolve_direct_ats.py` to crawl direct career pages + regex for embedded ATS URLs; resolved 14 of 35.
4. **Title-gate processor** — new `shortlist/processors/title_gate.py`. Batch LLM call (50 titles each) between hard filter and per-job scorer. Fail-open. 23 new tests, 613 total pass.
5. **Rotated Decodo proxy to dedicated `shortlist` user** — `PROXY_URL`/`PROXY_URLS` on fly.

**Key decisions:**
- Gate prompt stays permissive ("pass when in doubt"). User preference: "some might be a fit but we need to process."
- No new DB migration — `jobs.status` is unconstrained `String`, so `status='title_rejected'` just works.
- Patch `gate_titles` on the consumer, not the source — CLAUDE.md patch-where-used rule.

**Numbers:** Run 58 (no gate): 50 min, 4 matches. Run 59 (with gate): 47 min, 2 matches, 222 title_rejected (~30% prune rate).

## 2026-04-14 — Traffic report script

- Added `scripts/posthog_report.py` (project 139823, host `shortlist.addslift.com`).
- 7-day snapshot: 32 pv / 4 users (all you). Custom events firing as expected.

## 2026-04-08 — Collection efficiency

**What got done:**
1. **LinkedIn time filter** — `r604800` (week) → `r86400` (24h) on recurring runs. First run keeps `r604800` to populate the initial inbox. Detection: `COUNT(*) WHERE status IN ('scored', 'low_score')`. Wrapped in try/except — MagicMock comparison crashes without it.
2. **`_get_collectors` param** — added `li_time_filter: str = "r86400"`.
3. **`get_existing_urls`** — batch URL lookup.
4. **`bulk_update_last_seen`** — lightweight timestamp refresh for already-known jobs. Explicit `now` param for testability.
5. **`_split_known_new`** — splits job list into known/new. Only applies to `_PREFILTER_SOURCES = {"nextplay"}`.
6. **Wire-up in `_process_collected`** — known jobs get `bulk_update_last_seen`; new jobs get full path. `jobs_collected` now counts only new jobs.
7. **9 new tests** (602 total).

**Bug found:** `MagicMock() > 0` raises `TypeError` in Python 3.14. Fixed with try/except around the DB query.

## 2026-04-07 — Systematic job expiry detection

**What got done:**
1. **Migration 011** — `closed_at`, `closed_reason`, `expiry_checked_at` columns on jobs.
2. **`shortlist/expiry.py`** — proactive URL checker for all 4 ATS sources. LinkedIn HEAD through proxy. Greenhouse API for native URLs, HEAD for custom domains. Lever API. Ashby GET + title check. HN: age-based only.
3. **`http.py`** — added `head()`.
4. **`pgdb.mark_stale_jobs()`** — 5-pass staleness pipeline.
5. **`upsert_job`** — re-opens auto-closed jobs when they reappear. Preserves `closed_reason='user'`.
6. **Scheduler** — `run_expiry_checks()` each tick via `asyncio.to_thread`. 20 jobs/tick, cycles in ~10 min.
7. **Pipeline** — `mark_stale_jobs()` at end of every run.
8. **API + Frontend** — `closed_reason` exposed, default views filter `is_closed=false`. Counts exclude closed from `new`.
9. **31 new tests** (601 total).

**Key decisions:**
- Greenhouse `absolute_url` is often on custom company domains — identify by `sources_seen`, not URL patterns.
- HN jobs have null `posted_at` — needs separate pass using `last_seen` as fallback.
- `closed_reason='user'` is sacred — system never overrides user's explicit close.

## 2026-04-07 — Prestige tier + UI polish

**What got done:**
1. **Prestige tier** (`prestige_tier` A/B/C/D) — migration 012, scored in main LLM call, shown as dark pill (`bg-gray-900 text-white`). Tier B not shown (most jobs are B).
2. **Prestige refactor** — extracted `build_prestige_criteria(config)` + `score_prestige(job, config)` standalone function. Single source of truth.
3. **Backfill** — `scripts/backfill_prestige.py` scored all 76 visible jobs. 0 failures.
4. **Source badge** — first source from `sources_seen` shown as `text-gray-400` mono label in the LEFT meta row.
5. **Tier A filter pill** — toggle, stacks with status filter. API: `prestige` query param.
6. **Design system** — badge rule codified: system = plain/fill only; user-set = outlined or solid fill. Tier A = Ink color (not emerald, to avoid Saved collision).
7. **Chainguard duplicate** — closed LinkedIn copy, kept Greenhouse. Cross-source dedup is a known gap.

## 2026-04-07 — Chainguard VP Engineering application

- Generated `adam_ramirez_cv_chainguard.tex/.pdf` — security-first framing, correct 22→10 restructuring history, AI operating model + knowledge transfer system.
- Drafted application answers and applied. Marked as applied in Shortlist.
- Reference check note: tell them verbally on first call, not in writing.

## 2026-04-07 — Pipeline stability: backlog scoring, NextPlay OOM, zombie runs

**What got done:**
1. **Backlog scoring bug fixed** — orphan-drained jobs never triggered scoring. Added explicit backlog pass after all sources complete.
2. **NextPlay OOM fixed (properly)** — root cause: no role-level filtering (1,595 jobs from 26 boards). Fixed via `title_filter` callback applied AFTER caching, on in-memory objects in both code paths.
3. **Zombie run detection** — `reap_zombie_runs()` in scheduler tick marks any run `running` for >45min as `failed`. 5 tests.
4. **Backlog cleared** — 6 manual triggers cleared 1,964 filtered backlog. Final: 14 filtered, 187 scored visible.

**Key decisions:**
- Filter after cache, not before — system-wide cache must stay complete for other users.
- 45-min zombie timeout — longest normal run is ~10 min.

## 2026-04-07 — fit_context, curated sources, orphan drain, scoring upgrades

**What got done:**
1. **fit_context rewritten** — 7,474 chars synthesized from Adam's profile docs. Includes title/target/AI-native criteria/7 AI skills/credibility markers/hard nos/comp targets.
2. **Tracks updated** — `vp_engineering` and `cto_ai_leadership` replace stale queries.
3. **DB OOM fixed** — postgres VM scaled 512MB→1024MB.
4. **Curated career page sources** — new `career_page_sources` table (migration 010), `CuratedSourcesCollector`. State machine: active/closed/invalid, auto-close at 3 consecutive empty. 20 new tests.
5. **Ben Lang's 35 companies seeded** — ben_lang_2026-04-07.
6. **Orphan drain** — at pipeline startup. First run drained 673 stuck jobs.
7. **Scoring budget** — 150 → 500 jobs/run. Workers 2 → 4.

**Key decisions:**
- App VM already 1024MB; DB VM needed separate scale.
- `career_page_sources` is system-wide (no user_id).
- `max_workers=4` for LLM scoring — safe with 1GB VM and Gemini free tier.

## 2026-04-07 — AWW toggle + use_aww_slice

**What got done:**
1. Discovered AWW slice was silently replacing `fit_context` on every run.
2. `resolve_fit_context(config, aww_content)` extracted from worker — supplement-not-replace, `use_aww_slice` toggle.
3. `use_aww_slice: bool` added to `ProfileUpdate`/`ProfileResponse` schemas.
4. Frontend: AWW node ID field + toggle in Advanced section, shows what scorer sees.
5. Fixed pre-existing `test_aww_client.py` failure.
6. 13 new tests (644 total). AWW slice disabled for Adam's account.

**Key decisions:**
- Supplement not replace — user fit_context always first, AWW appended with separator.
- `profiles.config` is `json` type (not `jsonb`) — `||` operator doesn't work; use Python read-modify-write.

---

## Earlier sessions — archived

Sessions before 2026-04-05 moved to `docs/archive/sessions/` per `~/Code/ARCHIVE_SYSTEM.md`. Start at `docs/archive/INDEX.md` to find a specific period.
