"""Seed AI-frontier companies into the SQLite companies table.

These companies don't appear naturally in HN/LinkedIn/curated sources at
the volume we want, so we seed them directly. Once a company has a domain,
the pipeline's discovery loop (pipeline.py) auto-detects the ATS platform
(Ashby/Greenhouse/Lever) and starts pulling jobs from the career page.

Idempotent: ON CONFLICT(name_normalized, domain) DO NOTHING.

Usage:
    python scripts/seed_ai_frontier_companies.py
    python scripts/seed_ai_frontier_companies.py --db /path/to/jobs.db
    python scripts/seed_ai_frontier_companies.py --dry-run
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortlist.processors.enricher import _normalize_company  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "jobs.db"


# (name, domain) — kept domain-only so the discovery loop auto-detects the ATS.
AI_FRONTIER_COMPANIES: list[tuple[str, str]] = [
    ("OpenAI", "openai.com"),
    ("Anthropic", "anthropic.com"),
    ("Hugging Face", "huggingface.co"),
    ("Cursor", "cursor.com"),
    ("Modal", "modal.com"),
    ("Replicate", "replicate.com"),
    ("Vercel", "vercel.com"),
    ("Linear", "linear.app"),
    ("LangChain", "langchain.com"),
    ("Together AI", "together.ai"),
    ("Perplexity", "perplexity.ai"),
    ("Mistral AI", "mistral.ai"),
    ("Cohere", "cohere.com"),
    ("Stripe", "stripe.com"),
    ("GitHub", "github.com"),
    ("Databricks", "databricks.com"),
]


def seed(db: sqlite3.Connection, companies: list[tuple[str, str]]) -> tuple[int, int]:
    """Insert companies, skipping duplicates. Returns (inserted, skipped)."""
    inserted = 0
    skipped = 0
    for name, domain in companies:
        normalized = _normalize_company(name)
        cursor = db.execute(
            "INSERT INTO companies (name, name_normalized, domain, source) "
            "VALUES (?, ?, ?, 'ai-frontier-seed') "
            "ON CONFLICT(name_normalized, domain) DO NOTHING",
            (name, normalized, domain),
        )
        if cursor.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    db.commit()
    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to jobs.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print(f"Would seed {len(AI_FRONTIER_COMPANIES)} companies into {args.db}:")
        for name, domain in AI_FRONTIER_COMPANIES:
            print(f"  {name:20s}  {domain}")
        return

    db = sqlite3.connect(args.db)
    try:
        inserted, skipped = seed(db, AI_FRONTIER_COMPANIES)
        print(f"Seeded {inserted} new companies, skipped {skipped} existing.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
