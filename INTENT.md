# Shortlist — Intent

## Purpose

Automate the soul-crushing parts of a senior engineering leader's job search. Collect jobs from multiple sources, filter the noise, score what's left against your specific criteria, and surface a curated feed of matches you can review in 15 minutes with coffee. Generate cover letters and tailored resumes for the ones worth applying to.

Not a job board. A personal chief of staff for your job search. Open source at https://github.com/adamjramirez/shortlist.

## Who uses this

**Free tier with user-provided LLM API key.** Users bring their own Gemini/OpenAI/Anthropic key. Typical cost: ~$0.01 per run.

**Live at:** https://shortlist.addslift.com

## What matters (in order)

1. **Match quality** — Everything exists to surface the right jobs. If the feed is noisy, nothing else matters.
2. **Signal over noise** — Better to miss a mediocre match than show 50 false positives. Permissive filters + aggressive scoring.
3. **Freshness** — Jobs go stale fast. Run → results appear in minutes.
4. **Actionable output** — For top matches: cover letters, tailored resumes, direct ATS links. Reduce time-per-application.
5. **Transparency** — Show score reasoning, yellow flags, company intel. Let the user decide, don't hide the data.

## Scoring philosophy

- **Permissive filters, aggressive scoring.** Hard filters catch only clear mismatches. The LLM scorer does the real work — scores 0-100 with reasoning.
- **Enrichment adjusts scores.** Company intel (stage, headcount, Glassdoor, growth) can move a score ±20. A great role at a dying company is not a great role.
- **Score threshold 75 for visibility.** Below 75 = stored but hidden. Users only see matches worth their time.
- **Recruiter listings are valid.** They represent real jobs. Flag them transparently ("Posted by recruiter — actual company not listed") but don't filter them out.
- **Per-source fair budget.** Don't let one source eat the whole scoring budget. ~50 jobs scored per source.

## Cover letter philosophy

- **Starting point, not finished letter.** Always show the "review before sending" warning.
- **Story over summary.** The resume is already a list of achievements. The cover letter tells the story behind them.
- **Real data only.** Use actual company names and numbers from the resume. Never invent metrics.
- **Model choice matters.** Different LLMs write differently. Let users pick.
- **3-layer quality control.** Generate → QA pass → post-processor. No banned phrases ship.

## Tradeoffs (decided)

- **Gemini 2.0 Flash** as default. Fast (1-2s), cheap, good enough for scoring. 2.5-flash hangs on extended thinking.
- **subprocess+curl** for LLM calls on Fly.io. httpx/urllib crash in threaded async context.
- **In-process pipeline** (not ephemeral machines). Simpler, cheaper, good enough for single-user runs.
- **PostgreSQL from day 1** for web. SQLite frozen for CLI. No shared abstraction.
- **Per-provider API keys** over single key. Enables model selection for cover letters.
- **LaTeX-only resumes.** Users generate with AI tools, upload .tex. We tailor and store.
- **NextPlay is system-level cache.** Articles, companies, ATS providers are identical for all users. Only scoring is user-specific.
- **3 scorer workers** on shared-cpu-2x. Less pressure on the VM. 50 jobs in ~28s is fine.

## When to stop

- Spending more than 15 min reviewing matches (feed is too noisy — scoring needs work)
- A source starts returning garbage (disable it, don't fix it)
- Cover letters are generic despite having good context (prompt needs rework, not more features)

## When to escalate (stop and think)

- A source API changes and breaks collection (common with LinkedIn guest API)
- Gemini rate limits tighten significantly
- More than 30% of top matches are irrelevant (scoring prompt needs work)
- A code change touches more than 3 files without clear blast radius
- Can't define acceptance criteria for a feature
