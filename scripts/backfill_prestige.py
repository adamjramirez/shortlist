#!/usr/bin/env python3
"""Backfill prestige_tier for all visible jobs that don't have one yet.

Run once after deploying the prestige refactor:
    DATABASE_URL=<url> python3 scripts/backfill_prestige.py

Requires DATABASE_URL and config/profile.yaml.
"""
import os
import sys
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras

from shortlist.config import load_config
from shortlist.collectors.base import RawJob
from shortlist.processors.scorer import score_prestige
from shortlist.pgdb import update_job
from shortlist import llm


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    config = load_config(Path("config/profile.yaml"))
    llm.configure(config.llm.model)
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, title, company, url, description, location,
                   salary_text, sources_seen
            FROM jobs
            WHERE fit_score >= 75
              AND NOT is_closed
              AND prestige_tier IS NULL
            ORDER BY fit_score DESC
        """)
        rows = cur.fetchall()

    logger.info(f"Found {len(rows)} jobs to backfill")

    scored = 0
    failed = 0
    for row in rows:
        sources = row["sources_seen"] or []
        source = (sources[0] if isinstance(sources, list) else sources) if sources else "unknown"

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
            update_job(conn, row["id"], prestige_tier=tier)
            conn.commit()
            scored += 1
            logger.info(f"  [{tier}] {row['title'][:45]} @ {row['company'][:25]}")
        else:
            failed += 1
            logger.warning(f"  [?] Failed: {row['title'][:45]} @ {row['company'][:25]}")

        time.sleep(0.5)  # rate limit — 2 req/s

    logger.info(f"\nDone. {scored} scored, {failed} failed.")
    conn.close()


if __name__ == "__main__":
    main()
