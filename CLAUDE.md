# CLAUDE.md

**Read `PROJECT_LOG.md` first** — current state, session history, what's next.
**Read `INTENT.md`** — what this project values, scoring philosophy, decided tradeoffs.
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
pytest tests/ -q           # 496 tests, ~22s
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
| Pages | `app/{page,login,signup,profile,history}/page.tsx` |
| Components | `components/{JobCard,RunButton,OnboardingChecklist,Nav,...}.tsx` |
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
| `jobs` | Scored jobs (fit_score, enrichment, interest_note, cover_letter, career_page_url, tailored_resume_key, tailored_resume_pdf_key) |
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

- **496 tests**, ~22s, all unit tests
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

**VM:** shared-cpu-2x / 1024MB  
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
