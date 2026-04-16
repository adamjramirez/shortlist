"""Resolve the real ATS/slug for curated sources stored as ats='direct'.

Many career page URLs (cursor.com/careers, harvey.ai/careers) are landing
pages that embed jobs from Ashby/Greenhouse/Lever/Workable via iframe or
JS. This script fetches each direct career page and greps for the ATS slug.
When found, updates the row's ats + slug so the curated collector uses the
native ATS fetcher on the next run.

Usage:
    # Local dry-run (prints findings)
    python scripts/resolve_direct_ats.py --dry-run

    # Apply updates against prod (requires fly proxy)
    fly proxy 15432:5432 -a shortlist-db          # in another terminal
    DATABASE_URL=postgres://shortlist_web:...@localhost:15432/shortlist_web?sslmode=disable \\
        python scripts/resolve_direct_ats.py

    # Only one list
    python scripts/resolve_direct_ats.py --source ben_lang_2026-04-15

Safe to re-run — only updates rows where ats='direct'.
"""
import argparse
import os
import re
import sys
from dataclasses import dataclass

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shortlist.pgdb as pgdb

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 15.0

# Order matters: first match wins. Ashby/Greenhouse/Lever before workable.
# Slug must be at least 2 chars, alphanumeric + dash + underscore.
_SLUG = r"([a-zA-Z0-9][a-zA-Z0-9_-]+)"
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ashby",      re.compile(rf"jobs\.ashbyhq\.com/{_SLUG}")),
    ("ashby",      re.compile(rf"api\.ashbyhq\.com/posting-api/job-board/{_SLUG}")),
    ("greenhouse", re.compile(rf"boards\.greenhouse\.io/{_SLUG}")),
    ("greenhouse", re.compile(rf"job-boards\.greenhouse\.io/{_SLUG}")),
    ("greenhouse", re.compile(rf"boards-api\.greenhouse\.io/v1/boards/{_SLUG}")),
    ("greenhouse", re.compile(rf"api\.greenhouse\.io/v1/boards/{_SLUG}")),
    ("greenhouse", re.compile(rf"greenhouse\.io/embed/job_board[^\"']*?for={_SLUG}")),
    ("lever",      re.compile(rf"jobs\.lever\.co/{_SLUG}")),
    ("lever",      re.compile(rf"api\.lever\.co/v0/postings/{_SLUG}")),
    ("workable",   re.compile(rf"apply\.workable\.com/{_SLUG}")),
]

# Slugs to ignore (generic JS/library names that can appear in page HTML).
SLUG_BLOCKLIST = {
    "embed", "api", "widgets", "js", "static", "assets", "www", "careers",
    "job_board", "posting-api",
}


@dataclass
class Resolved:
    ats: str
    slug: str


def detect(html: str) -> Resolved | None:
    for ats, pattern in PATTERNS:
        for match in pattern.finditer(html):
            slug = match.group(1)
            if slug.lower() in SLUG_BLOCKLIST:
                continue
            return Resolved(ats=ats, slug=slug)
    return None


def fetch_html(url: str, client: httpx.Client) -> str | None:
    try:
        r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=TIMEOUT)
        if r.status_code >= 400:
            return None
        return r.text
    except Exception as e:
        print(f"  fetch failed: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--source", help="Only resolve rows with this source attribution")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db_url:
        print("ERROR: --db-url or DATABASE_URL required", file=sys.stderr)
        sys.exit(1)

    conn = pgdb.get_pg_connection(args.db_url)
    cur = conn.cursor()

    where = "WHERE ats = 'direct' AND status = 'active'"
    params: list = []
    if args.source:
        where += " AND source = %s"
        params.append(args.source)

    cur.execute(
        f"SELECT id, company_name, career_url FROM career_page_sources {where} ORDER BY company_name",
        params,
    )
    rows = cur.fetchall()
    print(f"Found {len(rows)} direct sources to resolve\n")

    resolved_count = 0
    unresolved = []
    with httpx.Client() as client:
        for row in rows:
            row_id = row["id"]
            company = row["company_name"]
            url = row["career_url"]
            html = fetch_html(url, client)
            if not html:
                print(f"  {company:30s} ✗ fetch failed")
                unresolved.append(company)
                continue

            hit = detect(html)
            if not hit:
                print(f"  {company:30s} — no ATS detected ({url})")
                unresolved.append(company)
                continue

            print(f"  {company:30s} → {hit.ats}/{hit.slug}")
            resolved_count += 1
            if not args.dry_run:
                cur.execute(
                    "UPDATE career_page_sources SET ats = %s, slug = %s WHERE id = %s",
                    (hit.ats, hit.slug, row_id),
                )

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\nResolved {resolved_count} / {len(rows)}")
    if unresolved:
        print(f"Unresolved ({len(unresolved)}): {', '.join(unresolved)}")


if __name__ == "__main__":
    main()
