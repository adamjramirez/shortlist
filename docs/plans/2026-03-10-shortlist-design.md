# Shortlist — Design Document

**Date:** 2026-03-10
**Status:** Approved
**Author:** Adam + Claude

---

## What Is This

A personal job search automation system that runs overnight and produces a curated daily markdown briefing. It finds jobs, filters out noise, scores fit, enriches with company intel, drafts tailored resume materials, and surfaces only decisions to you.

**Time budget:** 15 min/day reviewing the morning brief.

**Everything else is automated.**

---

## Target Roles

| Track | Title Range | Notes |
|-------|------------|-------|
| EM | Engineering Manager at large orgs | 20+ reports |
| AI | AI-focused roles at strong companies (e.g. LangChain) | IC-lead or EM |
| VP | VP Engineering at Series B+ | Executive scope |

---

## Requirements Profile

### Hard Filters (auto-reject)

| Requirement | Value |
|-------------|-------|
| Location | Remote OR within 30 min of 75098 (McKinney, TX) |
| Salary | Only reject if salary is explicitly listed AND max < $250k. No salary listed = pass through. |
| Role type | Only reject if **explicitly** IC ("this is an individual contributor role", "no direct reports"). Ambiguous = pass through. |

Note: Most $250k+ roles don't list salary. The hard filter only catches the obvious misses. Real salary assessment happens in the LLM scoring step via level/stage/location inference.

Note: Management scope (20+ reports, team size, etc.) is assessed by the LLM scorer, not the hard filter. Too many JDs describe management roles without using the words "manage" or "direct reports" — they say "lead", "build the team", "grow the org". The hard filter only rejects roles that are **unambiguously IC**.

### Soft Scoring (rank higher/lower)

| Factor | Direction |
|--------|-----------|
| Salary estimate (inferred) | Score against $250k floor using Levels.fyi data, company stage, role level |
| Equity | Nice to have; weight depends on stage + salary + growth |
| Travel | Less is better |
| Series A w/ fresh funding | Yellow flag — score down, don't auto-reject |
| Company growth trajectory | Higher = better |
| Eng culture signals | Blog, OSS, Glassdoor, tech talks |
| Team size / scope | Bigger scope relative to company = better |
| Career growth potential | Upward trajectory visible |

---

## Sources

| Source | Method | Collector Type | What It Covers | Frequency |
|--------|--------|---------------|---------------|-----------|
| **Google Jobs** | Playwright + mobile proxy (JS-rendered) | **Browser** | Aggregates LinkedIn, Indeed, Glassdoor, company pages | Daily |
| **NextPlay Substack** | httpx → extract companies → crawl career pages | Simple | Curated fast-growing startups | Weekly (on new articles) |
| **NextPlay Slack** | See investigation notes below | TBD | Real-time community job posts | Daily |
| **HN Who's Hiring** | HN Algolia API (no proxy needed) | Simple | Monthly high-signal tech/AI roles | Monthly (1st of month, ~200-400 comments) |

**Note on HN frequency:** HN Who's Hiring threads drop on the 1st of each month. Between threads, the HN collector returns no new jobs. This is expected. Phase 1 uses HN to prove the pipeline end-to-end with real data (the March 1 thread has ~300 comments to process), but daily briefs won't have fresh HN data until April 1. Google Jobs (Phase 2) provides the daily flow.

### NextPlay Slack — Access Investigation (Phase 1 Blocker)

**Must resolve before building.** Options to investigate:

1. **Slack API token** — if you're a member, you can create a user token and pull channel history via `conversations.history`. Best option.
2. **Slack RSS bridge** — some Slack workspaces expose RSS feeds per channel. Check if NextPlay does.
3. **Slack export** — manual export, then parse. Not automatable.
4. **Email digest** — if Slack sends channel digests, parse those.
5. **Not viable** — if none of the above work, drop this source and compensate with broader Google Jobs queries.

**Action:** Investigate access method in Phase 1. If blocked, deprioritize to Phase 6 or drop.

### Collector Architecture

Two collector types, each source is a config + parser:

| Type | When | Tool |
|------|------|------|
| **Simple** | Public pages, server-rendered HTML, APIs | `httpx` through mobile proxy |
| **Browser** | JS-heavy sites, bot detection, dynamic content | Playwright through mobile proxy |

Adding a new source = writing a parser function. The framework handles proxy rotation, dedup, storage, and error isolation.

### NextPlay Substack (Meta-Source)

This is a **meta-source** — articles list companies, not jobs directly.

Pipeline:
1. Crawl NextPlay Substack articles
2. Extract company names + career page URLs
3. Auto-add career pages to the "direct companies" source list
4. Crawl those career pages for actual job postings

### Career Page Crawling Strategy

Career pages are NOT uniform. Three tiers of support:

| Tier | ATS Platform | Approach | Coverage |
|------|-------------|----------|----------|
| **1 — Structured** | Greenhouse, Lever, Ashby | Dedicated parsers — these have predictable HTML/API patterns | ~60-70% of startup career pages |
| **2 — Semi-structured** | Workday, BambooHR, SmartRecruiters | Playwright + heuristic extraction | ~15-20% |
| **3 — Unstructured** | Custom career pages | LLM extraction as fallback (expensive, slower) | Remainder |

**Build order:** Tier 1 parsers first (Greenhouse + Lever cover most startups). Tier 2 only if needed. Tier 3 as a catch-all but rate-limited.

**ATS detection:** Hit the career page URL, check for known patterns:
- `boards.greenhouse.io/` or `job-boards.greenhouse.io/` → Greenhouse parser
- `jobs.lever.co/` → Lever parser
- `jobs.ashbyhq.com/` → Ashby parser
- Workday URL patterns → Playwright + Workday parser
- Otherwise → Tier 3 LLM fallback (queue, don't block pipeline)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    NIGHTLY CRON (~2-3 AM CT)             │
│                                                         │
│  ┌───────────┐   ┌───────────┐   ┌──────────────────┐  │
│  │  COLLECT   │──▶│  PROCESS   │──▶│     BRIEF        │  │
│  │           │   │           │   │                  │  │
│  │ • Fetch   │   │ • Dedup   │   │ • Rank top N    │  │
│  │   from    │   │ • Filter  │   │ • Render MD     │  │
│  │   sources │   │ • Score   │   │ • Draft resumes │  │
│  │ • Store   │   │ • Enrich  │   │ • Apply actions │  │
│  │   raw     │   │ • Match   │   │ • Update tracker│  │
│  │           │   │   resume  │   │ • Source health  │  │
│  └───────────┘   └───────────┘   └──────────────────┘  │
│       │               │                │                │
│       ▼               ▼                ▼                │
│    jobs.db        jobs.db      briefs/YYYY-MM-DD.md     │
│   (raw jobs)    (scored +       (daily output)          │
│                  enriched)                               │
└─────────────────────────────────────────────────────────┘

Storage:
  jobs.db (SQLite)     — all jobs, scores, status, company cache, run logs
  resumes/             — base resumes by track (em/, ai/, vp/)
  briefs/              — daily markdown outputs
  config/              — profile, filters, source configs
```

### Error Isolation

Each source runs independently. A failure in one source does NOT block others.

Per-source behavior:
- **Success:** jobs collected, `last_run` updated
- **Failure:** error logged to `source_runs` table, pipeline continues with other sources
- **Partial:** some pages scraped, some failed — store what we got, log the gap
- **3+ consecutive failures:** source marked `degraded`, flagged in brief

The daily brief includes a **Source Health** section:
```
## 🔧 Source Health
| Source | Status | Last Success | Jobs Found |
|--------|--------|-------------|------------|
| Google Jobs | ✅ | Today | 34 |
| HN | ✅ | Mar 1 | 12 |
| NextPlay | ⚠️ 2 failures | Mar 8 | 0 |
```

---

## Pipeline Detail

### Step 1: Collect

For each configured source:
1. Fetch new listings since last run
2. Normalize to `RawJob` schema:
   - `title`, `company`, `location`, `url`, `description`, `description_hash`, `salary_text`, `source`, `first_seen`
3. Store in `jobs.db` via upsert (see dedup strategy below)

**Dedup strategy:**
- Primary key: `description_hash` (SHA-256 of normalized description text)
- Secondary match: fuzzy on (company, title) with similarity threshold — catches reposts with minor wording changes
- On conflict: update `last_seen`, append source to `sources_seen` (JSON array), keep earliest `first_seen`
- Same role reposted after 30+ days: treated as new listing (stale window)

This avoids false positives from "Engineering Manager at Google Remote" matching across unrelated teams — the description content differentiates them.

### Step 2: Filter (Hard)

Cheap checks, no API calls:
- **Location:** reject if not remote AND not DFW metro (geocode once, cache)
- **Salary:** reject ONLY if salary is explicitly stated AND max < $250k. No salary = pass through.
- **Title:** reject obvious non-management roles ("Senior Software Engineer", "Staff Engineer", "Intern", "Junior", etc.)
- **Role type:** reject ONLY if explicitly IC ("this is an individual contributor role", "no direct reports"). Ambiguous roles pass through — the LLM scorer assesses management scope, team size, and seniority.

Jobs that pass → `status = 'filtered'`
Rejected → `status = 'rejected'` with reason

### Step 3: Score (LLM)

For each filtered job, single LLM call with:
- Full job description
- Your profile (role tracks, requirements, preferences)
- Scoring rubric (including salary inference instructions)

Output (structured):
- `fit_score`: 0-100
- `matched_track`: em | ai | vp
- `reasoning`: 2-3 sentences on why this score
- `yellow_flags`: list of concerns
- `salary_estimate`: inferred from company stage + role level + location + Levels.fyi data
- `salary_confidence`: low | medium | high

Jobs scoring ≥ 60 → `status = 'scored'`
Below 60 → `status = 'low_score'`

**Cost tracking:** Each run logs total LLM calls, tokens used, and estimated cost to `run_logs` table. Brief includes cost summary.

### Step 4: Enrich

For scored jobs (top N only, to limit API/scraping cost):
- **Company:** stage, last funding, headcount, growth rate (Crunchbase or similar)
- **Culture:** eng blog, Glassdoor rating, tech stack, OSS presence
- **People:** hiring manager name from JD, LinkedIn profile link
- **Connections:** mutual connections (if accessible)

Cached per company — don't re-fetch if already enriched in last 30 days.

### Step 4b: Re-Score (post-enrichment)

Enrichment can reveal score-changing information that wasn't in the JD:
- Series A with fresh funding → yellow flag
- Glassdoor < 3.0 → significant penalty
- Company shrinking (negative headcount growth) → penalty
- Strong eng culture signals → bonus

For each enriched job, a **lightweight re-score** LLM call with:
- Original score + reasoning
- Enrichment data
- "Should this score change? By how much and why?"

Output: `fit_score` (updated), `score_delta`, `rescore_reasoning`

Only re-scores jobs where enrichment contains material new info. If enrichment is thin (just a Glassdoor rating), skip the re-score to save cost. The brief shows score changes: "Score: 78 (↑ from 72 — strong eng culture signals)".

### Step 5: Match Resume + Draft

For top N jobs:
1. Select base resume based on `matched_track`
2. LLM pass: tailor emphasis for this specific role
   - NOT keyword stuffing
   - Reorder bullet points, adjust emphasis, highlight relevant metrics
   - Match language/framing to what the JD values
3. Save tailored version as markdown (PDF generation optional, later)
4. Optional: draft 3-sentence "why I'm interested" note for warm intros / email applies

### Step 6: Generate Brief

Render `briefs/YYYY-MM-DD.md` (relative to project root):

```markdown
# Shortlist — Tuesday, March 10, 2026

> 34 jobs collected | 18 filtered out | 16 scored | 5 top matches
> LLM cost: $0.47 (16 scoring + 5 enrichment + 5 resume drafts)

## 🟢 Top Matches (3 new, 2 seen before)

### 1. 🆕 VP Engineering — Acme AI (Series C, 280 ppl)
**Score: 91** | Remote | Est. $280-320k + 0.15% equity (high confidence)

**Why it fits:** AI-native company, 40-person eng org reporting to you,
Series C = funded through 2028, strong eng blog + OSS presence.

**Yellow flags:** None

**Company intel:**
- Last raised $85M (Oct 2025), 2x headcount in 12mo
- Glassdoor 4.2, eng blog active, uses Python/K8s stack
- HQ: SF, fully remote eng team

**Hiring manager:** Jane Smith, CTO (posted 2 days ago)

**Action:** Apply via Lever → [link]
**Tailored resume:** [resumes/drafts/2026-03-10-acme-ai-vp.md]

---

### 2. 👁️ EM, Platform — BigCo (seen 2 days, score unchanged)
**Score: 87** | Remote | $260-300k (listed)
...

---

### 3. 📈 Director AI Eng — MidCo (seen 3 days, score ↑ 72→78 after enrichment)
...

---

## 🟡 Worth a Look (2 today)

(Score 60-79, less detail, still actionable)

---

## ⚫ Filtered Out (18 today)

| Role | Company | Reason |
|------|---------|--------|
| Sr EM | FooCorp | Salary listed $180k |
| ML Engineer | BarAI | IC only, no reports |
| Director Eng | BazCo | In-office Atlanta |

---

## 📊 Tracker

| Company | Role | Score | Status | Applied | Notes |
|---------|------|-------|--------|---------|-------|
| Acme AI | VP Eng | 91 | 🆕 **NEW** | — | — |
| BigCo | EM Platform | 87 | Applied | Mar 8 | Recruiter screen Mar 12 |
| MidCo | Dir AI Eng | 78 | 👁️ Reviewing | — | Score improved after enrichment |
| OldCo | EM | 65 | Passed | — | Low scope |

---

## 🔧 Source Health

| Source | Status | Last Success | Jobs Found |
|--------|--------|-------------|------------|
| Google Jobs | ✅ | Today | 28 |
| HN | ✅ | Mar 1 | 12 (monthly) |
| NextPlay Sub | ✅ | Mar 9 | 6 companies → 14 jobs |
| NextPlay Slack | ⚠️ degraded | Mar 7 | 0 (2 consecutive failures) |
```

### Brief Markers

Each job in the brief is tagged:
- **🆕 NEW** — first time appearing in a brief
- **👁️ SEEN** — appeared in a previous brief, no significant change
- **📈 UPDATED** — score changed, new enrichment data, or status changed
- **⏰ STALE** — been in brief 7+ days with no action (nudge)

### Tracker State

The tracker persists in `jobs.db`. The brief renders current state each day.

You update status by editing a simple config or running a command:
```bash
# Match by company + role (unambiguous)
shortlist status "Acme AI" "VP Eng" applied
shortlist status "Acme AI" "VP Eng" interviewing --note "Recruiter screen Mar 12"
shortlist pass "MidCo" "EM"

# If only one role at that company, company alone is sufficient
shortlist status "MidCo" applied

# If ambiguous (multiple roles at same company), shortlist prompts you to pick:
#   $ shortlist status "Google" applied
#   Multiple roles at Google:
#     [1] EM, Platform (score 87)
#     [2] Director AI Eng (score 72)
#   Which one?

# Or use job ID directly (shown in brief)
shortlist status 42 applied
```

---

## Data Model

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT,
    description TEXT,
    description_hash TEXT NOT NULL,  -- SHA-256 of normalized description
    salary_text TEXT,
    sources_seen TEXT DEFAULT '[]',  -- JSON array of source names
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'new',  -- new/filtered/rejected/scored/low_score/applied/interviewing/passed/offer
    reject_reason TEXT,
    fit_score INTEGER,
    matched_track TEXT,  -- em/ai/vp
    score_reasoning TEXT,
    yellow_flags TEXT,  -- JSON array
    salary_estimate TEXT,
    salary_confidence TEXT,  -- low/medium/high
    enrichment TEXT,  -- JSON blob (company intel, people, culture)
    enriched_at DATETIME,
    tailored_resume_path TEXT,
    notes TEXT,
    first_briefed DATE,  -- first time shown in a brief
    brief_count INTEGER DEFAULT 0,  -- times shown in brief (for staleness)
    UNIQUE(description_hash)
);

-- Fuzzy dedup index: used for secondary matching on reposts with minor changes
CREATE INDEX idx_jobs_company_title ON jobs(company, title);

CREATE TABLE companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,              -- display name (as seen in JD)
    name_normalized TEXT NOT NULL,   -- lowercase, stripped of Inc/LLC/Corp/Co/Ltd suffixes
    domain TEXT,                     -- career page domain (secondary dedup key)
    career_page_url TEXT,
    ats_platform TEXT,  -- greenhouse/lever/ashby/workday/unknown
    stage TEXT,
    last_funding TEXT,
    headcount INTEGER,
    growth_signals TEXT,  -- JSON
    glassdoor_rating REAL,
    eng_blog_url TEXT,
    enriched_at DATETIME,
    source TEXT,  -- how we found them (nextplay, manual, etc.)
    UNIQUE(name_normalized, domain)  -- "acme" + "acme.com" dedupes "Acme" vs "Acme, Inc."
);

-- Company normalization strategy:
-- 1. Lowercase
-- 2. Strip: Inc, LLC, Corp, Co, Ltd, Limited, Company, Technologies, Labs (+ trailing punctuation)
-- 3. Extract domain from career_page_url if available
-- 4. Match on (name_normalized, domain) when domain known
-- 5. Match on name_normalized alone when domain unknown (with manual review if ambiguous)

CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,  -- simple/browser
    config TEXT NOT NULL,  -- JSON (url pattern, proxy settings, parser name)
    last_run DATETIME,
    enabled BOOLEAN DEFAULT 1
);

CREATE TABLE source_runs (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT NOT NULL,  -- success/partial/failure
    jobs_found INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE run_logs (
    id INTEGER PRIMARY KEY,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    jobs_collected INTEGER DEFAULT 0,
    jobs_filtered INTEGER DEFAULT 0,
    jobs_scored INTEGER DEFAULT 0,
    llm_calls INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_estimate REAL DEFAULT 0.0,
    brief_path TEXT,
    errors TEXT  -- JSON array of error summaries
);
```

---

## File Structure

```
shortlist/
├── shortlist/
│   ├── __init__.py
│   ├── cli.py              # CLI commands (run, status, add-source)
│   ├── config.py           # Profile, filters, settings
│   ├── db.py               # SQLite helpers + migrations
│   ├── pipeline.py         # Orchestrates collect → brief
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py         # BaseCollector protocol
│   │   ├── google_jobs.py  # Browser collector (Playwright)
│   │   ├── hn.py           # Simple collector (Algolia API)
│   │   ├── nextplay.py     # Substack meta-source + Slack (TBD)
│   │   └── career_page.py  # ATS-aware: Greenhouse, Lever, Ashby parsers + LLM fallback
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── dedup.py        # Hash + fuzzy dedup
│   │   ├── filter.py       # Hard filters
│   │   ├── scorer.py       # LLM scoring + salary inference
│   │   ├── enricher.py     # Company intel
│   │   └── resume.py       # Resume matching + tailoring
│   └── brief.py            # Markdown brief generator
├── resumes/
│   ├── em.md               # Base EM resume
│   ├── ai.md               # Base AI resume
│   └── vp.md               # Base VP resume
├── briefs/                  # Daily output (gitignored)
├── config/
│   └── profile.yaml        # Your requirements, filters, preferences
├── tests/
├── docs/
│   └── plans/
├── jobs.db                  # SQLite (gitignored)
├── pyproject.toml
└── README.md
```

---

## Config (profile.yaml)

```yaml
name: Adam

tracks:
  em:
    title: Engineering Manager
    resume: resumes/em.md
    target_orgs: large  # large orgs
    min_reports: 20
    search_queries:
      - "Engineering Manager"
      - "EM"
      - "Head of Engineering"
      - "Director of Engineering"
      - "Engineering Lead"
      - "Senior Engineering Manager"
  ai:
    title: AI Engineering
    resume: resumes/ai.md
    target_orgs: any
    min_reports: 5
    search_queries:
      - "AI Engineering Manager"
      - "Head of AI"
      - "ML Engineering Manager"
      - "AI Platform Lead"
      - "Director of AI"
      - "Head of Machine Learning"
  vp:
    title: VP Engineering
    resume: resumes/vp.md
    target_orgs: series_b_plus
    min_reports: 20
    search_queries:
      - "VP Engineering"
      - "VP of Engineering"
      - "Vice President Engineering"
      - "SVP Engineering"
      - "CTO"  # at smaller companies, CTO ≈ VP Eng

filters:
  location:
    remote: true
    local_zip: "75098"
    max_commute_minutes: 30
  salary:
    min_base: 250000
    # Only hard-reject when salary is explicitly listed below this
    # Unlisted salary = pass through to LLM scorer for inference
  management:
    required: true
    min_reports: 20  # soft — adjusted by scorer for stage/size

preferences:
  equity: nice_to_have
  travel: minimal
  series_a_fresh_funding: yellow_flag

proxy:
  type: mobile
  # connection details loaded from env vars

llm:
  model: claude-sonnet-4-20250514
  max_jobs_per_run: 50  # score at most 50 per night
  cost_budget_daily: 2.00  # USD — warn if exceeded

brief:
  output_dir: briefs/  # relative to project root
  top_n: 10
  show_filtered: true
  stale_threshold_days: 7  # mark jobs as stale after N days in brief
```

---

## Build Phases

| Phase | What | Deliverable | Est. Effort |
|-------|------|-------------|-------------|
| **1** | Project setup + DB + HN collector + hard filters + basic brief + **investigate NextPlay Slack access** | Daily brief with HN jobs, Slack access decision made | 1 session |
| **2** | Google Jobs browser collector (Playwright + proxy) + LLM scorer | Scored + ranked daily brief from aggregated sources | 1-2 sessions |
| **3** | NextPlay Substack meta-source + career page collector (Greenhouse + Lever + Ashby parsers) | Auto-discover companies + crawl structured career pages | 1 session |
| **4** | Resume matcher + tailored drafts | Draft materials in brief | 1 session |
| **5** | Enricher (company intel) + cost tracking | Rich briefs with company context + spend visibility | 1 session |
| **6** | NextPlay Slack (if viable) + tracker CLI + staleness markers + polish | Full system running | 1 session |

---

## CLI Interface

```bash
# Run the full pipeline
shortlist run

# Run just one phase
shortlist collect
shortlist score
shortlist brief

# Manage tracker (by company + role, company alone, or job ID)
shortlist status "Acme AI" "VP Eng" applied
shortlist status "Acme AI" "VP Eng" interviewing --note "Phone screen Mar 12"
shortlist status 42 applied
shortlist pass "MidCo" "EM"

# Add a company to watch
shortlist watch "https://langchain.com/careers"

# Show today's brief
shortlist today

# Show stats (including cost)
shortlist stats

# Check source health
shortlist health
```

---

## Principles

1. **Curation over volume.** 5 great matches > 50 mediocre ones.
2. **Emphasis shifting, not keyword stuffing.** Tailored resumes highlight relevant experience, they don't inject fake keywords.
3. **Hard filters are cheap, soft scoring is smart.** Don't burn LLM calls on jobs that fail basic filters.
4. **Every source is pluggable.** Adding a new source = one parser function.
5. **The brief is the product.** Everything exists to make that 15-minute morning review effective.
6. **Track everything.** Even rejected jobs go in the DB. Patterns in what you skip inform better filters.
7. **Source isolation.** One source failing never blocks others. The pipeline always produces a brief.
8. **Cost awareness.** Every LLM call is logged. Daily spend is visible in the brief.
