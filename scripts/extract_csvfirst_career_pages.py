"""Extract canonical career-page seed entries from a CSVFirst per-job snapshot.

Writes data/career_pages/<name>.json in the format consumed by seed_career_pages.py.

Only emits entries where we can extract a canonical Greenhouse slug from the job URL
(i.e. the URL hits boards.greenhouse.io/<slug> or job-boards.greenhouse.io/<slug>).
Proxied URLs (e.g. careers.airbnb.com?gh_jid=...) are reported but skipped — those
need their slug discovered via discover_ats_from_url, which is a separate concern.

Usage:
    python scripts/extract_csvfirst_career_pages.py <name> --csv <path> \\
        [--companies anthropic,figma,workato]   # restrict to these (case-insensitive)
        [--all]                                 # include every canonical row
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shortlist.collectors.career_page import detect_ats, extract_org_slug

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "career_pages"

# Canonical board URLs per ATS for a given slug
def board_url(ats: str, slug: str) -> str:
    if ats == "greenhouse":
        return f"https://job-boards.greenhouse.io/{slug}"
    if ats == "lever":
        return f"https://jobs.lever.co/{slug}"
    if ats == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}"
    raise ValueError(f"Unknown ats {ats}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name", help="output file stem (data/career_pages/<name>.json)")
    p.add_argument("--csv", required=True)
    p.add_argument("--companies", help="comma-separated company names (case-insensitive)")
    p.add_argument("--all", action="store_true", help="include every canonical row, not just --companies")
    args = p.parse_args()

    if not args.all and not args.companies:
        print("ERROR: pass --companies or --all", file=sys.stderr)
        sys.exit(2)

    target = None
    if args.companies:
        target = {c.strip().lower() for c in args.companies.split(",")}

    # company -> ats -> set(slugs)
    seen: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    skipped_proxied: dict[str, list[str]] = defaultdict(list)

    with open(args.csv, newline="") as f:
        for r in csv.DictReader(f):
            co = r["Company"].strip()
            if target and co.lower() not in target:
                continue
            url = r["Absolute_URL"].strip()
            ats = detect_ats(url)
            if not ats:
                # proxied / direct front, not a canonical ATS URL
                skipped_proxied[co].append(urlparse(url).netloc)
                continue
            slug = extract_org_slug(url, ats)
            if not slug:
                skipped_proxied[co].append(url)
                continue
            seen[co][ats].add(slug)

    entries = []
    for co in sorted(seen):
        for ats, slugs in seen[co].items():
            for slug in sorted(slugs):
                entries.append({
                    "company_name": co,
                    "career_url": board_url(ats, slug),
                    "ats": ats,
                    "slug": slug,
                })

    out = {"source": args.name, "entries": entries}
    out_path = DATA_DIR / f"{args.name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2) + "\n")

    print(f"Wrote {out_path} with {len(entries)} entries")
    if skipped_proxied:
        print()
        print("Companies with proxied URLs (slug unknown — handle separately):")
        from collections import Counter
        for co in sorted(skipped_proxied):
            hosts = Counter(skipped_proxied[co])
            top = ", ".join(f"{h}×{n}" for h, n in hosts.most_common(2))
            print(f"  {co:25s} ({len(skipped_proxied[co])} rows) {top}")


if __name__ == "__main__":
    main()
