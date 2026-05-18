"""Bulk-reopen jobs that were false-closed by `last_seen_stale` for companies
that now have an active observer in career_page_sources.

Safety predicates (a row is only reopened if ALL of these hold):
  1. closed_reason = 'last_seen_stale' (not user/age_expired/etc)
  2. company is in --companies (default: the 7 known-affected from 2026-05-17 incident)
  3. an active CPS row exists for the company with last_checked_at within the
     last 24h AND last_jobs_count > 0 (we just successfully observed that source)

NOT predicated on per-URL liveness — that would require either re-fetching every
URL or having another user with a recent refresh of the same URL. The active-observer
signal is the right tri-state: any URL we reopen that's actually closed at source
will get re-closed by the NEXT sweep pass anyway. Bounded blast radius.

Read-only by default. Use --apply to write.

Usage:
    DATABASE_URL=... uv run python scripts/bulk_reopen_false_closes.py            # dry-run
    DATABASE_URL=... uv run python scripts/bulk_reopen_false_closes.py --apply    # write
    DATABASE_URL=... uv run python scripts/bulk_reopen_false_closes.py --companies "Anthropic,Figma"
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras

DEFAULT_COMPANIES = [
    "Anthropic", "Anduril Industries", "Figma", "Workato",
    "Airbnb", "Five9", "Samsara",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    p.add_argument("--companies", default=",".join(DEFAULT_COMPANIES),
                   help="comma-separated company names to reopen")
    args = p.parse_args()

    if not args.db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr); sys.exit(1)

    companies = [c.strip() for c in args.companies.split(",") if c.strip()]

    conn = psycopg2.connect(args.db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False

    # Single query: select reopen-eligible rows.
    select_sql = """
        WITH active_companies AS (
            -- Companies whose CPS row was successfully checked in the last 24h
            -- AND returned at least one job (proves the fetch actually worked).
            SELECT DISTINCT LOWER(company_name) AS company_norm
            FROM career_page_sources
            WHERE status = 'active'
              AND last_checked_at > NOW() - INTERVAL '24 hours'
              AND last_jobs_count > 0
        )
        SELECT j.id, j.user_id, j.company, j.title, j.url,
               j.last_seen::date AS last_seen, j.closed_at::date AS closed_at
        FROM jobs j
        WHERE j.is_closed = true
          AND j.closed_reason = 'last_seen_stale'
          AND j.company = ANY(%s)
          AND LOWER(j.company) IN (SELECT company_norm FROM active_companies)
        ORDER BY j.company, j.user_id, j.id
    """

    with conn.cursor() as cur:
        cur.execute(select_sql, (companies,))
        eligible = cur.fetchall()

    if not eligible:
        print("No eligible rows. (Either no false closes, no active observer for these companies, or no URL is currently live for them.)")
        conn.close()
        return

    # Summary
    by_company: dict[str, int] = {}
    by_user: dict[int, int] = {}
    for row in eligible:
        by_company[row["company"]] = by_company.get(row["company"], 0) + 1
        by_user[row["user_id"]] = by_user.get(row["user_id"], 0) + 1

    print(f"{'APPLY' if args.apply else 'DRY-RUN'} — {len(eligible)} eligible rows")
    print()
    print("By company:")
    for co, n in sorted(by_company.items(), key=lambda x: -x[1]):
        print(f"  {co:25s} {n:>5}")
    print()
    print("By user (top 10):")
    for uid, n in sorted(by_user.items(), key=lambda x: -x[1])[:10]:
        print(f"  user_id={uid:>3}  {n:>5}")
    print()
    print("Sample (first 10):")
    for row in eligible[:10]:
        print(f"  id={row['id']:>5} user={row['user_id']:>3} {row['company']:20s} {row['title'][:50]}")

    if not args.apply:
        print()
        print("(dry-run) re-run with --apply to write")
        conn.close()
        return

    # Apply
    ids = [row["id"] for row in eligible]
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE jobs
               SET is_closed = false, closed_reason = NULL, closed_at = NULL
               WHERE id = ANY(%s)
                 AND closed_reason = 'last_seen_stale'""",
            (ids,),
        )
        n = cur.rowcount
    conn.commit()
    print()
    print(f"Reopened {n} rows. Committed.")
    conn.close()


if __name__ == "__main__":
    main()
