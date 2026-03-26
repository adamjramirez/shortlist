"""A/B test: score 10 jobs with AWW networking slice vs raw fit_context.

Compares scoring quality between:
  (A) AWW networking slice — curated, fact-checked, 1.8KB
  (B) Raw fit_context — full node dump, 14KB

Outputs a comparison table with scores and reasoning excerpts.
"""
import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shortlist.config import load_config, Config
from shortlist.processors.scorer import score_job, ScoreResult, SCORING_PROMPT_TEMPLATE
from shortlist.collectors.base import RawJob
from shortlist.aww_client import pull_networking_slice
from shortlist import llm


def get_test_jobs(db_path: str, n: int = 10) -> list[dict]:
    """Get n recent jobs with existing scores and descriptions."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT id, title, company, fit_score, description, location
        FROM jobs
        WHERE fit_score IS NOT NULL AND description IS NOT NULL AND length(description) > 200
        ORDER BY first_seen DESC LIMIT ?
    """, (n,)).fetchall()
    return [dict(r) for r in rows]


def score_with_context(job: dict, config: Config) -> ScoreResult | None:
    """Score a single job using the pipeline scorer."""
    raw = RawJob(
        title=job["title"],
        company=job["company"],
        location=job.get("location", ""),
        url="",
        source="ab-test",
        description=job["description"],
    )
    results = score_job(raw, config)
    return results


def main():
    base_config = load_config("config/profile.yaml")

    # Get AWW slice
    node_id = os.environ.get("AWW_NODE_ID", "")
    if not node_id:
        # Try profile config
        raw_cfg = base_config.preferences or {}
        node_id = raw_cfg.get("aww_node_id", "")
    if not node_id:
        print("ERROR: Set AWW_NODE_ID env var or aww_node_id in profile")
        sys.exit(1)

    aww_content = pull_networking_slice(node_id)
    if not aww_content:
        print("ERROR: Could not pull AWW networking slice")
        sys.exit(1)

    # Configure LLM
    from shortlist import llm as shortlist_llm
    model = base_config.llm.model if base_config.llm.model else "gemini-2.5-flash"
    shortlist_llm.configure(model)
    print(f"LLM: {model}")

    print(f"Context A (AWW slice):     {len(aww_content):,} chars")
    print(f"Context B (raw fit_context): {len(base_config.fit_context):,} chars")
    print()

    # Build two configs — clone base and swap fit_context
    import dataclasses
    config_a = dataclasses.replace(base_config, fit_context=aww_content)
    config_b = base_config  # unchanged

    # Get test jobs
    jobs = get_test_jobs("jobs.db", 10)
    print(f"Scoring {len(jobs)} jobs...\n")

    # Score with both contexts
    results = []
    for i, job in enumerate(jobs):
        print(f"  [{i+1}/{len(jobs)}] {job['company']}: {job['title'][:50]}...")

        result_a = score_with_context(job, config_a)
        result_b = score_with_context(job, config_b)

        results.append({
            "id": job["id"],
            "title": job["title"][:45],
            "company": job["company"][:20],
            "original_score": job["fit_score"],
            "score_a": result_a.fit_score if result_a else None,
            "score_b": result_b.fit_score if result_b else None,
            "reasoning_a": (result_a.reasoning[:80] + "...") if result_a and result_a.reasoning else "",
            "reasoning_b": (result_b.reasoning[:80] + "...") if result_b and result_b.reasoning else "",
        })

    # Print results
    print()
    print(f"{'ID':>4} | {'Company':<20} | {'Title':<45} | {'Orig':>4} | {'AWW':>4} | {'Raw':>4} | {'Δ':>3}")
    print("-" * 115)
    for r in results:
        delta = ""
        if r["score_a"] is not None and r["score_b"] is not None:
            d = r["score_a"] - r["score_b"]
            delta = f"{d:+d}" if d != 0 else "="
        print(f"{r['id']:>4} | {r['company']:<20} | {r['title']:<45} | {r['original_score']:>4} | {str(r['score_a'] or '?'):>4} | {str(r['score_b'] or '?'):>4} | {delta:>3}")

    # Summary
    a_scores = [r["score_a"] for r in results if r["score_a"] is not None]
    b_scores = [r["score_b"] for r in results if r["score_b"] is not None]
    if a_scores and b_scores:
        print()
        print(f"AWW avg:  {sum(a_scores)/len(a_scores):.1f}")
        print(f"Raw avg:  {sum(b_scores)/len(b_scores):.1f}")

        # Check for regressions: high-scoring jobs that dropped
        regressions = [r for r in results
                       if r["score_a"] is not None and r["score_b"] is not None
                       and r["score_b"] >= 70 and r["score_a"] < r["score_b"] - 10]
        if regressions:
            print(f"\n⚠ REGRESSIONS ({len(regressions)} jobs scored 10+ points lower with AWW):")
            for r in regressions:
                print(f"  {r['company']}: {r['title']} — AWW {r['score_a']} vs Raw {r['score_b']}")
        else:
            print("\n✅ No regressions (no high-scoring jobs dropped significantly with AWW)")

    # Save full results
    with open("scripts/ab_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nFull results saved to scripts/ab_test_results.json")


if __name__ == "__main__":
    main()
