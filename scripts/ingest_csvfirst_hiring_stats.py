"""Ingest a CSVFirst per-company hiring-stats snapshot into company_hiring_stats.

Input: CSVFirst "oldest active jobs" CSV (dataset #2). Columns:
    company, total_active_jobs, max_open_days, oldest_job_title,
    oldest_job_open_days, mean_open_days, share_180d_plus, share_365d_plus

Snapshot date is parsed from the filename (e.g. `top_50_oldest_active_jobs-may16-2026.csv`
→ 2026-05-16), with a `--snapshot-date YYYY-MM-DD` override.

Usage:
    DATABASE_URL=... uv run python scripts/ingest_csvfirst_hiring_stats.py <csv-path>
"""
import argparse
import csv
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shortlist.pgdb import (
    ensure_company_hiring_stats_table,
    get_pg_connection,
    upsert_hiring_stats,
)
from shortlist.processors.enricher import _normalize_company

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_snapshot_date_from_filename(name: str) -> date | None:
    """Match patterns like 'may16-2026' or '2026-05-16' anywhere in the filename."""
    m = re.search(r"\b([a-z]{3})(\d{1,2})-(\d{4})\b", name.lower())
    if m and m.group(1) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv", help="Path to the CSVFirst per-company stats CSV")
    p.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--snapshot-date", help="YYYY-MM-DD; overrides filename detection")
    p.add_argument("--source", default="csvfirst", help="source tag (default: csvfirst)")
    args = p.parse_args()

    if not args.db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr); sys.exit(1)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr); sys.exit(1)

    if args.snapshot_date:
        snapshot = date.fromisoformat(args.snapshot_date)
    else:
        snapshot = parse_snapshot_date_from_filename(csv_path.name)
        if not snapshot:
            print(f"ERROR: could not parse snapshot date from {csv_path.name}; "
                  "pass --snapshot-date", file=sys.stderr)
            sys.exit(1)

    print(f"Source={args.source} snapshot_date={snapshot}")

    conn = get_pg_connection(args.db_url)
    ensure_company_hiring_stats_table(conn)

    n = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            upsert_hiring_stats(
                conn,
                company_norm=_normalize_company(row["company"]),
                source=args.source,
                snapshot_date=snapshot,
                total_active_jobs=int(row["total_active_jobs"]) if row.get("total_active_jobs") else None,
                share_180d_plus=float(row["share_180d_plus"]) if row.get("share_180d_plus") else None,
                share_365d_plus=float(row["share_365d_plus"]) if row.get("share_365d_plus") else None,
                mean_open_days=float(row["mean_open_days"]) if row.get("mean_open_days") else None,
                oldest_job_open_days=int(row["oldest_job_open_days"]) if row.get("oldest_job_open_days") else None,
            )
            n += 1
    conn.close()
    print(f"Upserted {n} company-stats rows")


if __name__ == "__main__":
    main()
