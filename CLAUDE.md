# CLAUDE.md

**Read `PROJECT_LOG.md` first** — current state, session history, what's next.
**Read `INTENT.md`** — what this project values, scoring philosophy, decided tradeoffs.

---

## Workflow

TDD per `~/.pi/agent/skills/build/SKILL.md`. Test first, watch it fail, make it pass, refactor.

### Commands

```bash
# Run full pipeline (collect → filter → score → enrich → tailor → brief)
shortlist run

# Skip collection, process existing jobs only
shortlist run --no-collect

# Individual steps
shortlist collect          # Collect from all sources
shortlist brief            # Generate today's brief
shortlist today            # Print today's brief

# Status tracking
shortlist status <company> <status>         # e.g. shortlist status "Posit" applied
shortlist status <id> <status>              # by job ID
shortlist health                             # Source health check

# Tests
pytest tests/ -q                             # 256 tests, ~0.4s
pytest tests/test_filter.py -q               # Just filter tests
```

---

## Stack

- **Python 3.14**, venv at `.venv/`
- **SQLite** — `jobs.db` (gitignored)
- **Gemini 2.5 Flash** — scoring, enrichment, resume tailoring. Key: `GEMINI_API_KEY` in `.env`
- **Decodo proxy** — `PROXY_URL` in `.env` (currently unused — Google Jobs blocked)
- **Click** CLI, **httpx** for HTTP, **google-genai** for Gemini

---

## Architecture

### Pipeline Flow

```
Collect (HN, LinkedIn, NextPlay, Career Pages)
  → Dedup (SHA-256 description hash)
  → Filter (location, salary, role type)
  → Score (Gemini, parallel, 10 workers)
  → Enrich companies (Gemini, cached 30 days)
  → Discover ATS from enriched companies
  → Tailor resumes (Gemini, parallel, 10 workers)
  → Generate brief (markdown)
```

### Key Files

| Area | Files |
|------|-------|
| Core | `shortlist/{cli,pipeline,db,config,brief,http}.py` |
| Collectors | `collectors/{base,hn,linkedin,nextplay,career_page}.py` |
| Processors | `processors/{filter,scorer,resume,enricher}.py` |
| Config | `config/profile.yaml`, `.env` |
| Resumes | `resumes/{ai,em,vp_enterprise,vp_growth}.tex` |
| Drafts | `resumes/drafts/` (tailored `.tex` + `.note.md` files) |
| Briefs | `briefs/YYYY-MM-DD.md` |

### DB Tables

| Table | Purpose |
|-------|---------|
| `jobs` | All collected jobs. Status: new→filtered→scored/low_score/rejected. Has fit_score, enrichment, tailored_resume_path. |
| `companies` | Enrichment cache. Domain, stage, headcount, ATS platform, Glassdoor. 30-day TTL. |
| `sources` | Collector registry (hn, linkedin, nextplay). |
| `source_runs` | Per-source run logs. |
| `crawled_articles` | NextPlay article URL cache. 7-day TTL. |
| `probe_cache` | Negative ATS lookup cache. |
| `run_logs` | Pipeline execution logs. |

### HTTP & Rate Limiting

**All external requests go through `shortlist/http.py`.** No direct httpx/requests calls anywhere else.

Domain limits in `DOMAIN_LIMITS`:
- Gemini: 0.5s
- Greenhouse/Lever/Ashby/LinkedIn/Substack: 2s
- HN Algolia: 1s
- Default: 2s

### ATS API Patterns

| ATS | Endpoint | Notes |
|-----|----------|-------|
| Greenhouse | `GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | Board name via `/v1/boards/{slug}` |
| Lever | `GET api.lever.co/v0/postings/{slug}` | Returns array. HTML responses = invalid slug. |
| Ashby | `POST jobs.ashbyhq.com/api/non-user-graphql` | GraphQL. 406 = org doesn't exist (handled silently). |

### ATS Discovery

`career_page.py` has two strategies:
1. Visit company website → follow /careers → detect ATS from HTML/redirects/JSON-LD
2. Try domain slug directly on Greenhouse/Lever (`_probe_greenhouse`, `_probe_lever`)

### Parallel Processing

- `score_jobs_parallel()` — ThreadPoolExecutor(10), DB writes on main thread after
- `tailor_jobs_parallel()` — Same pattern. 2 LLM calls per job (select + tailor).
- Tests mock these at the pipeline level, not individual functions.

### Recruiter Detection

`enricher.py` has `JOB_BOARD_COMPANIES` set + `is_job_board()` with prefix matching. Used for:
- Skipping enrichment (don't enrich Jobgether, they're not the real employer)
- Brief 🔍 marker
- Brief dedup (recruiter listings matching direct listings by >50% description overlap get merged)

---

## Testing

- **256 tests**, ~0.4s, all unit tests
- All tests mock `shortlist.http._wait` to disable rate limiting
- Pipeline tests mock `score_jobs_parallel` and `tailor_jobs_parallel` (not individual functions)
- Pipeline tests mock `enrich_company` to skip LLM calls

---

## Common Mistakes to Avoid

- ❌ Making HTTP calls without going through `shortlist.http` — breaks rate limiting
- ❌ Using `source` column (doesn't exist) — it's `sources_seen` (JSON array)
- ❌ Assuming career page company names are proper-cased — Greenhouse API returns proper name, Lever/Ashby use slug. Pass `company_name` param.
- ❌ JSON-parsing Gemini responses with raw LaTeX — backslashes break `json.loads()`. Use `_parse_json()` which has escape-fixing fallbacks.
- ❌ Filtering too aggressively — permissive filters, let the scorer handle nuance
- ❌ Enriching recruiter companies — waste of an LLM call, they're not the real employer

---

## Environment

```bash
# .env (gitignored)
GEMINI_API_KEY=...
PROXY_URL=http://...@gate.decodo.com:10001    # Currently unused
SUBSTACK_SID=...                                # For NextPlay auth

# Config
config/profile.yaml   # max_jobs_per_run: 500, top_n: 30, track definitions
```

---

## Known Limitations

- **Google Jobs:** Proxy can't HTTPS tunnel. No workaround found.
- **JS-rendered career pages:** Atlassian, Shopify, GitLab, Zillow, Docusign use custom platforms. Would need Playwright.
- **LinkedIn guest API:** Unauthenticated, fragile, may break anytime. Returns max ~25 results per search.
- **NextPlay source_run logging:** `_log_source_run` not firing (shows "last run: never").
- **Recruiter dedup:** Only catches >50% description overlap. Most recruiter listings are too anonymized to match reliably.
