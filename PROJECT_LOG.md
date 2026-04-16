# PROJECT_LOG.md — Shortlist

Session-by-session progress log. Read this first when resuming work.

---

## Current Focus

**New-user analyze fix shipped to the codebase (not yet deployed). Silent failure surfaced when a concerned new user reported Analyze "started but didn't finish." Root cause: `SaveBar` (the only `error` render site) is gated on `hasProfile || generated`, both false for first-time analyze failures. Added visible banner, amber "most important" callout on step 3, and Regenerate-roles button on step 4. Next: deploy, watch the new user retry.**

## 2026-04-16 — New-user analyze silent failure + step 3/4 UX

**What got done:**
1. **Error banner under AnalyzeButton** — `web/src/app/profile/page.tsx`. Gated on `error && !hasProfile && !generated` so only first-time-analyze failures show it (existing users still get errors via `SaveBar`). Previously these errors were set in React state but never rendered.
2. **`saveApiKeyOrThrow` inner + catching outer split** — `handleAnalyze` now aborts early with a proper error message if key-save fails, instead of proceeding to `generate()` and getting a misleading 400.
3. **Step 3 "Most important" amber callout** — emerald was already taken by the post-analyze success callout directly above (would have made emerald soup). Amber matches existing `SaveBar` "Unsaved changes" treatment.
4. **"Regenerate roles" button on step 4** — calls existing `/api/profile/generate` with optional `fit_context` passed through, writes only `result.tracks` (discards fit_context + filters intentionally). Disabled when no resume, no fit_context, or no saved/pending API key.
5. **Backend: optional `fit_context` on `POST /api/profile/generate`** — schemas, `FIT_CONTEXT_ADDENDUM` module constant, per-provider injection (Gemini prepend user turn; OpenAI insert user message between system+resume; Anthropic merge into single user message since roles must alternate). `SYSTEM_PROMPT` byte-identical (md5 verified) so future prompt caching isn't busted.
6. **Two new API tests** — `test_generate_profile_without_fit_context_unchanged`, `test_generate_profile_with_fit_context_forwarded`. `FakeProfileGenerator` records `last_fit_context`. Existing `test_generate_no_api_key` at line 70 already covered the no-key path; did not duplicate.

**Key decisions:**
- Amber for step 3 emphasis, not emerald — emerald is reserved for user-action/accent and collides with the existing success callout.
- Regenerate button discards the returned `fit_context` and `filters` — only overwrites tracks. User's hand-edited step 3 and filters stay intact.
- Injection as extra user turn, never into `SYSTEM_PROMPT` — keeps the system prompt stable.
- Anthropic's alternating-role requirement forced merging fit_context + resume into one user message; Gemini/OpenAI use separate messages.

**Process:** tiered-build (Opus plans → Opus reviews plan → Sonnet executes backend → Sonnet executes frontend → Opus reviews both batches). Plan at `docs/plans/2026-04-16-new-user-analyze-fix.md`. First Opus pre-execution review caught emerald-soup risk, missing apiKey guard on Regenerate disabled state, and a duplicate test that already existed.

**Verification:**
- `pytest tests/api/test_profile_generate.py -q` → 9 passed, 1 pre-existing `fpdf` import error.
- `pytest tests/ --ignore=tests/api -q` → 613 passed, 2 skipped, 12 pre-existing psycopg2 errors (local Postgres not running).
- `cd web && npm run build` → clean, no type errors.

**Follow-ups open:**
- Deploy to Fly (`fly deploy --app shortlist-web`) and walk through the three UX paths as a fresh user.
- Sharpen the `test_generate_no_api_key` detail-string assertion if we want to lock in the exact error message.

## 2026-04-15 — Title gate + curated sources expansion

**What got done:**
1. **Fixed `apply_hard_filters` closure bug** — redundant local import inside `run_pipeline_pg` under `if _orphan_new:` shadowed the module-level import, making it UnboundLocalError whenever orphan drain was empty. Runs had been failing for a week. One-line fix (pipeline.py ~527). Deployed.
2. **Standardized curated-source seeding workflow** — replaced per-list hardcoded scripts with: `data/career_pages/raw/<name>.txt` (paste) → `scripts/parse_career_pages.py <name>` (Gemini extracts + URL regex classifies ATS) → `data/career_pages/<name>.json` (reviewable) → `scripts/seed_career_pages.py <name>` (idempotent load via fly proxy).
3. **Seeded 37 Ben Lang 2026-04-15 startups** — all landed `active`. Built `scripts/resolve_direct_ats.py` to crawl direct career pages + regex for embedded ATS URLs (ashby/greenhouse/lever/workable); resolved 14 of 35 direct entries (Cursor→ashby, Applied Intuition→greenhouse, WHOOP→lever, etc.). First productive run yielded ~1500 jobs from 10 ATS-resolved companies.
4. **Title-gate processor** — new `shortlist/processors/title_gate.py`. Batch LLM call (50 titles each) between `apply_hard_filters` and per-job scorer. Fail-open. Gemini 2.0 Flash via `call_llm(json_schema=...)`. `config.llm.title_gate_enabled=True` (default). 23 new tests, 613 total pass. Built via tiered-build (Opus plan → Sonnet execute x2 → Opus review).
5. **Rotated Decodo proxy to dedicated `shortlist` user** — `PROXY_URL`/`PROXY_URLS` on fly.

**Key decisions:**
- Gate prompt stays permissive ("pass when in doubt"). User preference: "some might be a fit but we need to process. 45-55 min is OK since it runs in background." Don't tighten to exact-fit.
- No new DB migration — `jobs.status` is unconstrained `String`, so `status='title_rejected'` just works.
- Patch `gate_titles` on the consumer (`shortlist.pipeline`), not the source — CLAUDE.md patch-where-used rule.
- Reaper marks runs `failed` at 45 min but worker keeps going; `finally` block overwrites back to `completed` when it wraps. Consider bumping `ZOMBIE_RUN_TIMEOUT_MINUTES` to 90 for DB/reality alignment.

**Numbers:**
- Run 58 (no gate, baseline): 50 min, 2133 collected, 4 matches
- Run 59 (with gate): 47 min, 2128 collected, 2 matches, 222 title_rejected (~30% prune rate — below 70% target because hard filter already removes obvious misses)
- Net speedup: ~3 min wall clock. Modest but real.

**Follow-ups open:**
- 21 direct-ATS sources still unresolved (JS-injected iframes can't be parsed by plain HTTP). Headless browser or manual resolution if priority.
- Curated collector's fetched jobs don't currently go through `_split_known_new` pre-filter — every run re-upserts the full job list for every ATS company. Follow-up from 2026-04-08.
- Cross-source dedup (LinkedIn+Greenhouse same role).

## 2026-04-14 — Traffic report script

- Added `scripts/posthog_report.py` (project 139823, host `shortlist.addslift.com`).
- 7-day snapshot: 32 pv / 4 users (all you). Custom events firing: `run_completed` (3), `run_failed` (2), `job_expanded` (7), `job_status_changed` (2). Pipeline active, no external users.

## 2026-04-08 — Collection efficiency

**What got done:**
1. **LinkedIn time filter** — changed from `r604800` (week) to `r86400` (24h) on recurring runs. First run (no scored jobs yet) keeps `r604800` to populate the initial inbox. Detection: `COUNT(*) WHERE status IN ('scored', 'low_score')`. Wrapped in try/except — MagicMock comparison crashes without it.
2. **`_get_collectors` param** — added `li_time_filter: str = "r86400"` so callers control the filter. `run_pipeline_pg` computes it before calling.
3. **`get_existing_urls(conn, user_id, urls)`** — batch URL lookup, returns set of known URLs.
4. **`bulk_update_last_seen(conn, user_id, urls, now=None)`** — lightweight timestamp refresh for already-known jobs. `now` param makes it testable.
5. **`_split_known_new(conn, user_id, name, jobs)`** — module-level function, splits job list into `(known_urls, new_jobs)`. Only applies to `_PREFILTER_SOURCES = {"nextplay"}`. LinkedIn uses f_TPR; HN is low volume.
6. **Wire-up in `_process_collected`** — known jobs get `bulk_update_last_seen`; new jobs get full `upsert_job` → filter → score path. `jobs_collected` now counts only new jobs.
7. **9 new tests** — 2 LinkedIn filter tests, 4 pgdb tests, 3 `_split_known_new` tests. 602 total.

**Key decisions:**
- Curated sources use `_on_curated_fetched` callback (not `_process_collected`) — pre-filter doesn't apply there. Follow-up.
- `bulk_update_last_seen` takes explicit `now` — not `NOW()` SQL function. Testable without DB, consistent within a run.
- `_PREFILTER_SOURCES` at module level (not inside function) — not recreated per call.
- First-run detection via scored job count, not run history — simpler, same semantics.

**Bug found in execution (not caught in review):**
- `MagicMock() > 0` raises `TypeError` in Python 3.14. The review didn't flag this. Fixed with try/except around the DB query.

## 2026-04-07 — Systematic job expiry detection

**What got done:**
1. **Migration 011** — `closed_at`, `closed_reason`, `expiry_checked_at` columns on jobs. Backfilled existing `is_closed=true` rows with `closed_reason='user'`.
2. **`shortlist/expiry.py`** — proactive URL checker for all 4 ATS sources. LinkedIn: HEAD through proxy (404=gone). Greenhouse: API endpoint for native URLs, HEAD stored URL for custom domains (samsara.com etc). Lever: individual API endpoint. Ashby: GET + title check (`@` = active, `Jobs` = gone). HN: no URL signal, age-based only. All HTTP via `shortlist.http`.
3. **`http.py`** — added `head()` function (same proxy/rate-limit pattern as `get()`).
4. **`pgdb.mark_stale_jobs()`** — 5-pass staleness pipeline: ATS 3-day last_seen, LinkedIn 30-day posted_at, HN 45-day posted_at, HN null posted_at 45-day last_seen (critical: all current HN jobs have null posted_at), generic 7-day last_seen.
5. **`upsert_job`** — re-opens auto-closed jobs when they reappear in a feed. Preserves `closed_reason='user'` (never auto-reopens user-closed jobs).
6. **Scheduler** — `run_expiry_checks()` fires each tick via `asyncio.to_thread`. Checks 20 jobs/tick, cycles through all 187 in ~10 minutes. Errors swallowed.
7. **Pipeline** — `mark_stale_jobs()` at end of every pipeline run. `closed_count` in return dict and worker progress.
8. **API** — `closed_reason` in `JobSummary`. Inbox + default view filter `is_closed=false`. Counts exclude closed from `new`. Toggle sets `closed_reason='user'`.
9. **Frontend** — `closed_reason` sub-text on expanded view, `closed_count` in run footer.
10. **31 new tests** (580 + 21 expiry = 601 total across test files).

**Key decisions:**
- Greenhouse `absolute_url` is often on custom company domains (samsara.com) — identify by `sources_seen`, not URL patterns.
- HN jobs have null `posted_at` — needs separate pass using `last_seen` as fallback.
- All HTTP via `shortlist.http` — rate limits already registered for all 4 domains, proxy auto-applied for LinkedIn.
- `closed_reason='user'` is sacred — system never overrides user's explicit close.
- Saved/Applied tabs keep showing closed jobs (user may have applied before it closed).

**What's next:**
- Monitor first auto-run to see how many jobs get marked stale
- CV title update — brief at `cv-new/BRIEF-title-update.md`

## 2026-04-07 — Prestige tier + UI polish

**What got done:**
1. **Prestige tier** (`prestige_tier` A/B/C/D) — migration 012, scored in main LLM call alongside fit_score, stored as VARCHAR(1), shown as dark pill badge (`bg-gray-900 text-white`) in JobCard. Tier B not shown (too noisy — most jobs are B).
2. **Prestige refactor** — extracted `build_prestige_criteria(config)` (derives criteria from `config.tracks`, not hardcoded strings) + `score_prestige(job, config)` standalone function (own prompt/schema, reuses criteria builder). Main scorer calls `build_prestige_criteria()` via format param. One source of truth.
3. **Backfill** — `scripts/backfill_prestige.py` scored all 76 visible jobs. 0 failures.
4. **Source badge** — first source from `sources_seen` shown as `text-gray-400` mono label in the LEFT meta row (company · location · age · LinkedIn), not the badge row. Prevents layout shift when status badges appear.
5. **Tier A filter pill** — toggle in filter row, stacks with status filter. API: `prestige` query param. Frontend: `prestigeFilter` state.
6. **Design system** — badge rule codified: system badges = plain text or fill only (no border). User-set badges = outlined or solid fill. Tier A = `bg-gray-900 text-white` (Ink color, not emerald, to avoid collision with Saved badge).
7. **Chainguard duplicate** — closed LinkedIn copy (ID 6547), kept Greenhouse (authoritative ATS). Cross-source dedup is a known gap.

**Key decisions:**
- Prestige criteria derived from `config.tracks` — updating profile automatically updates scoring criteria
- Tier B hidden — most jobs score B, showing it adds noise without signal
- `bg-gray-900` for Tier A — emerald conflicted with Saved badge (same color family). Ink = high-value content signal per design system.
- Source label goes in meta row (left), not badge row (right) — structural info, not status

**What's next:**
- Cross-source dedup: same role from LinkedIn + Greenhouse = two visible rows. Needs company + normalized title dedup.
- CV title update — brief at `cv-new/BRIEF-title-update.md`
- Monitor prestige quality over next few pipeline runs

## 2026-04-07 — Chainguard VP Engineering application

- Generated `adam_ramirez_cv_chainguard.tex/.pdf` — security-first framing, correct 22→10 restructuring history, AI operating model + knowledge transfer system, Engineering Manager Exchange
- Drafted application answers: velocity question (autonomous bets model + training 100+ engineers), AI teams question (shared context / leaving the team behind)
- Applied. Marked as applied in Shortlist.
- Reference check note: tell them verbally on first call, not in writing

## 2026-04-07 — Pipeline stability: backlog scoring, NextPlay OOM, zombie runs

**What got done:**
1. **Backlog scoring bug fixed** — `_score_filtered()` only fired when a source produced new filtered jobs. Orphan drain output (and all prior-run filtered jobs) never triggered scoring. Added explicit backlog pass after all sources complete: `_score_filtered(budget_override=remaining)`.
2. **NextPlay OOM fixed (properly)** — NextPlay fetches ALL roles from ATS boards (1,595 jobs from 26 boards). Root cause: no role-level filtering. Fixed via `title_filter` callback on `NextPlayCollector` — applied AFTER caching (cache stays unfiltered/system-wide), on in-memory objects in both code paths (step 1 sequential ATS loop + steps 2/3 parallel `_probe_homepages`). 27 tests.
3. **Zombie run detection** — OOM kills prevent `finally` blocks, leaving runs in `running` forever, blocking all future auto-runs. `reap_zombie_runs()` in scheduler tick marks any run `running` for >45min as `failed`. 5 tests.
4. **Backlog cleared** — ran 6 manual triggers to clear 1,964 filtered backlog. Final state: 14 filtered, 187 scored (visible), pipeline stable.

**Key decisions:**
- Filter after cache, not before — system-wide cache must stay complete for future users
- `title_filter` as callback (not hardcoded) — future users with different role targets pass their own filter or None
- 45-min zombie timeout — longest normal run is ~10 min; 45 gives headroom without leaving real zombies
- Zombie reaper in same transaction as `trigger_due_users` — atomic: reap then schedule

**What's next:**
- CV title update — brief at `cv-new/BRIEF-title-update.md`
- Re-upload corrected CV after CV agent
- Pipeline now self-healing; auto-run handles everything from here

## 2026-04-07 — fit_context, curated sources, orphan drain, scoring upgrades

**What got done:**
1. **fit_context rewritten** — 7,474 chars synthesized from goals.md, guardrails.md, ai-skills-mapping.md, profile.md. Includes: Senior Director title, VP/CTO target, AI-native 5-criteria definition, 7 AI skills with evidence, Panora 3/3 outcome agent score, Howdy BBQ founder credibility, German/global operator context, hard nos, comp targets ($350K–$600K).
2. **Tracks updated** — replaced stale queries with `vp_engineering` (VP of Engineering, Head of Engineering, VP Engineering, SVP Engineering, VP of Technology) and `cto_ai_leadership` (CTO, Chief Technology Officer, Head of AI Engineering, VP AI Engineering, VP of AI).
3. **DB OOM fixed** — postgres VM OOM killed, scaled 512MB→1024MB (`fly machine update e827d10fe59778 --vm-memory 1024 --app shortlist-db`).
4. **Curated career page sources** — new `career_page_sources` table (migration 010), `CuratedSourcesCollector`, pipeline integration. State machine: active/closed/invalid, auto-close at 3 consecutive empty fetches. 20 new tests.
5. **Ben Lang's 35 companies seeded** — from April 7 2026 LinkedIn post (ben_lang_2026-04-07). 5 Ashby slugs (Momentic, Grotto AI, Foundry Robotics, ATG, Baba) + 30 direct pages.
6. **Orphan drain** — added at pipeline startup. Drains jobs stuck in `status='new'` from cancelled runs before collection. First run drained 673 stuck jobs (480 filtered, 193 rejected).
7. **Scoring budget** — increased from 150→500 jobs/run. Workers 2→4 (safe with 1GB VM).

**Key decisions:**
- App VM already 1024MB; DB VM was still 512MB — both now 1024MB
- `career_page_sources` is system-wide (no user_id) — curated lists benefit all users
- Orphan drain runs at start of every PG pipeline run — prevents silent backlog from cancelled runs
- `max_workers=4` for LLM scoring — each job gets its own isolated call, no batching
- Scoring fetches `ORDER BY first_seen DESC` — newest jobs scored first; old backlog clears over multiple runs

**What's next:**
- CV title update — brief at `cv-new/BRIEF-title-update.md`, all 4 .tex files need title correction
- Re-upload corrected CV to Shortlist after CV agent completes
- Monitor next auto-run (12h) for quality of matches against new fit_context + tracks
- Consider adding Harmonic.ai as a data source for curated company lists

## 2026-04-07 — AWW toggle + use_aww_slice

**What got done:**
1. Discovered AWW slice was silently replacing `fit_context` on every run with no user visibility
2. `resolve_fit_context(config, aww_content)` extracted from worker — supplement-not-replace, `use_aww_slice` toggle
3. `use_aww_slice: bool` added to `ProfileUpdate`/`ProfileResponse` schemas and profile defaults
4. Frontend: AWW node ID field + toggle in Advanced section, shows "Scorer sees: fit context + AWW slice" vs "fit context only"
5. Fixed pre-existing `test_aww_client.py` failure (`FakeResponse` missing `headers`)
6. 13 new tests (644 total). Deployed. AWW slice disabled for Adam's account.

**Key decisions:**
- Supplement not replace — user fit_context always first, AWW appended with `## Additional Context (from AWW)` separator
- `use_aww_slice` defaults `True` (backward compat) but explicitly set `False` for Adam via DB
- `profiles.config` is `json` type (not `jsonb`) — `||` operator doesn't work; use Python read-modify-write

**What's next:**
- Update fit_context for Adam's account from `~/Code/profile/` — synthesize goals.md, profile.md, guardrails.md into rich job-search context
- Re-score existing stored jobs against new fit_context

---

## 2026-04-02 — Scheduled auto-run

**What got done:**
1. Migration 009: `auto_run_enabled`, `auto_run_interval_h`, `next_run_at`, `consecutive_failures` on profiles; `trigger` on runs
2. `shortlist/scheduler.py`: `trigger_due_users` (single NOT EXISTS query, no N+1), `_fire_and_update` (callback pattern — restart-safe), `_update_profile_after_run`, `run_scheduler` loop
3. Commit-before-fire: run rows committed before `asyncio.create_task` to avoid race condition
4. Profile route: `AutoRunConfig`/`AutoRunUpdate` schemas, dedicated column handling, `_to_response` signature update
5. Runs route: `trigger='manual'` on creation, resets `next_run_at` after manual run
6. supervisord.conf: scheduler as third process (priority 15)
7. Frontend: `AutoRunSettings` component (toggle/interval/countdown/warnings), profile page, history 'scheduled' badge
8. 32 new tests (630 total). Deployed to Fly.io — migration ran clean, scheduler live.

**Key decisions:**
- Callback pattern (`_fire_and_update`) over `since=last_tick` — survives restarts
- `autoRunDirty` flag in frontend — avoids resetting `next_run_at` on every profile save
- Separate `AutoRunUpdate` schema with `enabled: bool | None` — interval-only changes don't touch enabled state
- Backoff: `min(2^failures, 24)h`, auto-disable at 5 consecutive failures

**What's next:**
- Email Mihai about the 429 fix + new design
- PostHog dashboard setup
- Run a pipeline to verify `run_id` gets set on scored jobs in production

---

**What got done (2026-04-03, session 2):**
1. Profile page componentized: ResumeUploader, AiProviderForm, AnalyzeButton, SaveBar extracted (623→392 lines)
2. Profile page design: Phase A (setup) in white card, Phase B (search profile) flat with divide-y, centered divider label between phases
3. Signup flow fix: redirects to /profile instead of /getting-started
4. Getting-started page: auth-aware (logged-in users see "Go to profile" instead of "Sign up")
5. Local dev: MemoryStorage fallback when TIGRIS_BUCKET not set
6. Design system updated: container/grouping rules, card nesting anti-patterns, step number spec
7. CLAUDE.md: design system reference added to top-level read list, 7 new mistake entries
8. Review fixes: region expansion in scorer, getattr cleanup, sync test, constants extraction, request budget warning

**Not yet done:**
- Email Mihai about the 429 fix + new design
- PostHog dashboard setup (funnels, error rates)
- Verify PostHog in production (network tab → /ingest requests)

## 2026-04-04 — New + Viewed states, design system enforcement

**What got done:**
1. **New + Viewed job states**: `run_id` column on jobs (set during scoring), `viewed_at` column (set on card expand via PATCH endpoint). `is_new` = job's run_id matches latest non-failed run. Replaces broken `brief_count` logic. `brief_count` deprecated.
2. **Read/unread visual treatment**: Unread = bold title + darker text. Read = normal weight + slightly muted. Email inbox pattern. Read ≠ Closed (different axes).
3. **Tab rename**: "New" → "Inbox" (display only, wire format unchanged).
4. **Optimistic status updates**: Save/skip/applied update UI immediately, API fires in background. Reverts on failure. Counts update optimistically too.
5. **Clearable badges**: All user-set status badges (Saved/Applied/Skipped/Closed) show × on hover. Uses `invisible` + absolute overlay to prevent layout jump.
6. **Design system §8 Interaction Patterns**: Added to `web/DESIGN.md` — optimistic updates, state axes, read/unread treatment, clearable badges, hover content swap technique.
7. **Design system audit**: All pages/components audited against spec. Fixed 10 deviations (selects, dividers, cursor-pointer, header alignment, empty states, pagination arrows, RunButton sizing, skeleton baseline).
8. **Generic design system skill**: Created `~/.pi/agent/skills/design-system/SKILL.md` — 7-step process for creating and enforcing design systems across any project.
9. **Migration 008**: `viewed_at` + `run_id` columns, index on `(user_id, run_id)`.
10. **10 new tests** in `tests/api/test_viewed_and_new.py` (598 total).

**Decisions made:**
- Wire format stays `new`/`counts.new` — "Inbox" is display-only rename
- Re-scored jobs reset `viewed_at` to NULL (new content = unread)
- Read styling: `font-normal text-gray-700` (not gray-600, which was too close to closed)
- `brief_count` deprecated but not dropped (no migration needed)

**What's next:**
- Email Mihai about the 429 fix + new design
- PostHog dashboard setup
- Run a pipeline to verify `run_id` gets set on scored jobs in production

## 2026-04-03 (session 3) — UX polish: unsave, history, profile continuity

**What got done:**
1. Unsave/unreact: added `clear` status to API, clicking active status button toggles it off
2. Profile page continuity: single `divide-y` for all steps, AnalyzeButton inline, phase divider removed
3. Save button disabled when profile is clean (dirty state controls enabled/disabled)
4. History page rewrite: shows stats (collected → scored → matches), duration, per-source expansion, null handling, running state
5. Design system docs updated with container/grouping rules

**Key decisions:**
- `clear` status mapped to `user_status = None` in DB (not a new column)
- SaveBar stays mounted always (hiding causes layout shift from pb-28)
- History page needs no backend changes — progress dict already has all data
- Fragment children inside `divide-y` flatten correctly for CSS `* + *` selector

**Test count:** 444 passed (+9 new), 1 pre-existing failure (test_aww_client)

**Additional commits (same session):**
6. is_closed toggle: separate boolean from user_status, migration 007, toggle button in expanded action bar, red badge on collapsed row, dimmed treatment
7. Hover feedback on active status buttons (hover:bg-emerald-100 + cursor-pointer)

---

## 2026-04-03 — International support (country, region, currency)

**What got done:**
1. `country` field on `LocationFilter` — flows from frontend → profile JSON → worker → pipeline → LinkedIn collector + scorer prompt
2. LinkedIn collector: `location` param configurable (was hardcoded "United States"), `f_WT` derived from user's remote/local_cities prefs (4-way matrix)
3. Multi-country region expansion: DACH (3), Scandinavia (4), EU (10), Europe (10), APAC (7), LATAM (6) — 1 page per country to cap request count
4. Currency-aware scorer prompt: salary requirement + estimate format use user's currency, cross-currency conversion instruction
5. Location requirement respects `remote` flag: "Remote in Germany" vs "In Germany" vs "Near Berlin in Germany" (8 combinations)
6. Searchable Combobox component: 55 countries + 6 regions, flag emojis, keyboard nav, type-to-filter (searches descriptions too)
7. Region descriptions visible in dropdown + below combobox when selected ("Searches: Germany, Austria, Switzerland")
8. 11 currencies with symbols (USD, GBP, EUR, CAD, AUD, INR, SGD, CHF, SEK, JPY, ILS)
9. Deployed to Fly.io

**Key decisions:**
- Empty `country` = "United States" (backward compat in pipeline, not in config default)
- Regions capped at ~10 countries each to keep LinkedIn requests ≤30 per run
- 1 page per country for multi-country (vs 2 for single) — breadth over depth
- Dedup by job ID across countries (existing `_seen_ids` mechanism)
- NextPlay kept for all users (ATS pages are global, not US-only)
- LinkedIn guest API verified for 9 countries + region strings (DACH, Europe, EU, APAC, LATAM all return results)

**Test count:** 430 passed (+27 new), 1 pre-existing failure (test_aww_client)

---

## 2026-04-02 — Design overhaul, posted_at, matches page UX

**What got done:**
1. Full design overhaul: zinc neutrals, emerald-600 accent, Outfit + JetBrains Mono fonts, Phosphor icons
2. All components restyled: Nav (frosted glass), AuthForm, JobCard, RunButton, OnboardingChecklist, Skeleton, etc.
3. Landing page: asymmetric hero, interactive demo with 4 expandable mock jobs
4. Getting Started page: provider cards (Gemini recommended), step-by-step, FAQ, signup CTA
5. `posted_at` field: RawJob → collectors (HN, LinkedIn, Greenhouse, Lever) → DB migration 006 → API → frontend
6. NextPlay cache bug fix: `j.salary` → `j.salary_text`, `_raw_job_from_cache_dict()` for old/new cache compat
7. Company intel on collapsed rows with labeled fields (Stage:, Glassdoor X/5, Growth:)
8. Matches page redesign: 3-zone layout (title+salary / company+location+badges / condensed intel)
9. Quick-action buttons: save/skip icons fade in on hover, no expand needed
10. Status filter pills: All · New (12) · Saved (8) · Applied (3) · Skipped — with backend counts
11. Action bar moved to top of expanded view, Tools section merges resume + cover letter
12. User status badges visible on collapsed rows (Saved/Applied/Skipped)
13. DNS fix: Cloudflare CNAME for shortlist.addslift.com, SSL Full (strict)

**Bugs fixed:**
- NextPlay cache serialization: `j.salary` (doesn't exist on RawJob) → `j.salary_text`
- NextPlay cache deserialization: old format `salary` key → mapped to `salary_text`
- Pipeline crash: `CompanyIntel.from_json()` dict handling (from prior PR)
- Nested button HTML: collapsed row changed from `<button>` to `<div role="button">` for valid quick-action buttons
- Layout shift on saved rows: quick-action column always rendered (opacity toggle, not conditional)

**Key decisions:**
- Emerald accent over blue — "go signal" for curation tool
- Zinc over stone — cool, consistent temperature
- Centered hero banned (DESIGN_VARIANCE 8) — asymmetric grid
- No framer-motion — CSS sufficient at MOTION_INTENSITY 6, saves ~40KB + RAM on 512MB VM
- Reasoning removed from collapsed rows — editorial content belongs in expanded view
- Source (`via hn`) moved to expanded action bar — low scan value on collapsed row
- Track shown as badge on identity line, not separate line
- Salary right-aligned on first line — visual anchor like a financial dashboard
- `user_status=new` → `IS NULL` in backend, not `is_new` (brief_count)
- Counts computed server-side (not from current page data)

**Test count:** 542 passed (+15 new), 1 pre-existing failure (test_aww_client)

**Design system:** `web/DESIGN.md` — full reference for palette, typography, components, layout, anti-patterns

---

## 2026-04-02 — PostHog overhaul, pipeline crash fix, LLM retry, location scoring

**What got done:**
1. PostHog proper init (`posthog.ts`) with `capture_pageview: "history_change"`, session recording (`maskAllInputs`), reverse proxy
2. User identification: `posthog.identify()` on login/signup/hydration, `posthog.reset()` on logout
3. Activation milestones: `setPersonProperties()` on 5 events (has_resume, has_api_key, profile_complete, has_run, has_completed_run)
4. Pipeline crash fix: `CompanyIntel.from_json()` now accepts both str (SQLite) and dict (PG JSON column)
5. Pipeline resilience: try/except around enrichment + interest note loops — one bad job can't kill a run
6. LLM retry: `_retry_on_transient()` with 2 retries + exponential backoff (2s, 4s) for 429/5xx
7. 429 error UX: actionable message suggesting Gemini, amber warning instead of red
8. Location scoring: prompt now includes local_cities + instruction to penalize country-restricted remote roles
9. RunButton: fires `runFailed` on polling catch, retroactive `run_completed` with sessionStorage dedup

**Test count:** 527 passed (+10 new), 1 pre-existing failure (test_aww_client)

---

## 2026-03-25 — Score reasoning on cards, PostHog report tool, memory optimization

**What got done:**
1. Surfaced `score_reasoning` on collapsed job cards — moved from `JobDetail` to `JobSummary`, one-line truncated display via `line-clamp-1`
2. Built generic PostHog report script at `~/Code/adamlab/scripts/posthog_report.py` — works for any project, config-driven registry, HogQL queries
3. Memory optimization for 512MB Fly VM: Node.js heap capped at 192MB, uvicorn recycles after 10k requests

**Test count:** 517 passed, 1 pre-existing failure (test_aww_client)

---

(older entries truncated for brevity — see git history)
