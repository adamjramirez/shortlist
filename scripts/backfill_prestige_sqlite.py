#!/usr/bin/env python3
"""Backfill prestige_tier for visible CLI/SQLite jobs missing one.

Sister to backfill_prestige.py (Postgres / web path). Standalone — calls
score_prestige() for each job with NULL prestige_tier above the visibility
threshold and writes the result back. Safe to re-run (idempotent: skips
rows already populated).

Usage:
    python scripts/backfill_prestige_sqlite.py
    python scripts/backfill_prestige_sqlite.py --db /path/to/jobs.db
    python scripts/backfill_prestige_sqlite.py --min-score 60   # broader
    python scripts/backfill_prestige_sqlite.py --dry-run
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shortlist.collectors.base import RawJob  # noqa: E402
from shortlist.config import SCORE_VISIBLE, load_config  # noqa: E402
from shortlist import llm  # noqa: E402
from shortlist.processors.scorer import score_prestige  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "jobs.db"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to jobs.db")
    parser.add_argument(
        "--min-score",
        type=int,
        default=SCORE_VISIBLE,
        help=f"Only backfill jobs with fit_score >= this (default: {SCORE_VISIBLE})",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Re-score jobs that already have a prestige_tier (use when rubric changes)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(REPO_ROOT / "config" / "profile.yaml")
    llm.configure(config.llm.model)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    where_clause = "WHERE fit_score >= ?"
    if not args.rescore:
        where_clause += " AND prestige_tier IS NULL"
    rows = conn.execute(
        f"""
        SELECT id, title, company, url, description, location,
               salary_text, sources_seen, fit_score
        FROM jobs
        {where_clause}
        ORDER BY fit_score DESC
        """,
        (args.min_score,),
    ).fetchall()

    logger.info(f"Found {len(rows)} jobs to backfill (min score {args.min_score}).")

    if args.dry_run:
        for row in rows:
            logger.info(f"  would score [{row['fit_score']}] {row['title'][:45]} @ {row['company'][:25]}")
        return

    scored = 0
    failed = 0
    for row in rows:
        sources_raw = row["sources_seen"] or "[]"
        try:
            sources_list = json.loads(sources_raw) if isinstance(sources_raw, str) else sources_raw
        except (TypeError, json.JSONDecodeError):
            sources_list = []
        source = sources_list[0] if sources_list else "unknown"

        job = RawJob(
            title=row["title"],
            company=row["company"],
            url=row["url"] or "",
            description=row["description"] or "",
            source=source,
            location=row["location"] or "",
            salary_text=row["salary_text"],
        )

        tier = score_prestige(job, config)
        if tier:
            conn.execute(
                "UPDATE jobs SET prestige_tier = ? WHERE id = ?",
                (tier, row["id"]),
            )
            conn.commit()
            scored += 1
            logger.info(f"  [{tier}] {row['title'][:45]} @ {row['company'][:25]}")
        else:
            failed += 1
            logger.warning(f"  [?] failed: {row['title'][:45]} @ {row['company'][:25]}")

        time.sleep(0.5)  # rate limit ~ 2 req/s

    logger.info(f"\nDone. {scored} scored, {failed} failed.")
    conn.close()


if __name__ == "__main__":
    main()
