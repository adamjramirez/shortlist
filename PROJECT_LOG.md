# PROJECT_LOG.md — Shortlist

Session-by-session progress log. Read this first when resuming work.

---

## Current Focus

**Web UI close-the-gap features shipped.** All 3 batches deployed + cover letter generator.

**Not yet done:**
- Cron/launchd for overnight runs

**TODO — Tracking & Observability:**
- Add PostHog event tracking for cover letter generation (model used, job_id, word count, generation time, QA pass time)
- Add PostHog event tracking for resume tailoring (job_id, generation time, success/fail)
- Add PostHog event tracking for profile generation (resume_id, generation time)
- Dashboard in PostHog: cover letter generation volume, model popularity, failure rate
- Track which banned phrases the post-processor catches (to improve the prompt over time)

---

## 2026-03-12 — Close the gap: web UI vs CLI brief

**What got done:**
1. Batch 1: Interest pitch (`interest_note` on jobs, `generate_interest_note()`, pipeline wiring, API, JobCard "Why you might be interested")
2. Batch 1: New/seen badges (`is_new` via `brief_count`, green "New" tag, worker increments on run complete)
3. Batch 2: Direct ATS links (`get_career_url_for_domain()` from nextplay_cache, `career_page_url` on jobs, "Apply Direct →" button)
4. Batch 3: Tailored resume (`tailor_resume_from_text()` DRY wrapper, POST/GET endpoints, Tigris storage, frontend download via fetch+blob)
5. Cover letter generator — 3-layer pipeline: generate → QA pass → post-processor
6. Per-provider API keys — store multiple keys, model selector dropdown on cover letter button
7. Fixed LaTeX extraction — complete rewrite handles fontspec, tabular*, custom commands
8. Fixed profile generator — added all 7 models to PROVIDERS + _CALLERS dicts
9. Fixed JSON parsing — LaTeX backslashes (\$) in LLM responses no longer break parsing
10. Fixed resume picker — was selecting template over real resume (scalar_one_or_none bug)
11. Cover letter logging — extraction quality, QA corrections, post-processor catches

**Bugs found & fixed:**
- Tailor endpoint: LLM not configured (needed user's API key from profile)
- Resume download: `<a href>` can't send JWT → switched to fetch+blob
- Profile generator: `_CALLERS` and `PROVIDERS` only had 3 of 7 models
- Resume picker: `scalar_one_or_none()` returns None with multiple resumes → `.first()`
- Cover letters full of "Company Name" placeholders → root cause was template resume being picked + bad LaTeX extraction

**Key decisions:**
- Cover letter QA as 2nd LLM pass — catches what prompts can't enforce
- Post-processor as deterministic safety net — banned phrase replacement
- Resume picker prefers largest file when multiple exist (templates are tiny)
- Per-provider keys stored in `config.llm.api_keys` dict, backward-compat with `encrypted_api_key`

---

## 2026-03-10 — Delivery cleanup + public release

**What got done:**
1. Assessed delivery readiness — found 5 minor issues
2. Removed hardcoded `75098` zip fallback in scorer (now empty string)
3. Fixed DFW-specific comment in filter to generic "local area"
4. Removed personal `config/profile.yaml` from git tracking, added to `.gitignore`
5. Fixed README Python version (3.12 → 3.11 to match pyproject.toml)
6. Added `uv.lock` to `.gitignore`
7. Purged `config/profile.yaml` from entire git history with `git-filter-repo` (contained personal career details, DFW cities, fit_context)
8. Force-pushed cleaned history to GitHub
9. Made repo public: https://github.com/adamjramirez/shortlist

**Decisions:**
- No PyPI — GitHub repo is sufficient for distribution. Code is visible either way.
- No secrets were ever committed (only placeholder API key examples)
- Personal config (profile.yaml) was the only sensitive data in history — now purged

---

## 2026-03-10 — Full build from scratch

### Phase 1: Foundation
- Project scaffolding: pyproject.toml, DB schema (6 tables), config loader (profile.yaml), CLI
- Base collector protocol (`RawJob`, `BaseCollector`, `description_hash` SHA-256 dedup)
- HN Who's Hiring collector via Algolia API (420 jobs from March thread)
- Hard filters: location (remote/DFW), salary (reject only if explicitly <$250k), role type (reject explicit IC)
- Location filter sanity: `_looks_like_location()` prevents false rejections on garbage location fields
- Brief generator with 🆕/👁️/📈/⏰ markers, filtered-out summary, tracker, source health
- Full pipeline orchestration: `shortlist run/collect/brief/today/status/health`

### Phase 2: Scoring + LinkedIn
- Gemini 2.5 Flash scoring via `google-genai`. `build_scoring_prompt()`, `parse_score_response()`, `score_job()`.
- LinkedIn guest API collector — unauthenticated, 9 searches covering VP/EM/AI/CTO tracks, 429 retry with 30s backoff.

### Phase 3: NextPlay + Career Pages
- `shortlist/http.py` — centralized rate-limited HTTP. ALL external requests go through it.
- ATS parsers: Greenhouse (JSON API), Lever (JSON API), Ashby (GraphQL + N+1 detail fetches).
- NextPlay Substack RSS → extract ATS links + discover ATS from company websites.
- Refactored all collectors and scorer to use `shortlist.http`.

### Phase 4: Resume tailoring
- 4 LaTeX CVs in `resumes/`: ai.tex, em.tex, vp_enterprise.tex, vp_growth.tex.
- `processors/resume.py`: LLM-based resume selection (picks between VP variants), Gemini-powered tailoring (surgical changes only), saves `.tex` + `.note.md`.
- Parallelized tailoring with ThreadPoolExecutor(10): 30 resumes in 141s (was ~22 min sequential).
- Fixed LaTeX escape chars breaking JSON parsing — escape-fixer + regex field extraction fallback.

### Phase 5: Enrichment + Discovery
- Company enrichment via Gemini: stage, headcount, funding, Glassdoor, growth/OSS signals. Cached 30 days.
- `rescore_with_enrichment()` adjusts scores ±20 based on intel.
- Job board detection (`is_job_board()`) skips enriching aggregators.
- Parallel scoring: ThreadPoolExecutor(10), 416 jobs in 8.5 min (was 33 min at 4s rate limit).
- ATS discovery from company websites — visit homepage → follow /careers → detect ATS from HTML/redirects/JSON-LD.
- Pipeline Step 4b: after enrichment, probe companies with domains for ATS boards, fetch new jobs.
- Slug fallback: try company domain as Greenhouse/Lever slug when website discovery fails. Found Affirm (162 jobs) and Nerdy (44 jobs).
- Gemini rate limit dropped from 4.0s to 0.5s — verified no 429s.

### Phase 6: Polish
- Company name normalization: career page fetchers use proper names (Greenhouse board name API), fixed 418 slug-cased jobs in DB.
- Brief dedup: merge same-company/same-title listings across sources, show alternate links. 49→42 matches.
- Recruiter flagging: 🔍 marker on recruiter/aggregator listings. `is_job_board()` prefix matching for long company names. 13 of 42 flagged.
- Location filter fix: check title for "remote" (not just location field + description). Recovered 4 false rejections.
- `--no-collect` flag on `shortlist run` to skip collection when processing existing data.
- Created INTENT.md, PROJECT_LOG.md, CLAUDE.md (this session).

### Decisions made
- Google Jobs scraping blocked — Decodo proxy can't HTTPS CONNECT tunnel. Tried multiple approaches, all fail.
- JS-rendered career pages (Atlassian, Shopify, GitLab, etc.) can't be discovered without Playwright — only ~5 companies affected, 1 LinkedIn listing each is sufficient.
- Recruiter listings are valid — flag don't filter. They represent real jobs behind anonymized company names.
- Description-similarity dedup for recruiter→direct matching set at 50% threshold — only one real duplicate found (Jobgether/Posit). Lower thresholds produce false positives from shared tech vocabulary.

### Key numbers
- **963 jobs** in DB (HN 420, LinkedIn 126, NextPlay/career pages ~417)
- **185 rejected** by hard filters, **707 low-score**, **71 scored ≥60**
- **42 deduped top matches** in brief (29 direct, 13 recruiter-flagged)
- **50 tailored resumes** generated
- **256 tests** passing in 0.4s

### What's next
1. Set up cron/launchd for overnight pipeline runs
2. Score the 4 recovered location-filter jobs
3. Consider adding more sources (Indeed, BuiltIn, etc.) if current yield drops
