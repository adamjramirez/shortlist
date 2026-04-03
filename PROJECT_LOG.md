# PROJECT_LOG.md — Shortlist

Session-by-session progress log. Read this first when resuming work.

---

## Current Focus

**Design overhaul + UX improvements deployed.** Full visual redesign (zinc/emerald), posting dates from sources, matches page UX (quick actions, status filters, action bar). DNS fixed for shortlist.addslift.com. Getting Started page for onboarding.

**Not yet done:**
- Email Mihai about the 429 fix + new design
- PostHog dashboard setup (funnels, error rates)
- Verify PostHog in production (network tab → /ingest requests)
- Test authenticated flow end-to-end with new design

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
