# PROJECT_LOG.md — Shortlist

Session-by-session progress log. Read this first when resuming work.

---

## Current Focus

**AWW toggle shipped. Updating fit_context from ~/Code/profile/ next.**

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
