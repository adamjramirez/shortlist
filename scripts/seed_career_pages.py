"""Seed curated career page sources from a structured data file.

Input:  data/career_pages/<name>.json  (produced by parse_career_pages.py
        or handwritten — format: {"source": "<name>", "entries": [...]})

Usage:
    python scripts/seed_career_pages.py <name> [--db-url postgresql://...]
    python scripts/seed_career_pages.py ben_lang_2026-04-15

For prod: run `fly proxy 15432:5432 -a shortlist-db` in another terminal,
then export DATABASE_URL=postgres://user:pass@localhost:15432/shortlist_web

Idempotent — duplicate URLs are silently skipped.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shortlist.pgdb as pgdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "career_pages"


def main():
    parser = argparse.ArgumentParser(description="Seed curated career page sources from a JSON list")
    parser.add_argument("name", help="List name (matches file stem in data/career_pages/)")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = DATA_DIR / f"{args.name}.json"
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(path.read_text())
    source = payload.get("source", args.name)
    entries = payload["entries"]

    if args.dry_run:
        print(f"Would insert {len(entries)} entries from source={source!r}:")
        for e in entries:
            print(f"  {e['ats']:10s}  {e['company_name']}")
        return

    if not args.db_url:
        print("ERROR: --db-url or DATABASE_URL required", file=sys.stderr)
        sys.exit(1)

    conn = pgdb.get_pg_connection(args.db_url)
    pgdb.ensure_career_page_sources_table(conn)
    inserted = pgdb.bulk_add_career_page_sources(conn, entries, source=source)
    print(f"Inserted {inserted} / {len(entries)} entries (duplicates skipped)")
    rows = pgdb.get_active_career_page_sources(conn)
    print(f"Total active curated sources: {len(rows)}")
    conn.close()


if __name__ == "__main__":
    main()
