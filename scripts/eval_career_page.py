#!/usr/bin/env python3
"""Fetch and score all jobs from a career page URL (Ashby, Greenhouse, or Lever).

Usage:
    python scripts/eval_career_page.py https://jobs.ashbyhq.com/vellum/...
    python scripts/eval_career_page.py https://boards.greenhouse.io/stripe
    python scripts/eval_career_page.py https://jobs.lever.co/openai

Uses config/profile.yaml for fit_context and scoring. Prints results to stdout,
sorted by score. No DB writes.
"""
import sys
from pathlib import Path

# Make sure shortlist package is importable from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from shortlist.collectors.career_page import fetch_career_page, detect_ats, extract_org_slug
from shortlist.processors.scorer import score_job
from shortlist.config import load_config
from shortlist import llm as llm_module


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/eval_career_page.py <career-page-url>")
        sys.exit(1)

    url = sys.argv[1]

    # Detect ATS so we can give a clear message if unsupported
    ats = detect_ats(url)
    if not ats:
        print(f"Unrecognized ATS URL: {url}")
        print("Supported: jobs.ashbyhq.com, boards.greenhouse.io, jobs.lever.co")
        sys.exit(1)

    slug = extract_org_slug(url, ats)
    print(f"Fetching {ats}/{slug} jobs…")

    jobs = fetch_career_page(url)
    if not jobs:
        print("No jobs found.")
        sys.exit(0)

    print(f"Found {len(jobs)} jobs. Scoring against your profile…\n")

    # Load local profile for scoring context
    config_path = Path(__file__).parent.parent / "config" / "profile.yaml"
    if not config_path.exists():
        print(f"No config found at {config_path} — scoring skipped.")
        _print_jobs_unscored(jobs)
        sys.exit(0)

    config = load_config(config_path)
    llm_module.configure(config.llm.model)

    # Score each job
    results = []
    for job in jobs:
        result = score_job(job, config)
        score = result.fit_score if result else 0
        reasoning = result.reasoning if result else ""
        flags = result.yellow_flags if result else ""
        results.append((score, job, reasoning, flags))

    results.sort(key=lambda x: x[0], reverse=True)

    # Print
    print("=" * 70)
    for score, job, reasoning, flags in results:
        tier = "✅ Strong" if score >= 85 else "👍 Good" if score >= 75 else "⚠️  Marginal" if score >= 60 else "❌ Low"
        print(f"{tier}  [{score}/100]  {job.title}")
        print(f"  📍 {job.location or 'Location not specified'}")
        print(f"  🔗 {job.url}")
        if reasoning:
            print(f"  💬 {reasoning[:200]}{'…' if len(reasoning) > 200 else ''}")
        if flags:
            print(f"  ⚑  {flags}")
        print()


def _print_jobs_unscored(jobs):
    for job in jobs:
        print(f"  {job.title} | {job.location or 'no location'}")
        print(f"  {job.url}")
        print()


if __name__ == "__main__":
    main()
