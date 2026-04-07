"""Seed curated career page sources from Ben Lang's 2026-04-07 list.

Usage:
    python scripts/seed_career_pages.py [--db-url postgresql://...]

Idempotent — duplicate URLs are silently skipped.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shortlist.pgdb as pgdb

SOURCE = "ben_lang_2026-04-07"

# All 35 companies from Ben Lang's April 7 2026 post.
# ATS detected from career URLs: ashby/greenhouse/lever/yc/direct.
# YC company pages use ats=None (no standard ATS slug pattern).
ENTRIES = [
    {"company_name": "Baba",                   "career_url": "https://jobs.ashbyhq.com/baba",                      "ats": "ashby",    "slug": "baba"},
    {"company_name": "Eolas Medical",           "career_url": "https://www.eolasmedical.com/about-us-and-careers#careers",  "ats": "direct",   "slug": None},
    {"company_name": "InfiniteWatch",           "career_url": "https://infinitewatch.ai/careers#open-positions",   "ats": "direct",   "slug": None},
    {"company_name": "Ando",                    "career_url": "https://www.ando.work/careers",                      "ats": "direct",   "slug": None},
    {"company_name": "Aristotle",               "career_url": "https://www.heyaristotle.com/careers",               "ats": "direct",   "slug": None},
    {"company_name": "ZeroPhase",               "career_url": "https://www.zerophase.de/careers",                   "ats": "direct",   "slug": None},
    {"company_name": "Diffraqtion",             "career_url": "https://diffraqtion.com/careers",                    "ats": "direct",   "slug": None},
    {"company_name": "HammerheadAI",            "career_url": "https://hammerheadco.ai/careers/",                   "ats": "direct",   "slug": None},
    {"company_name": "Powerlattice",            "career_url": "https://powerlatticeinc.com/careers",                "ats": "direct",   "slug": None},
    {"company_name": "Natural",                 "career_url": "https://www.natural.co/careers",                     "ats": "direct",   "slug": None},
    {"company_name": "Tivara",                  "career_url": "https://www.ycombinator.com/companies/tivara/jobs", "ats": "direct",   "slug": None},
    {"company_name": "Cephia AI",               "career_url": "https://www.cephia.ai/careers",                      "ats": "direct",   "slug": None},
    {"company_name": "Grotto AI",               "career_url": "https://jobs.ashbyhq.com/grotto",                    "ats": "ashby",    "slug": "grotto"},
    {"company_name": "Formulary Financial",     "career_url": "https://www.formulary.co/careers",                   "ats": "direct",   "slug": None},
    {"company_name": "Dryft",                   "career_url": "https://dryft.ai/careers",                           "ats": "direct",   "slug": None},
    {"company_name": "Vybe",                    "career_url": "https://www.vybe.build/careers",                     "ats": "direct",   "slug": None},
    {"company_name": "Phoebe",                  "career_url": "https://www.phoebe.work/about",                      "ats": "direct",   "slug": None},
    {"company_name": "Ultra Pouches",           "career_url": "https://takeultra.com/pages/careers",                "ats": "direct",   "slug": None},
    {"company_name": "Unlimited Industries",    "career_url": "https://www.unlimitedindustries.com/careers",        "ats": "direct",   "slug": None},
    {"company_name": "AgentMail",               "career_url": "https://www.agentmail.to/careers#roles",             "ats": "direct",   "slug": None},
    {"company_name": "Brickanta",               "career_url": "https://www.ycombinator.com/companies/brickanta/jobs", "ats": "direct", "slug": None},
    {"company_name": "Rainfall Health",         "career_url": "https://www.rainfallhealth.com/about/careers",       "ats": "direct",   "slug": None},
    {"company_name": "Double Blind Bio",        "career_url": "https://www.notion.so/Open-Roles-2f98afefd3f280d58106c8a53793ac96", "ats": "direct", "slug": None},
    {"company_name": "Antioch",                 "career_url": "https://antioch.com/careers",                        "ats": "direct",   "slug": None},
    {"company_name": "Pensive",                 "career_url": "https://www.pensive.com/schools/careers",            "ats": "direct",   "slug": None},
    {"company_name": "Autoscience Institute",   "career_url": "https://autoscience.ai/careers#open-roles",          "ats": "direct",   "slug": None},
    {"company_name": "Foundry Robotics",        "career_url": "https://jobs.ashbyhq.com/foundry-robotics",          "ats": "ashby",    "slug": "foundry-robotics"},
    {"company_name": "Autonomous Technologies Group", "career_url": "https://jobs.ashbyhq.com/ATG",                 "ats": "ashby",    "slug": "ATG"},
    {"company_name": "Asymmetric Security",     "career_url": "https://www.asymmetricsecurity.com/careers",         "ats": "direct",   "slug": None},
    {"company_name": "Evoke Security",          "career_url": "https://www.evokesecurity.com/careers",              "ats": "direct",   "slug": None},
    {"company_name": "Momentic",                "career_url": "https://jobs.ashbyhq.com/momentic",                  "ats": "ashby",    "slug": "momentic"},
    {"company_name": "GetMint",                 "career_url": "https://team.getmint.ai/job-board",                  "ats": "direct",   "slug": None},
    {"company_name": "Crunched",                "career_url": "https://www.usecrunched.com/careers",                "ats": "direct",   "slug": None},
    {"company_name": "Feltsense",               "career_url": "https://feltsense.com/",                             "ats": "direct",   "slug": None},
    {"company_name": "Lemrock",                 "career_url": "https://www.notion.so/Careers-30cc672d08498017bf3ae0f644539878", "ats": "direct", "slug": None},
]


def main():
    parser = argparse.ArgumentParser(description="Seed curated career page sources")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                        help="PostgreSQL connection URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print entries without inserting")
    args = parser.parse_args()

    if args.dry_run:
        print(f"Would insert {len(ENTRIES)} entries from source={SOURCE!r}:")
        for e in ENTRIES:
            print(f"  {e['ats'] or 'direct':10s}  {e['company_name']}")
        return

    if not args.db_url:
        print("ERROR: --db-url or DATABASE_URL required", file=sys.stderr)
        sys.exit(1)

    conn = pgdb.get_pg_connection(args.db_url)
    pgdb.ensure_career_page_sources_table(conn)
    inserted = pgdb.bulk_add_career_page_sources(conn, ENTRIES, source=SOURCE)
    print(f"Inserted {inserted} / {len(ENTRIES)} entries (duplicates skipped)")

    # Print summary
    rows = pgdb.get_active_career_page_sources(conn)
    print(f"Total active curated sources: {len(rows)}")
    conn.close()


if __name__ == "__main__":
    main()
