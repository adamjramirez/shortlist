# PROJECT_LOG.md — Shortlist

Session-by-session progress log. Read this first when resuming work.

---

## Current Focus

**Profile page UX overhaul + international support review fixes shipped.**

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
- Deploy latest (profile components + UX fixes + review fixes)

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
