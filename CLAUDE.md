# CLAUDE.md

**Read `PROJECT_LOG.md` first** — current state, session history, what's next.
**Read `INTENT.md`** — what this project values, scoring philosophy, decided tradeoffs.
**Read `web/DESIGN.md` before any frontend/design work** — palette, typography, container rules, anti-patterns. This is the design system.
**Adam's profile:** `~/Code/profile/` — career context, health, identity. CVs live in `shortlist/cv-new/`.

---

## Workflow

TDD per `~/.pi/agent/skills/build/SKILL.md`. Test first, watch it fail, make it pass, refactor.

### Commands

```bash
# CLI (frozen on SQLite — don't maintain alongside web)
shortlist run              # Full pipeline
shortlist brief            # Generate today's brief

# Web (primary development path)
cd web && npm run dev      # Frontend dev server (port 3000)
uvicorn shortlist.api.app:create_app --factory --port 8001  # Backend

# Tests
pytest tests/ -q           # 644 tests, ~31s
cd web && npm run build    # Frontend type check + build

# Deploy
fly deploy --app shortlist-web
```

---

## Stack

### Web (primary)
- **FastAPI** + **SQLAlchemy** async — backend API at `shortlist/api/`
- **Next.js 14** App Router + Tailwind — frontend at `web/src/`
- **PostgreSQL** on Fly.io — `shortlist-db`
- **Tigris** (S3-compatible) — resume storage
- **supervisord** — runs FastAPI (:8001) + Next.js (:3000) in one container
- **PostHog** (EU) — 26 custom events via reverse proxy (`web/src/lib/analytics.ts`)

### CLI (frozen)
- **SQLite** — `jobs.db` (gitignored)
- **Click** CLI

### Shared
- **Gemini 2.0 Flash** (default) — scoring, enrichment, interest notes, cover letters
- **Per-provider API keys** — users can configure Gemini + OpenAI + Anthropic
- **subprocess+curl** for Gemini LLM calls — httpx/urllib crash in asyncio.to_thread on Fly.io
- **Decodo proxy** — residential proxy rotation for LinkedIn (6 endpoints)

---

## Architecture

### Web Pipeline Flow

```
User clicks "Run now"
  → worker.py: asyncio.to_thread(run_pipeline_pg)
  → Parallel source collection (HN, LinkedIn, NextPlay via queue.Queue)
  → Per-source: collect → filter → score → enrich → interest notes → save to PG
  → Results appear incrementally in UI
```

### Backend Structure

| Area | Files |
|------|-------|
| API core | `api/{app,auth,schemas,models,db,deps,crypto}.py` |
| Routes | `api/routes/{auth,profile,resumes,runs,jobs,tailor}.py` |
| Worker | `api/worker.py` (in-process, max_jobs_per_run=150) |
| Storage | `api/storage.py` (Tigris prod, InMemory test) |
| LLM client | `api/llm_client.py` (profile generation — 7 models registered) |
| Pipeline | `pipeline.py` (`run_pipeline_pg()` — PG-native) |
| PG layer | `pgdb.py` (sync psycopg2, nextplay_cache CRUD) |
| LLM | `llm.py` (subprocess+curl for Gemini, `json_schema` optional param) |
| Collectors | `collectors/{hn,linkedin,nextplay,career_page}.py` |
| Processors | `processors/{filter,scorer,enricher,resume,cover_letter,latex_compiler}.py` |

### Frontend Structure

| Area | Files |
|------|-------|
| Pages | `app/{page,login,signup,profile,history,getting-started}/page.tsx` |
| Components | `components/{JobCard,RunButton,OnboardingChecklist,Nav,SectionCard,ResumeUploader,AiProviderForm,AnalyzeButton,SaveBar,Combobox,FiltersEditor,TrackEditor,...}.tsx` |
| API client | `lib/api.ts` (fetch wrapper with JWT) |
| Types | `lib/types.ts`, `lib/profile-types.ts`, `lib/constants.ts` |
| Analytics | `lib/analytics.ts` (26 PostHog events — actions + errors + onboarding) |
| Auth | `lib/auth-context.tsx`, `lib/use-require-auth.ts` |

### DB Tables (PostgreSQL)

| Table | Purpose |
|-------|---------|
| `users` | Auth (email, bcrypt password hash) |
| `profiles` | JSON config (fit_context, tracks, filters, llm keys) |
| `resumes` | Metadata + S3 key to Tigris (`resume_type`: tex/pdf, `extracted_text_key` for PDFs) |
| `runs` | Pipeline runs (status, progress JSON, timestamps) |
| `jobs` | Scored jobs (fit_score, enrichment, interest_note, cover_letter, career_page_url, tailored_resume_key, tailored_resume_pdf_key, posted_at, is_closed, user_status, viewed_at, run_id) |
| `companies` | Enrichment cache (30-day TTL) |
| `nextplay_cache` | System-level ATS discovery cache (24h TTL, shared across users) |

### PDF Resume + LaTeX Compilation

```
PDF user uploads .pdf
  → PyMuPDF extracts text → stored as .txt alongside original
  → Tailor: generate_resume_from_text() → full LaTeX from template
  → compile_latex() → tectonic → PDF cached in storage

LaTeX user uploads .tex
  → Tailor: tailor_resume_from_text() → surgical edits preserving structure
  → Download PDF: make_portable() strips fontspec/custom fonts
    → substitutes Latin Modern OTF → compile_latex() → PDF
  → Download .tex: original with custom fonts preserved
```

**`make_portable()`** (`latex_compiler.py`): transforms any LaTeX for tectonic compilation
- Strips `fontspec`, `\setmainfont`, `\fontspec{...}`, `\addfontfeatures{...}`
- Substitutes Latin Modern OTF fonts (lmroman10-regular.otf etc.)
- Fixes double-escaped backslashes from JSON fallback parser
- Reconstructs mangled `\noindent` (from `\n` escape consuming the `n`)
- Unescapes LaTeX special chars (`\\&` → `\&`)

**`_extract_tailor_fields()`** (`resume.py`): JSON fallback when LaTeX breaks `json.loads`
- Unescape order matters: `\\` → `\` BEFORE `\n` → newline

### Key Patterns

- **Protocol + fake for all deps** — Storage, ProfileGenerator, DB session
- **Profile merge semantics** — PUT /profile merges, doesn't replace
- **`flag_modified()` on JSON columns** — SQLAlchemy won't detect dict mutation
- **subprocess+curl for Gemini** — httpx sync crashes in asyncio.to_thread on Fly.io
- **Cancel via threading.Event + DB polling** — flush loop checks DB every 2s
- **Rate limiter slot reservation** — lock held microseconds, not during sleep
- **Per-source scoring budget** — `remaining // sources_left`, minimum 20 per source
- **Score threshold 75 for visibility** — SCORE_SAVED=60 (DB), SCORE_VISIBLE=75 (API), SCORE_STRONG=85
- **`score_reasoning` in JobSummary** — visible in expanded view (moved from collapsed to reduce density)
- **`is_new` based on `run_id`** — job's `run_id` matches user's latest non-failed/cancelled run. Replaces old `brief_count == 0` logic. `brief_count` deprecated (still in schema, no longer incremented).
- **`viewed_at` for read/unread** — set via `PATCH /api/jobs/{id}/view` (fire-and-forget from frontend). Reset to NULL when job is re-scored in a new run. Read = `font-normal text-gray-700`, Unread = `font-semibold text-gray-900`.
- **Optimistic status updates** — `handleStatus` updates local state immediately, fires API in background. On failure, sends `__refresh` to parent to refetch. Parent does optimistic count updates too.
- **Clearable badges** — user-set badges (Saved/Applied/Skipped/Closed) are `<button>` with hover-to-× behavior using `invisible` + absolute overlay. System badges (New/Recruiter) are inert `<span>`.
- **Tab rename: New → Inbox** — display-only. Wire format still `?user_status=new` and `counts.new`. "Inbox" = untriaged (user_status IS NULL), "New" pill = from latest run.
- **`posted_at` on RawJob/DB/API** — actual posting date from source (HN, LinkedIn, Greenhouse, Lever). Normalized to ISO 8601 at collector level.
- **Design system** — `web/DESIGN.md` is canonical. Zinc neutrals, emerald-600 accent, Outfit + JetBrains Mono. No blue, no stone, no emoji, no framer-motion. Includes interaction patterns (§8): optimistic updates, read/unread treatment, clearable badges, state axes.
- **`is_closed` separate from `user_status`** — a job can be saved AND closed. `user_status` = user intent (saved/applied/skipped), `is_closed` = job availability. Toggle via `status="closed"` on the same PUT endpoint.
- **Status toggle pattern** — PUT `/jobs/{id}/status` with `"clear"` resets `user_status` to null, `"closed"` toggles `is_closed`. Same endpoint, different fields.
- **Profile page structure** — single `divide-y` for all steps (1-6). Steps 3-6 conditionally rendered inside fragment. AnalyzeButton inline with `py-6` wrapper. SaveBar fixed at bottom, disabled when `!dirty`.
- **JobListResponse.counts** — `{new, saved, applied, skipped}` computed server-side for status filter pills
- **Quick actions on hover** — save/skip icons fade in via `group-hover:opacity-100`, always rendered (opacity toggle, not conditional) to prevent grid layout shift
- **PostHog person properties for activation** — `setPersonProperties()` on 5 milestones (has_resume, has_api_key, profile_complete, has_run, has_completed_run) for cohort analysis
- **LLM retry with `_retry_on_transient()`** — coro_factory pattern, 2 retries + exponential backoff, only 429/5xx
- **Per-item try/except in pipeline loops** — enrichment + interest note loops catch per-job errors so one failure doesn't kill the run
- **`resolve_*(config, ...)` pattern** — extract business logic from async workers into pure named functions (`resolve_fit_context`, etc.) so they can be unit-tested without any async/DB setup. The worker calls them; the tests import them directly.
- **Supplement-not-replace for external context** — when an external source (AWW, future integrations) can enrich `fit_context`, append with a labelled separator (`## Additional Context (from AWW)\n`) rather than replacing. User's data is always first and always preserved. Toggle via a dedicated boolean (`use_aww_slice`).

### Cover Letter Pipeline (3 layers)

```
1. Generate (LLM call with structured prompt)
   - 4-paragraph format, 250-350 words
   - Uses extracted resume, company intel, interest note, score reasoning
   
2. QA Pass (2nd LLM call)
   - Catches placeholder names, invented numbers, repeated sentences, grammar
   
3. Post-processor (deterministic)
   - Banned phrase replacement (excited→drawn, spearheaded→led, etc.)
   - Logs which phrases were caught
```

### Per-Provider API Keys

Profile config stores:
- `llm.model` — default model for scoring/pipeline
- `llm.encrypted_api_key` — legacy single key (backward compat)
- `llm.api_keys.{gemini,openai,anthropic}` — per-provider encrypted keys
- Cover letter endpoint accepts `model` override, picks matching provider key

---

## Testing

- **644 tests**, ~31s, all unit tests
- All tests mock `shortlist.http._wait` to disable rate limiting
- Pipeline tests mock scoring/enrichment (not individual functions)
- API tests use async SQLAlchemy with in-memory SQLite
- Fake implementations: `FakeStorage`, `FakeProfileGenerator`

---

## Deploy

```bash
fly deploy --app shortlist-web    # Builds Docker, runs Alembic, starts supervisord
fly logs --app shortlist-web --no-tail  # Check logs
fly postgres connect --app shortlist-db --database shortlist_web  # Direct DB access
```

**Fly secrets:** DATABASE_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3, AWS_REGION, BUCKET_NAME, TIGRIS_BUCKET, ENCRYPTION_KEY, JWT_SECRET, FLY_WORKER_TOKEN, PROXY_URL, PROXY_URLS, GEMINI_API_KEY

**VM:** shared-cpu-1x / 512MB  
**Memory tuning:** Node.js capped at 192MB (`--max-old-space-size=192`), uvicorn recycles after 10k requests (`--limit-max-requests 10000`)  
**Domain:** shortlist.addslift.com (CNAME → fly.dev)

---

## Common Mistakes to Avoid

- ❌ Making HTTP calls without going through `shortlist.http` — breaks rate limiting
- ❌ Using `source` column (doesn't exist) — it's `sources_seen` (JSON array)
- ❌ Calling httpx/urllib sync from threads inside asyncio.to_thread on Fly.io — use subprocess+curl
- ❌ Using gemini-2.5-flash for scoring — extended thinking makes it hang 60s+. Use 2.0-flash.
- ❌ Hardcoding JSON schemas in LLM providers — `json_schema` is optional param on `call_llm()`
- ❌ Enriching recruiter companies — waste of an LLM call, they're not the real employer
- ❌ Showing jobs with score < 75 to users — enforce SCORE_VISIBLE at API level
- ❌ Forgetting `flag_modified()` on JSON column mutations in SQLAlchemy
- ❌ Adding new models without updating BOTH `_CALLERS` and `PROVIDERS` in `llm_client.py`
- ❌ Assuming LaTeX resumes parse cleanly — backslashes break JSON, fontspec/tabular break extraction
- ❌ Using `scalar_one_or_none()` when multiple rows possible — use `.scalars().first()`
- ❌ Unescaping `\n` before `\\` in JSON fallback parser — splits `\\noindent` into `\` + newline + `oindent`
- ❌ Using font names like `Latin Modern Roman` with tectonic — use OTF filenames (`lmroman10-regular.otf`)
- ❌ Using T1 fontenc with tectonic — it's XeTeX-based, use fontspec + OTF fonts for Unicode support
- ❌ Doing `tex.replace("\\\\", "\\")` globally — destroys LaTeX line breaks (`\\[14pt]`). Only unescape before letters/special chars
- ❌ Moving a field from child to parent Pydantic model without checking `**summary` spread in child constructor — causes "got multiple values for keyword argument"
- ❌ Setting `--limit-max-requests` too low on uvicorn — health checks (every 10s) count toward the limit. 1000 requests = recycle every 3 hours. Use 10000+.
- ❌ Suggesting infra scaling before optimizing — check traffic first. 5 users don't need 1GB RAM.
- ❌ Using `fly postgres connect` interactively in scripts — hangs. Use `fly ssh console -C` with inline Python instead.
- ❌ Assuming `json.loads()` on PG JSON columns — psycopg2 auto-deserializes JSON columns to dicts. Use `isinstance(data, dict)` guard in any `from_json()` method.
- ❌ Bare `except Exception` around loops with cancel checks — if `_check_cancel()` is inside the try, `CancelledError(Exception)` gets swallowed. Always put cancel checks outside try blocks.
- ❌ Letting one bad job crash the entire pipeline run — wrap per-item LLM/enrichment work in try/except so the run continues.
- ❌ Nesting `<button>` inside `<button>` — invalid HTML, breaks a11y. Use `<div role="button" tabIndex={0}>` for outer, real `<button>` for inner with `stopPropagation`.
- ❌ Using conditional render for hover elements in CSS grid — column collapses when content is removed, causing layout shift. Use `opacity-0 pointer-events-none` instead.
- ❌ NextPlay cache serialization using `j.salary` — RawJob has `salary_text`, not `salary`. Cache dict also needs `_raw_job_from_cache_dict()` for old/new format compat.
- ❌ Showing `first_seen` (crawl time) as "posting date" — misleading. Use `posted_at` from source APIs (HN `created_at`, LinkedIn `<time>`, Greenhouse `updated_at`, Lever `createdAt`).
- ❌ Making frontend design changes without reading `web/DESIGN.md` first — the design system defines container rules, step number styles, card nesting, and anti-patterns. Inventing new visual patterns (filled-circle badges, card-wrapping-card) breaks consistency.
- ❌ Wrapping `SectionCard` in a card when its children already have cards (FiltersEditor, TrackEditor) — creates double-nested borders. Use flat parent + card children, or card parent + flat children. Never both.
- ❌ Duplicating data between frontend and backend without a sync test — region/country lists, config constants. Add a test that parses both sources and compares.
- ❌ Using defensive `getattr` chains in typed Python code — if the function only receives `Config` objects, use direct attribute access. `getattr` hides bugs and is inconsistent with the rest of the codebase.
- ❌ Redirecting signup to an info page (`/getting-started`) instead of the action page (`/profile`) — users lose context and can't find the next step.
- ❌ Building `LocalStorage`/`FileStorage` for local dev when `MemoryStorage` already exists — check what fakes are available before adding new classes.
- ❌ Mixing job state with user intent in one field — `user_status` is user intent (saved/applied/skipped). Job availability (`is_closed`) is a separate boolean. A saved job can become closed.
- ❌ Forgetting hover feedback on toggle buttons — if a button toggles state (e.g. unsave), the active state needs `hover:bg-*` color change AND `cursor-pointer` to signal clickability.
- ❌ Using `hidden`/`inline` swap for hover content — causes layout shift as element width changes. Use `invisible` (keeps layout) + absolute overlay with `opacity-0 → opacity-100`.
- ❌ Making read/viewed state look like closed/disabled — read items reduce weight (`font-normal`) but stay dark (`text-gray-700`). Only closed/skipped get `opacity-40`. These are different axes.
- ❌ Forgetting `cursor-pointer` on `<button>` elements — Tailwind v4 reset removes default pointer cursor. Every clickable button needs explicit `cursor-pointer` (with `disabled:cursor-not-allowed`).
- ❌ Making UX decisions without recording them — if you decide "save should be optimistic" or "badges should be clearable on hover", add it to the design system (`web/DESIGN.md` §8) immediately. Decisions not recorded get made differently next time.
- ❌ Designing hover states without considering parent opacity — a badge at `opacity-40` (skipped card) needs a background fill on hover for the × to be visible. Bare text-color changes are invisible at low opacity.
- ❌ Breaking `divide-y` flow with elements between two separate containers — use one `divide-y` parent with conditional children inside, not two `divide-y` blocks with a standalone element between them. Tailwind's `* + *` selector handles conditionally rendered fragments.
- ❌ Using `json || jsonb_build_object` on PostgreSQL `json` columns — the `||` merge operator only works on `jsonb`. The `profiles.config` column is `json`. Use Python read-modify-write (`SELECT config`, mutate dict, `UPDATE profiles SET config = %s`) instead of trying to merge in SQL.
- ❌ Leaving dead local variables after extracting logic to a helper — if `resolve_fit_context(config, aww_content)` reads `fit_context` from config internally, remove any `fit_context = config.get(...)` the caller computed before calling it. Extract means the helper owns the logic.
- ❌ Assuming external context sources (AWW slice) supplement user data — AWW slice was silently replacing `fit_context` with no user visibility. Any external data source that modifies user config needs: (a) an explicit enable/disable toggle, (b) supplement-not-replace semantics, (c) visible indication of what the scorer actually receives.
