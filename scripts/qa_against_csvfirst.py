"""QA shortlist's job pipeline against a CSVFirst ground-truth snapshot.

CSVFirst is an independent observer of Greenhouse-ATS postings across 200+ companies.
By diffing their snapshot against our DB we can detect failure modes that have no
internal signal:

  1. False-close detection      — jobs we marked is_closed=true that CSVFirst still
                                  shows active (likely expiry-checker false positives,
                                  like the 2026-04-16 incident)
  2. Coverage-gap detection     — companies where our active count is far below
                                  CSVFirst's total (collector miss / missing from
                                  career_page_sources)
  3. Posting-age drift          — for URLs in both, compare CSVFirst Published_At
                                  vs our posted_at (collector date-extraction bugs)
  4. Stale-company audit        — for companies with high share_180d_plus, what
                                  fraction of their jobs do we still treat as fresh?
                                  (requires --oldest CSV, dataset #2)

Read-only. No DB writes. Outputs a markdown report.

Usage:
    # Local (against any reachable PG)
    DATABASE_URL=postgres://... python scripts/qa_against_csvfirst.py \\
        --csv path/to/sample_2k_jobs.csv

    # Prod (run `fly proxy 15432:5432 -a shortlist-db` first)
    DATABASE_URL=postgres://shortlist_web:PW@localhost:15432/shortlist_web?sslmode=disable \\
        python scripts/qa_against_csvfirst.py \\
            --csv ~/Downloads/sample_2k_jobs.csv \\
            --oldest ~/Downloads/top_50_oldest_active_jobs.csv \\
            --out docs/qa/csvfirst_2026-05-17.md
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2
import psycopg2.extras

from shortlist.processors.enricher import _normalize_company


# ----- helpers -----

def normalize_url(url: str) -> str:
    """Strip query params + fragment + trailing slash for join-key purposes."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
        path = p.path.rstrip("/")
        return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", "", "")).rstrip("/")
    except Exception:
        return url.strip().lower()


def parse_iso(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_csvfirst_jobs(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "company": r["Company"].strip(),
                "company_norm": _normalize_company(r["Company"]),
                "title": r["Job_Title"].strip(),
                "location": r.get("Location", "").strip(),
                "url": r["Absolute_URL"].strip(),
                "url_key": normalize_url(r["Absolute_URL"]),
                "published_at": parse_iso(r.get("Published_At", "")),
                "open_days": int(r["open_days"]) if r.get("open_days") else None,
                "total_active_company": int(r["total_active_jobs_company"])
                    if r.get("total_active_jobs_company") else None,
            })
    return rows


def load_oldest(path: Path) -> dict[str, dict]:
    """Returns {company_normalized: {share_180d_plus, share_365d_plus, ...}}."""
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out[_normalize_company(r["company"])] = {
                "company": r["company"],
                "total_active": int(r["total_active_jobs"]),
                "share_180d": float(r["share_180d_plus"]),
                "share_365d": float(r["share_365d_plus"]),
                "mean_days": float(r["mean_open_days"]),
                "oldest_days": int(r["oldest_job_open_days"]),
            }
    return out


# ----- checks -----

def check_false_closes(conn, cf_rows: list[dict]) -> list[dict]:
    """Jobs we marked is_closed=true but CSVFirst shows as active."""
    url_keys = [r["url_key"] for r in cf_rows if r["url_key"]]
    if not url_keys:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, url, company, title, is_closed, closed_reason,
                   last_seen, posted_at
            FROM jobs
            WHERE is_closed = true
            """,
        )
        ours_closed = cur.fetchall()
    by_key: dict[str, list[dict]] = defaultdict(list)
    for row in ours_closed:
        by_key[normalize_url(row["url"])].append(dict(row))

    # Dedupe by URL: same closed job appears once per affected user, but it's one bug.
    hits_by_url: dict[str, dict] = {}
    for cf in cf_rows:
        for our in by_key.get(cf["url_key"], []):
            if our.get("closed_reason") == "user":
                continue  # user-closed = intentional, not a bug
            h = hits_by_url.setdefault(cf["url_key"], {
                "url": cf["url"],
                "company": cf["company"],
                "title": cf["title"],
                "csvfirst_open_days": cf["open_days"],
                "closed_reasons": set(),
                "n_users_affected": 0,
                "max_last_seen": None,
            })
            h["closed_reasons"].add(our.get("closed_reason") or "<null>")
            h["n_users_affected"] += 1
            ls = our.get("last_seen")
            if ls and (h["max_last_seen"] is None or ls > h["max_last_seen"]):
                h["max_last_seen"] = ls
    return sorted(hits_by_url.values(),
                  key=lambda h: (h["csvfirst_open_days"] or 0), reverse=True)


def check_coverage_gaps(conn, cf_rows: list[dict]) -> list[dict]:
    """Per-company: distinct active URLs in our DB vs CSVFirst's reported total."""
    # CSVFirst total per company (same number on every row for that company)
    cf_total: dict[str, tuple[str, int]] = {}
    for r in cf_rows:
        if r["total_active_company"] and r["company_norm"] not in cf_total:
            cf_total[r["company_norm"]] = (r["company"], r["total_active_company"])

    if not cf_total:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT company, COUNT(DISTINCT url) AS n_open
            FROM jobs
            WHERE is_closed = false
            GROUP BY company
            """,
        )
        ours = {_normalize_company(row["company"]): row["n_open"] for row in cur.fetchall()}

    gaps = []
    for cnorm, (cname, cf_n) in cf_total.items():
        our_n = ours.get(cnorm, 0)
        ratio = our_n / cf_n if cf_n else 0
        gaps.append({
            "company": cname,
            "csvfirst_active": cf_n,
            "our_active": our_n,
            "ratio": ratio,
            "missing": cf_n - our_n,
        })
    return sorted(gaps, key=lambda g: g["missing"], reverse=True)


def check_age_drift(conn, cf_rows: list[dict]) -> list[dict]:
    """For URLs in both, compare CSVFirst Published_At vs our posted_at."""
    by_key = {r["url_key"]: r for r in cf_rows if r["url_key"] and r["published_at"]}
    if not by_key:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT url, MAX(posted_at) AS posted_at, MIN(first_seen) AS first_seen,
                   ARRAY_AGG(DISTINCT company) AS companies
            FROM jobs
            WHERE posted_at IS NOT NULL
            GROUP BY url
            """,
        )
        ours = {normalize_url(row["url"]): dict(row) for row in cur.fetchall()}

    drifts = []
    for key, cf in by_key.items():
        our = ours.get(key)
        if not our:
            continue
        ours_dt = our["posted_at"]
        if ours_dt is None:
            continue
        cf_dt = cf["published_at"]
        if cf_dt.tzinfo is None:
            cf_dt = cf_dt.replace(tzinfo=timezone.utc)
        if ours_dt.tzinfo is None:
            ours_dt = ours_dt.replace(tzinfo=timezone.utc)
        delta_days = abs((cf_dt - ours_dt).days)
        if delta_days >= 7:  # tolerate ±1 week
            drifts.append({
                "url": cf["url"],
                "company": cf["company"],
                "title": cf["title"],
                "csvfirst_published_at": cf_dt.date().isoformat(),
                "our_posted_at": ours_dt.date().isoformat(),
                "delta_days": delta_days,
            })
    return sorted(drifts, key=lambda d: d["delta_days"], reverse=True)


def check_stale_company_audit(conn, oldest: dict[str, dict]) -> list[dict]:
    """For high-share_180d_plus companies, what % of our jobs are still 'fresh'?"""
    if not oldest:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT company,
                   COUNT(*) FILTER (WHERE is_closed = false) AS n_open,
                   COUNT(*) FILTER (WHERE is_closed = false
                                    AND status IN ('scored', 'low_score')) AS n_scored,
                   COUNT(*) FILTER (WHERE is_closed = false
                                    AND posted_at < NOW() - INTERVAL '180 days') AS n_old
            FROM jobs
            GROUP BY company
            """,
        )
        ours = {_normalize_company(row["company"]): dict(row) for row in cur.fetchall()}

    rows = []
    for cnorm, meta in oldest.items():
        our = ours.get(cnorm)
        if not our:
            rows.append({**meta, "our_open": 0, "our_scored": 0, "our_old": 0,
                         "we_track": False})
            continue
        rows.append({
            **meta,
            "our_open": our["n_open"],
            "our_scored": our["n_scored"],
            "our_old": our["n_old"],
            "we_track": True,
        })
    return sorted(rows, key=lambda r: r["share_180d"], reverse=True)


# ----- report -----

def render_report(false_closes, gaps, drifts, stale, *, n_cf_rows: int, oldest_loaded: bool) -> str:
    lines: list[str] = []
    lines.append(f"# CSVFirst QA — {datetime.now().date().isoformat()}")
    lines.append("")
    lines.append(f"Snapshot rows: {n_cf_rows}")
    lines.append("")

    # 1
    lines.append(f"## 1. False closes — {len(false_closes)} unique URLs")
    lines.append("Jobs we marked `is_closed=true` (non-user) that CSVFirst shows as active. "
                 "Deduped by URL; `users` = number of distinct users whose row was closed.")
    lines.append("")
    if false_closes:
        lines.append("| Company | Title | Closed reason(s) | Open in CSVFirst (d) | Users | Last seen | URL |")
        lines.append("|---|---|---|---:|---:|---|---|")
        for h in false_closes[:50]:
            reasons = ", ".join(sorted(h["closed_reasons"]))
            last_seen = h["max_last_seen"].date().isoformat() if h["max_last_seen"] else "-"
            lines.append(f"| {h['company']} | {h['title'][:60]} | {reasons} | "
                         f"{h['csvfirst_open_days']} | {h['n_users_affected']} | {last_seen} | {h['url']} |")
        if len(false_closes) > 50:
            lines.append(f"\n_…and {len(false_closes) - 50} more_")
    else:
        lines.append("_None — expiry checker is clean against this snapshot._")
    lines.append("")

    # 2
    real_gaps = [g for g in gaps if g["missing"] >= 5]
    lines.append(f"## 2. Coverage gaps — {len(real_gaps)} companies with ≥5 missing jobs")
    lines.append("CSVFirst's company-level totals vs our distinct open URLs.")
    lines.append("")
    if real_gaps:
        lines.append("| Company | CSVFirst active | Our active | Missing | Coverage |")
        lines.append("|---|---:|---:|---:|---:|")
        for g in real_gaps[:30]:
            lines.append(f"| {g['company']} | {g['csvfirst_active']} | {g['our_active']} | "
                         f"{g['missing']} | {g['ratio']:.0%} |")
        if len(real_gaps) > 30:
            lines.append(f"\n_…and {len(real_gaps) - 30} more_")
    else:
        lines.append("_None._")
    lines.append("")

    # 3
    lines.append(f"## 3. Posting-age drift — {len(drifts)} URLs with ≥7d divergence")
    lines.append("URLs present in both datasets where our `posted_at` disagrees with CSVFirst.")
    lines.append("")
    if drifts:
        lines.append("| Company | Title | CSVFirst published | Our posted_at | Δ days |")
        lines.append("|---|---|---|---|---:|")
        for d in drifts[:30]:
            lines.append(f"| {d['company']} | {d['title'][:50]} | {d['csvfirst_published_at']} | "
                         f"{d['our_posted_at']} | {d['delta_days']} |")
        if len(drifts) > 30:
            lines.append(f"\n_…and {len(drifts) - 30} more_")
    else:
        lines.append("_None._")
    lines.append("")

    # 4
    lines.append("## 4. Stale-company audit")
    if not oldest_loaded:
        lines.append("_Skipped — pass `--oldest <csv>` to enable._")
    elif stale:
        lines.append("Companies with high evergreen-req share — how many we still treat as scoreable.")
        lines.append("")
        lines.append("| Company | 180d+ share | Our open | Our scored | Our open >180d |")
        lines.append("|---|---:|---:|---:|---:|")
        for s in stale[:30]:
            mark = "" if s.get("we_track") else " _(not tracked)_"
            lines.append(f"| {s['company']}{mark} | {s['share_180d']:.0%} | "
                         f"{s['our_open']} | {s['our_scored']} | {s['our_old']} |")
    else:
        lines.append("_No matching companies in our DB._")
    lines.append("")

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="QA shortlist DB against a CSVFirst snapshot.")
    p.add_argument("--csv", required=True, help="Path to CSVFirst per-job CSV (dataset #1)")
    p.add_argument("--oldest", help="Path to oldest-jobs per-company CSV (dataset #2, optional)")
    p.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--out", help="Write report to this file (default: stdout)")
    args = p.parse_args()

    if not args.db_url:
        print("ERROR: DATABASE_URL not set and --db-url not provided", file=sys.stderr)
        sys.exit(1)

    cf_rows = load_csvfirst_jobs(Path(args.csv))
    oldest = load_oldest(Path(args.oldest)) if args.oldest else {}

    conn = psycopg2.connect(args.db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        false_closes = check_false_closes(conn, cf_rows)
        gaps = check_coverage_gaps(conn, cf_rows)
        drifts = check_age_drift(conn, cf_rows)
        stale = check_stale_company_audit(conn, oldest)
    finally:
        conn.close()

    report = render_report(
        false_closes, gaps, drifts, stale,
        n_cf_rows=len(cf_rows), oldest_loaded=bool(oldest),
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"Wrote {out_path} ({len(report.splitlines())} lines)", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
