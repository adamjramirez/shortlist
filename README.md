# Shortlist

Personal job search automation. Collects jobs overnight from multiple sources, filters and scores them against your criteria using an LLM, tailors your resume for top matches, and produces a daily markdown briefing.

## What it does

```
Collect → Dedup → Filter → Score → Enrich → Tailor → Brief
```

1. **Collects** from HN Who's Hiring, LinkedIn (no auth needed), Substack newsletters, and company career pages (Greenhouse, Lever, Ashby — auto-detected)
2. **Filters** by location, salary, and role type — very permissive, only rejects clear mismatches
3. **Scores 0-100** with Gemini against your profile — reads the full JD, returns reasoning and flags
4. **Enriches** top companies — stage, headcount, Glassdoor, growth signals
5. **Tailors your resume** for each top match — reorders bullets, adjusts emphasis (never invents facts)
6. **Generates a markdown brief** — ranked matches with scores, company intel, apply links, and tailored resume drafts

Scoring and resume tailoring run in parallel (10 workers). A full run of ~1000 jobs takes about 15 minutes.

## Quick start

```bash
# Install
git clone https://github.com/youruser/shortlist.git
cd shortlist
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Set up
shortlist init

# Edit your config
$EDITOR config/profile.yaml   # your search criteria, role tracks, location
$EDITOR .env                   # add your Gemini API key

# Add your resume(s) to resumes/ (LaTeX format)

# Run
shortlist run
```

## Requirements

- **Python 3.12+**
- **Gemini API key** (free to start)
- **Your resume in LaTeX** — one or more `.tex` files. You can have multiple variants for different role types (the LLM picks the best one per job).

No Docker, no database server, no infrastructure. It's SQLite and a CLI.

### Getting a Gemini API key

1. Go to [aistudio.google.com](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click **"Get API key"** in the left sidebar
4. Click **"Create API key"** → select any Google Cloud project (or create one — it's free)
5. Copy the key and paste it into your `.env` file:
   ```
   GEMINI_API_KEY=AIzaSy...your-key-here
   ```

The free tier gives you 15 requests/minute on Flash, which is enough for small test runs. For a full run (~1000 jobs), you'll hit the free tier limits — upgrade to pay-as-you-go in Google AI Studio settings. A full run costs roughly $2-3.

## Configuration

After `shortlist init`, edit `config/profile.yaml`:

```yaml
name: Your Name

fit_context: |
  Describe what you're looking for. Be specific.
  What's your background? What kind of companies?
  What should score high vs. low?

tracks:
  em:
    title: Engineering Manager
    resume: resumes/em.tex
    target_orgs: large
    min_reports: 10
    search_queries:
      - "Engineering Manager"
      - "Director of Engineering"

filters:
  location:
    remote: true
    local_zip: "10001"
    local_cities:
      - new york
      - brooklyn
  salary:
    min_base: 200000
  role_type:
    reject_explicit_ic: true
```

The `fit_context` field is the most important — it's sent directly to the LLM scorer. Write it like you'd brief a recruiter: what roles fit, what doesn't, what signals matter.

The `search_queries` under each track become LinkedIn searches. More specific = better results.

See `config/example-profile.yaml` for a fully commented template.

## Commands

```bash
shortlist run                  # Full pipeline: collect → score → tailor → brief
shortlist run --no-collect     # Skip collection, process existing jobs only
shortlist collect              # Just collect from all sources
shortlist brief                # Just regenerate today's brief
shortlist today                # Print today's brief to stdout
shortlist status "Acme" applied   # Track your application status
shortlist health               # Check source health
shortlist init                 # Set up a new project
```

## Output

### Daily brief (`briefs/YYYY-MM-DD.md`)

Each job in the brief includes:
- **Score and reasoning** — why it fits (or doesn't)
- **Company intel** — stage, headcount, Glassdoor rating, growth signals
- **Apply link** — with alternate links if the same job was found on multiple sources
- **Tailored resume** — link to the customized `.tex` file
- **"Why I'm interested" note** — 3 sentences you can use in a cover letter

Markers:
- 🆕 New today
- 👁️ Seen before
- ⏰ Stale (>7 days)
- 🔍 Recruiter listing (real job, but company name is hidden — ask "who's the company?" when applying)

### Tailored resumes (`resumes/drafts/`)

For each top match, shortlist generates:
- `YYYY-MM-DD-company-track.tex` — your resume with bullets reordered and summary adjusted for the JD
- `YYYY-MM-DD-company-track.note.md` — "why I'm interested" + list of changes made

The tailoring is surgical — it reorders existing bullets and adjusts emphasis. It never invents experience or metrics.

## How it works

### Sources

| Source | What it gets | How |
|--------|-------------|-----|
| HN Who's Hiring | Monthly thread, all postings | Algolia API |
| LinkedIn | Keyword searches per track | Guest API (no auth) |
| NextPlay Substack | Career page links from articles | RSS + HTML parsing |
| Career pages | Full job boards from companies | Greenhouse/Lever/Ashby JSON APIs |

Career pages are discovered automatically: when a company scores well, shortlist probes their website for an ATS board and pulls all their listings.

### Scoring

Each job gets a Gemini prompt with your full profile (`fit_context`, tracks, requirements) and the complete job description. The LLM returns:
- `fit_score` (0-100)
- `matched_track` (which of your role tracks it fits)
- `reasoning` (2-3 sentences)
- `yellow_flags` (concerns)
- `salary_estimate` and `salary_confidence`

After scoring, top companies get enriched (stage, headcount, Glassdoor), which can adjust the score ±20.

### Rate limiting

All HTTP goes through a centralized rate-limited client. Per-domain throttling:
- Gemini: 0.5s between calls
- LinkedIn, Greenhouse, Lever, Ashby: 2s between calls
- HN Algolia: 1s between calls

You won't get rate-limited or blocked.

## Cost

Gemini API only. Roughly **$2-3 per full run** on Flash pricing (~1000 jobs scored + 50 enriched + 30 resumes tailored). Free tier may work for smaller runs.

## Limitations

- **No Google Jobs** — would need SerpAPI or similar
- **No JS-rendered career pages** — companies using Workday or custom platforms (Atlassian, Shopify, GitLab) aren't auto-discovered. Their LinkedIn listings still get collected.
- **LinkedIn guest API is fragile** — unauthenticated, limited to ~25 results per search, may break without notice
- **LaTeX resumes only** — the tailoring assumes `.tex` format

## License

MIT
