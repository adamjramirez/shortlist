# Shortlist

Personal job search automation. Runs overnight, collects jobs from multiple sources, scores them against your criteria with an LLM, tailors your resume for top matches, and produces a daily markdown briefing.

---

## Setup (10 minutes)

### Step 1: Install

```bash
git clone https://github.com/adamjramirez/shortlist.git
cd shortlist
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires **Python 3.11 or later**. Check with `python --version`.

### Step 2: Initialize

```bash
shortlist init
```

This creates:
- `config/profile.yaml` — your search configuration (edit this next)
- `.env` — where your API key goes
- `resumes/` — where your resume files go
- `briefs/` — where daily briefs get written
- `.gitignore` — keeps secrets and personal files out of git

### Step 3: Get a Gemini API key

1. Go to [aistudio.google.com](https://aistudio.google.com/)
2. Sign in with any Google account
3. Click **"Get API key"** in the left sidebar
4. Click **"Create API key"** — select or create a Google Cloud project (free)
5. Copy the key

Open `.env` and replace the placeholder:

```
GEMINI_API_KEY=AIzaSy...paste-your-key-here
```

**No quotes, no spaces around the `=`.** Just the key.

The free tier gives 15 requests/minute, enough for small test runs. For a full run (~500+ jobs), upgrade to pay-as-you-go in Google AI Studio. Costs roughly **$2-3 per run**.

### Step 4: Add your resume

Put your resume in `resumes/` as a LaTeX `.tex` file.

```
resumes/my_resume.tex
```

If you have multiple resume variants for different role types (e.g., one for management, one for technical leadership), add them all. Shortlist will pick the best one per job.

**LaTeX format is required.** The tailoring engine modifies `.tex` source to reorder bullets and adjust emphasis. If you don't have a LaTeX resume, you can still use shortlist — the scoring and brief will work, but resume tailoring won't.

### Step 5: Configure your search

Open `config/profile.yaml` and edit it. Here's what each section does:

```yaml
name: Your Name                    # Used in scoring prompts

fit_context: |                     # MOST IMPORTANT FIELD
  Describe yourself in 5-15 lines. # This is sent directly to the LLM.
  What roles fit you?              # Be specific — it determines scoring quality.
  What's your background?          
  What should score high vs low?   
```

**`fit_context` is the single most important thing to get right.** Write it like you'd brief a recruiter who knows nothing about you. Include:
- Your level and target roles
- Your background (what industries, what size companies)
- What signals should score HIGH (e.g., "Series B fintech", "AI infrastructure")
- What signals should score LOW (e.g., "pure research", "pre-product startups")

```yaml
tracks:                            # Role types you're targeting
  em:                              
    title: Engineering Manager     # Human-readable label
    resume: resumes/my_resume.tex  # Path to resume for this track
    target_orgs: any               # any, large, series_b_plus
    min_reports: 5                 # Ideal team size
    search_queries:                # Keywords for LinkedIn searches
      - "Engineering Manager"      
      - "Head of Engineering"      
```

Each track generates LinkedIn searches from its `search_queries`. More specific queries = better results. If you're targeting multiple role types (e.g., EM and VP), create a track for each.

**Multiple resumes per track:** If you have variants (e.g., enterprise vs. growth VP resume), use `resumes:` (plural) instead of `resume:`:

```yaml
  vp:
    title: VP Engineering
    resumes:
      - resumes/vp_enterprise.tex
      - resumes/vp_growth.tex
    search_queries:
      - "VP Engineering"
```

The LLM will read each job description and pick the best resume variant.

```yaml
filters:
  location:
    remote: true                   # Accept remote roles
    local_zip: "10001"             # Your zip code (used in scoring)
    local_cities:                  # Cities you'd commute to (lowercase)
      - new york
      - brooklyn

  salary:
    min_base: 200000               # Only reject if EXPLICITLY below this

  role_type:
    reject_explicit_ic: true       # Reject "individual contributor" roles
```

**Filters are very permissive by design.** Salary only rejects jobs that explicitly list a number below your minimum — if no salary is listed, the job passes through to scoring. Same for location: if it's ambiguous, it passes.

See `config/example-profile.yaml` for a fully commented template.

### Step 6: Run it

```bash
shortlist run
```

You'll see progress as it runs:

```
Running full pipeline...
Collecting from hn...
  → hn: 380 jobs
Collecting from linkedin...
  → linkedin: 95 jobs
Collecting from nextplay...
  → nextplay: 42 jobs
Collection done: 517 jobs total
Filtering jobs...
  → 410 passed, 107 filtered out
Scoring 410 jobs (parallel, 10 workers)...
  → 28 jobs scored ≥60
Enriching 15 companies...
Tailoring resumes for 15 top matches (parallel, 10 workers)...
  → 14 resumes tailored
Generating brief...
  → briefs/2026-03-10.md

✅ Brief generated: briefs/2026-03-10.md
   Run 'shortlist today' to read it.
```

First run takes 10-20 minutes depending on how many jobs are found. Subsequent runs are faster because already-seen jobs are skipped.

---

## Daily usage

```bash
shortlist run                      # Full run: collect new jobs + process + brief
shortlist run --no-collect         # Re-process existing jobs without fetching new ones
shortlist today                    # Print today's brief to terminal
shortlist brief                    # Regenerate the brief without re-scoring
shortlist status "Acme" applied    # Track your application status
shortlist health                   # Check if sources are working
```

### Reading the brief

The brief is a markdown file at `briefs/YYYY-MM-DD.md`. Open it in any markdown viewer, VS Code, or just read it in the terminal.

Each job entry includes:
- **Score (0-100) and reasoning** — why it's a match
- **Company intel** — stage, headcount, Glassdoor rating, growth signals
- **Apply link** — with alternate links if found on multiple sources
- **Tailored resume** — link to customized `.tex` file in `resumes/drafts/`
- **"Why I'm interested" note** — 3 sentences for a cover letter

**Markers tell you what's new:**
- 🆕 First time in the brief
- 👁️ Seen in a previous brief
- ⏰ Stale — been in the brief for 7+ days with no action
- 🔍 Recruiter listing — real job, but company name is hidden. Ask "who's the company?" when applying.

### Tailored resumes

For each top match, shortlist generates two files in `resumes/drafts/`:
- `YYYY-MM-DD-company-track.tex` — your resume with bullets reordered for the specific JD
- `YYYY-MM-DD-company-track.note.md` — "why I'm interested" + list of changes made

**The tailoring is surgical** — it reorders existing bullets and adjusts your summary. It never invents experience or fabricates metrics. Always review before sending.

---

## How it works

### Sources

| Source | What | How |
|--------|------|-----|
| **HN Who's Hiring** | Monthly thread, all postings | Algolia API |
| **LinkedIn** | Keyword searches from your config | Guest API (no login needed) |
| **NextPlay Substack** | Career page links from newsletter | RSS + HTML parsing |
| **Career pages** | Full company job boards | Greenhouse, Lever, Ashby APIs |

Career pages are discovered automatically. When a company scores well, shortlist visits their website, finds their ATS (applicant tracking system), and pulls all their open roles.

### Scoring

For each job, Gemini gets:
- Your full profile (`fit_context`, tracks, requirements)
- The complete job description

It returns a score (0-100), matched track, reasoning, yellow flags, and salary estimate.

After scoring, top companies get enriched with additional intel (funding stage, headcount, Glassdoor), which can adjust the score ±20 points.

### Rate limiting

All HTTP requests go through a centralized rate-limited client. You won't get blocked or rate-limited from any source. Per-domain throttling is built in.

---

## Troubleshooting

### "❌ Fix these issues before running"

Shortlist validates your config before starting. Read the error messages — they tell you exactly what's wrong and how to fix it.

### "GEMINI_API_KEY not set"

Check your `.env` file:
- No quotes around the key
- No spaces around `=`
- Key starts with `AIza`

### No jobs found

- Check `shortlist health` — are sources returning errors?
- Your `search_queries` might be too specific. Try broader terms.
- LinkedIn guest API occasionally returns empty results. Run again later.

### Low scores across the board

Your `fit_context` might be too vague. Be specific about what you want — the LLM can only score well if it understands your priorities.

### Resume tailoring fails

- Resume must be LaTeX (`.tex`) format
- Check the file path in `config/profile.yaml` matches the actual file in `resumes/`

---

## Cost

Gemini API only. Roughly **$2-3 per full run** (~500 jobs scored + 30 enriched + 15 resumes tailored). The free Gemini tier works for test runs but you'll hit rate limits on a full run.

## Limitations

- **LaTeX resumes only** — tailoring requires `.tex` format
- **No Google Jobs** — would need a paid API (SerpAPI etc.)
- **No JS-rendered career pages** — companies using Workday or custom platforms (Atlassian, Shopify) aren't auto-discovered. Their LinkedIn listings still get collected.
- **LinkedIn guest API is fragile** — unauthenticated, may break without notice

## License

MIT
