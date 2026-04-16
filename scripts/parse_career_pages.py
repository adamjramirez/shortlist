"""Parse an unstructured career-page list into seed JSON.

Input:  data/career_pages/raw/<name>.txt  (free-form paste)
Output: data/career_pages/<name>.json     (structured entries)

Gemini extracts {company_name, career_url} pairs. ATS is classified
deterministically from the URL (ashby/lever/greenhouse/direct).

Usage:
    python scripts/parse_career_pages.py <name>
    python scripts/parse_career_pages.py ben_lang_2026-04-15
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shortlist import llm
from shortlist.config import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "career_pages" / "raw"
OUT_DIR = REPO_ROOT / "data" / "career_pages"

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "career_url": {"type": "string"},
                },
                "required": ["company_name", "career_url"],
            },
        }
    },
    "required": ["entries"],
}

PROMPT = """Extract every (company_name, career_url) pair from the text below.

Rules:
- Include every distinct company, even if mentioned multiple times.
- career_url must be the direct link to their careers/jobs page.
- Preserve the company name exactly as written (including casing, punctuation, suffixes like "Inc.").
- Skip entries that don't have an explicit career URL.
- De-duplicate by company_name (keep the first URL).

TEXT:
---
{text}
---
"""


def classify_ats(url: str) -> tuple[str, str | None]:
    """Return (ats, slug) from a career URL. Deterministic, no LLM."""
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.strip("/")
    first = path.split("/")[0] if path else ""

    if "ashbyhq.com" in host:
        return "ashby", first or None
    if "lever.co" in host:
        return "lever", first or None
    if "greenhouse.io" in host or "boards.greenhouse.io" in host:
        return "greenhouse", first or None
    if "workable.com" in host:
        return "workable", first or None
    return "direct", None


def parse_raw(text: str) -> list[dict]:
    raw = llm.call_llm(PROMPT.format(text=text), json_schema=EXTRACT_SCHEMA)
    if not raw:
        raise RuntimeError("LLM returned empty response")
    data = json.loads(raw)
    entries = data.get("entries", [])
    seen = set()
    out = []
    for e in entries:
        name = e["company_name"].strip()
        url = e["career_url"].strip()
        if name in seen or not url:
            continue
        seen.add(name)
        ats, slug = classify_ats(url)
        out.append({
            "company_name": name,
            "career_url": url,
            "ats": ats,
            "slug": slug,
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="Parse unstructured career-page list → seed JSON")
    parser.add_argument("name", help="List name (matches file stem in data/career_pages/raw/)")
    parser.add_argument("--config", default="config/profile.yaml", help="Config file for LLM model")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args()

    raw_path = RAW_DIR / f"{args.name}.txt"
    out_path = OUT_DIR / f"{args.name}.json"

    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found", file=sys.stderr)
        sys.exit(1)
    if out_path.exists() and not args.overwrite:
        print(f"ERROR: {out_path} exists (use --overwrite)", file=sys.stderr)
        sys.exit(1)

    config = load_config(Path(args.config))
    llm.configure(config.llm.model)

    text = raw_path.read_text()
    print(f"Parsing {raw_path.name} ({len(text)} chars) with {config.llm.model}...")
    entries = parse_raw(text)
    print(f"Extracted {len(entries)} entries")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"source": args.name, "entries": entries}, indent=2) + "\n")
    print(f"Wrote {out_path}")

    counts = {}
    for e in entries:
        counts[e["ats"]] = counts.get(e["ats"], 0) + 1
    print("ATS breakdown:", counts)


if __name__ == "__main__":
    main()
