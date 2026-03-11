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

### Step 3: Get an API key

Shortlist supports **Gemini** (default), **OpenAI**, and **Anthropic**. Pick a model based on your budget:

| Model | Provider | Est. cost/run | Quality | Best for |
|-------|----------|--------------|---------|----------|
| `gemini-2.5-flash` ⭐ | Gemini | **~$0.25** | Good | Daily runs, budget-friendly |
| `gpt-4o-mini` | OpenAI | **~$0.25** | Good | Already have an OpenAI key |
| `claude-3-5-haiku-20241022` | Anthropic | **~$1.30** | Better | Balance of cost and quality |
| `gemini-2.5-pro` | Gemini | **~$2.65** | Great | Better scoring, occasional use |
| `gpt-4o` | OpenAI | **~$3.75** | Great | Best OpenAI quality |
| `claude-sonnet-4-20250514` | Anthropic | **~$5.00** | Best | Best scoring quality |

*Estimates based on a typical run: ~500 jobs scored, 30 companies enriched, 15 resumes tailored (~1M tokens total).*

**Our recommendation:** Start with `gemini-2.5-flash` or `gpt-4o-mini` — they're cheap enough to run daily. If you want better scoring nuance (especially for ambiguous roles), upgrade to `gemini-2.5-pro` or `claude-sonnet-4-20250514`.

Get your API key:

| Provider | Get a key |
|----------|-----------|
| **Gemini** | [aistudio.google.com](https://aistudio.google.com/) → Get API key |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/settings/keys) |

Open `.env` and set the key for your chosen provider:

```
# Pick ONE — whichever matches your llm.model in config/profile.yaml
GEMINI_API_KEY=AIzaSy...your-key-here
# OPENAI_API_KEY=sk-...your-key-here
# ANTHROPIC_API_KEY=sk-ant-...your-key-here
```

Then set the model in `config/profile.yaml`:

```yaml
llm:
  model: gemini-2.5-flash    # see table above for options
```

**No quotes, no spaces around the `=` in `.env`.** Just the key.

Gemini has a free tier (15 requests/minute) — enough for test runs but you'll hit rate limits on a full run.

**Install the provider library** for non-Gemini providers:

```bash
pip install -e ".[openai]"      # for OpenAI models
pip install -e ".[anthropic]"   # for Anthropic models
pip install -e ".[all-llm]"     # all providers
```

Gemini is included by default.

### Step 3b (optional): NextPlay paid articles

One of the job sources ([NextPlay](https://nextplay.substack.com/)) is a Substack newsletter. Free articles are collected automatically. Some paid articles also contain job listings — to include those:

1. Subscribe to NextPlay (paid tier)
2. Log in at [nextplay.substack.com](https://nextplay.substack.com/)
3. Open browser DevTools → Application → Cookies → `nextplay.substack.com`
4. Copy the value of `substack.sid`
5. Add it to `.env`:

```
SUBSTACK_SID=s%3A...your-cookie-here
```

**This is optional.** Without it you still get the majority of NextPlay job listings from their free content.

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

**`fit_context` is the single most important thing to get right.** This text gets sent directly to the LLM with every job it scores. Vague context = vague scores. Write it like you'd brief a recruiter who knows nothing about you.

#### Let AI write it for you

Don't stare at a blank page. Paste this prompt into ChatGPT, Claude, or any AI chat — along with your resume — and it'll generate your `fit_context`, tracks, and search queries:

<details>
<summary>📋 Click to copy the profile generator prompt</summary>

```
I'm setting up a job search tool that scores job listings against my profile.
I need you to read my resume and generate a YAML configuration. Here's what I need:

1. A "fit_context" section (10-20 lines) that describes:
   - My level and years of experience
   - What I'm looking for (role types, company stage, team size)
   - My strongest domain areas
   - "Score HIGH" signals — company types, industries, role traits that are a great fit
   - "Score LOW" signals — things that are clearly not a fit
   - "Yellow flags" — things to note but not reject

2. One or more "tracks" — each representing a type of role I'd target. For each:
   - A short key (like "em" or "vp" or "data")
   - A human-readable title
   - 3-6 LinkedIn search queries (exact job titles people use on LinkedIn)
   - A minimum team size I'd want to manage (if applicable)

3. Filter settings:
   - Am I open to remote, hybrid, or local-only?
   - What's my minimum base salary?
   - Should it reject individual contributor roles?

Write it like you're briefing a recruiter who doesn't know me. Be specific about
what makes a role good or bad for me — not generic statements like "looking for
leadership roles" but real signals like "Series B+ B2B SaaS" or "not ad-tech."

Output the result as YAML I can paste directly into a config file.

Here's my resume:

[PASTE YOUR RESUME TEXT HERE]
```

</details>

Review what it gives you — tweak anything that doesn't feel right, especially the "Score HIGH" and "Score LOW" sections. You know your preferences better than any AI does.

**❌ Too vague (will produce mediocre scores):**
```yaml
fit_context: |
  Looking for engineering leadership roles. 
  Prefer remote. Good at building teams.
```

**✅ Specific (will produce useful scores):**
```yaml
fit_context: |
  12 years in software engineering, last 5 in management. Currently managing
  25 engineers across 3 teams at a Series C fintech company ($40M ARR).
  
  Looking for: Director or VP of Engineering at product-focused companies,
  Series B or later, 30-100 engineers. I'm strongest at scaling teams through
  the 20→80 engineer growth phase and building platform/infrastructure orgs.
  
  Score HIGH:
  - B2B SaaS, fintech, developer tools, data infrastructure
  - Companies with engineering blogs, OSS presence, or strong Glassdoor
  - Roles where I'd own the full eng org or a major pillar (platform, data)
  - PE-backed companies needing eng transformation (VP track)
  
  Score LOW:
  - Consumer social, gaming, ad-tech (not my domain)
  - Pure ML/AI research orgs (I'm an eng leader, not a researcher)
  - Pre-product startups (seed/pre-seed) — too early for my level
  - Roles that report to a non-technical founder with no VP Eng layer
  
  Yellow flags (don't reject, but note):
  - Series A with fresh funding (may not need my level yet)
  - "Engineering Manager" title at a 500+ person company (likely too junior)
  - No salary listed at a company with <50 people
```

The more specific your "Score HIGH" and "Score LOW" sections are, the better. Think about the last 5 roles you saw and thought "yes, that's me" vs. "no way" — put that reasoning here.

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

Each track generates LinkedIn searches from its `search_queries`.

**Tips for `search_queries`:**
- Use the **exact job titles** you'd search on LinkedIn — these become LinkedIn keyword searches
- Include title variations people actually use (e.g., "Head of Engineering" vs "Director of Engineering" — same role, different titles)
- Don't add generic terms like "remote" or "software" — that's what filters are for
- 3-6 queries per track is the sweet spot. Too many = noise, too few = missed roles
- If you're targeting a specific domain, add it: "Fintech Engineering Manager", "AI/ML Engineering Lead"

**Multiple resumes per track:** If you have variants (e.g., enterprise vs. growth VP resume), use `resumes:` (plural) instead of `resume:`:

```yaml
  vp:
    title: VP Engineering
    resumes:
      - resumes/vp_enterprise.tex
      - resumes/vp_growth.tex
    search_queries:
      - "VP Engineering"
      - "VP of Engineering"
      - "Vice President Engineering"
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

**Filters are intentionally permissive.** They only reject jobs with clear disqualifiers — explicit salary below your minimum, explicit IC role, or a location that's clearly not remote and not local. If anything is ambiguous, the job passes through to scoring. This means:
- No salary listed? → Passes to scoring (the LLM will estimate)
- "Hybrid" with no city? → Passes to scoring
- You'll see some irrelevant jobs scored low (30-40) — that's by design. Better to score a bad job than miss a good one.

See `config/example-profile.yaml` for a fully commented template.

### Tuning your results

After your first run, check the brief:

- **Too many low-scoring jobs?** Your `search_queries` might be too broad. Narrow them.
- **Good jobs scoring low?** Your `fit_context` is probably missing what makes them good. Add it to "Score HIGH."
- **Bad jobs scoring high?** Add the pattern to "Score LOW" in your `fit_context`.
- **Missing jobs you expected?** Add more `search_queries` variations, or check if the company uses an ATS we don't support (Workday, custom platforms).

The scorer learns nothing between runs — it re-reads your `fit_context` every time. So edit it freely and re-run with `shortlist run --no-collect` to re-score existing jobs with your updated profile.

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

### Adding a new job source

The collector architecture is designed to be extended. To add a new source:

1. **Create a collector** at `shortlist/collectors/yoursource.py`
2. **Implement the `BaseCollector` protocol** — just one method:

```python
from shortlist.collectors.base import BaseCollector, RawJob

class YourSourceCollector:
    def fetch_new(self) -> list[RawJob]:
        # Fetch jobs and return them as RawJob objects
        return [
            RawJob(
                title="Engineering Manager",
                company="Acme Corp",
                url="https://example.com/jobs/123",
                description="Full job description text...",
                source="yoursource",        # unique source key
                location="Remote",           # optional
                salary_text="$180k - $220k", # optional
            )
        ]
```

3. **Register it** in `shortlist/pipeline.py` → `_get_collectors()`:

```python
collectors["yoursource"] = YourSourceCollector()
```

That's it. The pipeline handles deduplication (via description hashing), filtering, scoring, enrichment, resume tailoring, and briefing automatically.

### Scoring

For each job, your configured LLM gets:
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

### "API key not set" or "API key is invalid"

Check your `.env` file:
- No quotes around the key
- No spaces around `=`
- The key matches your configured provider (`llm.model` in profile.yaml)
- Gemini keys start with `AIza`, OpenAI with `sk-`, Anthropic with `sk-ant-`

### No jobs found

- Check `shortlist health` — are sources returning errors?
- Your `search_queries` might be too specific. Try broader terms.
- LinkedIn guest API occasionally returns empty results. Run again later.

### Low scores across the board

Your `fit_context` is probably too vague. See the [good vs. bad examples](#step-5-configure-your-search) and the [tuning guide](#tuning-your-results) above.

### Resume tailoring fails

- Resume must be LaTeX (`.tex`) format
- Check the file path in `config/profile.yaml` matches the actual file in `resumes/`

---

## Cost

LLM API only. A typical run processes ~500 jobs scored + 30 enriched + 15 resumes tailored (~1M tokens). Costs range from **$0.25/run** (Gemini Flash, GPT-4o-mini) to **$5/run** (Claude Sonnet). See the [model table](#step-3-get-an-api-key) for per-model estimates. The free Gemini tier works for test runs but you'll hit rate limits on a full run.

## Limitations

- **LaTeX resumes only** — tailoring requires `.tex` format
- **No Google Jobs** — would need a paid API (SerpAPI etc.)
- **No JS-rendered career pages** — companies using Workday or custom platforms (Atlassian, Shopify) aren't auto-discovered. Their LinkedIn listings still get collected.
- **LinkedIn guest API is fragile** — unauthenticated, may break without notice
- **Location filtering is US-biased** — state abbreviations, zip codes, and the known-city list skew American. International cities like London, Berlin, Tokyo, etc. are recognized, but smaller non-US cities may not be. Remote jobs pass through regardless of geography, so this mainly affects on-site/hybrid filtering for international users.
- **Salary parsing is USD-only** — the salary filter parses `$` amounts. Salaries listed in `€`, `£`, `¥`, or other currencies are ignored (job passes through to scoring). No currency conversion is performed.

## License

MIT
