# Shortlist — Intent

## Purpose

Automate the soul-crushing parts of a senior engineering leader's job search. Collect jobs overnight from multiple sources, filter the noise, score what's left against my specific criteria, and produce a curated daily markdown briefing I can review in 15 minutes with coffee.

Not a job board. A personal chief of staff for your job search. Open source at https://github.com/adamjramirez/shortlist.

## Who uses this

**Adam** — personally job hunting. Engineering leader (EM/VP/Director level). Located in McKinney, TX (DFW). Looking for remote or local roles.

## What matters (in order)

1. **Brief quality** — Everything exists to make the 15-min morning review effective. If the brief is noisy, nothing else matters.
2. **Signal over noise** — Better to miss a mediocre match than show 50 false positives. Permissive filters + aggressive scoring achieves this.
3. **Freshness** — Jobs go stale fast. Overnight collection → morning brief. Don't show me week-old listings.
4. **Tailored resumes** — For top matches, having a pre-tailored resume draft saves 30+ minutes per application.
5. **Simplicity** — One person, one machine. SQLite, not Postgres. Cron, not Kubernetes. If it breaks, `shortlist run` fixes it.

## Target roles

| Track | Description | Resume |
|-------|-------------|--------|
| **EM** | Engineering Manager at large orgs (20+ reports) | `resumes/em.tex` |
| **AI** | AI/ML leadership at solid companies | `resumes/ai.tex` |
| **VP Enterprise** | VP Eng at established companies (Series B+) | `resumes/vp_enterprise.tex` |
| **VP Growth** | VP Eng at growth-stage companies | `resumes/vp_growth.tex` |

## Hard filters (non-negotiable)

- **Location:** Remote, or within 30 min of 75098 (McKinney, TX / DFW metro)
- **Salary:** Only reject if explicitly listed below $250k base. Unlisted = pass through.
- **Management:** Only reject explicit IC roles. Ambiguous passes to scorer.
- **Travel:** Prefer no travel, but not a hard filter.

## Scoring philosophy

- **Permissive filters, aggressive scoring.** Hard filters catch only clear mismatches. The LLM scorer does the real work — it understands context, reads between the lines, and scores 0-100 with reasoning.
- **Enrichment adjusts scores.** Company intel (stage, headcount, Glassdoor, growth signals) can move a score ±20. A great role at a dying company is not a great role.
- **Recruiter listings are valid.** They represent real jobs. Flag them (🔍) so I know to ask "who's the company?" — but don't filter them out.
- **Series A fresh funding is a yellow flag.** Score down, don't reject.
- **Equity is nice to have.** Depends on company/growth/salary.

## Tradeoffs (decided)

- **Gemini over Claude** for scoring/enrichment. Already have the API key, rate limits are generous.
- **Guest API over authenticated scraping** for LinkedIn. Fragile but works, no auth risk.
- **Centralized HTTP with rate limiting** over per-collector clients. Every external call goes through `shortlist.http`.
- **Parallel scoring over batched prompts.** ThreadPoolExecutor(10) is simpler and more reliable (0 failures on 400+ jobs) vs. fragile multi-job prompt parsing.
- **Smart ATS discovery over blind probing.** Visit company website → find careers page → detect ATS. Eliminates false 406 errors.
- **Article cache with 7-day TTL.** Re-crawl updated articles without redundant daily work.
- **SQLite over Postgres.** One user, one machine. No need for concurrent writes or network access.

## When to stop

- Spending more than 15 min/day reviewing the brief (brief is too noisy)
- A source starts returning garbage (disable it, don't fix it)
- Tailoring a resume for a job I wouldn't actually apply to (scoring is miscalibrated)

## When to escalate (stop and think)

- A source API changes and breaks collection (common with LinkedIn guest API)
- Gemini rate limits tighten significantly
- More than 30% of top matches are irrelevant (scoring prompt needs work)
- A code change touches more than 3 files without clear blast radius
