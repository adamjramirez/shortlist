#!/usr/bin/env python3
"""Pull PostHog analytics for shortlist.addslift.com.

Usage:
    python scripts/posthog_report.py            # Last 7 days
    python scripts/posthog_report.py --days 28
"""

import argparse
import json
import os
import sys
import urllib.request

PROJECT_ID = 139823
BASE_URL = "https://eu.posthog.com"
PROD_HOST = "shortlist.addslift.com"


def _load_api_key() -> str | None:
    for var in ("POSTHOG_API_KEY_SHORTLIST", "POSTHOG_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    keys_file = os.path.expanduser("~/.posthog_keys")
    if os.path.exists(keys_file):
        with open(keys_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("POSTHOG_API_KEY_SHORTLIST="):
                    return line.split("=", 1)[1]
    return None


def hogql(query_str: str, api_key: str) -> list:
    url = f"{BASE_URL}/api/projects/{PROJECT_ID}/query/"
    data = json.dumps({"query": {"kind": "HogQLQuery", "query": query_str}}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read()).get("results", [])


PV_PROD = f"AND properties.$current_url LIKE '%{PROD_HOST}%' "


def main():
    parser = argparse.ArgumentParser(description="PostHog analytics for shortlist.addslift.com")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    d = args.days

    api_key = _load_api_key()
    if not api_key:
        print("No API key. Set POSTHOG_API_KEY_SHORTLIST or add to ~/.posthog_keys")
        sys.exit(1)

    def q(s):
        return hogql(s, api_key)

    print("=" * 60)
    print(f"  shortlist.addslift.com — last {d} days")
    print("=" * 60, "\n")

    rows = q(f"SELECT count(), count(DISTINCT person_id), countIf(event='$pageview' {PV_PROD}) FROM events WHERE timestamp >= now() - interval {d} day")
    if rows:
        total, users, pvs = rows[0]
        print(f"  Events: {total:,} | Users: {users:,} | Pageviews: {pvs:,}\n")

    print("=== DAILY ===")
    for day, pvs, users in q(f"SELECT toDate(timestamp) as day, countIf(event='$pageview' {PV_PROD}) as pvs, count(DISTINCT person_id) as users FROM events WHERE timestamp >= now() - interval {d} day GROUP BY day ORDER BY day"):
        print(f"  {day} | {pvs:>4} pvs | {users:>4} users")

    print("\n=== TOP PAGES ===")
    for url, v in q(f"SELECT properties.$current_url as url, count() as v FROM events WHERE event='$pageview' AND timestamp >= now() - interval {d} day {PV_PROD} GROUP BY url ORDER BY v DESC LIMIT 20"):
        print(f"  {v:>5}  {url}")

    print("\n=== REFERRERS ===")
    for ref, v in q(f"SELECT properties.$referrer as r, count() as v FROM events WHERE event='$pageview' AND timestamp >= now() - interval {d} day AND properties.$referrer != '' AND properties.$referrer IS NOT NULL {PV_PROD} GROUP BY r ORDER BY v DESC LIMIT 15"):
        print(f"  {v:>5}  {ref}")

    print("\n=== CUSTOM EVENTS ===")
    rows = q(f"SELECT event, count() as c FROM events WHERE timestamp >= now() - interval {d} day AND event NOT LIKE '$%' GROUP BY event ORDER BY c DESC LIMIT 30")
    if rows:
        for ev, c in rows:
            print(f"  {c:>5}  {ev}")
    else:
        print("  (none)")

    print("\n=== DEVICES ===")
    for dev, u in q(f"SELECT properties.$device_type as d, count(DISTINCT person_id) as u FROM events WHERE event='$pageview' AND timestamp >= now() - interval {d} day {PV_PROD} GROUP BY d ORDER BY u DESC"):
        print(f"  {u:>5}  {dev or '(unknown)'}")

    print("\n=== PER-USER JOURNEY ===")
    # auth-context.tsx: posthog.identify(String(user.id), { email: user.email })
    # → distinct_id = our backend user_id, person.properties.email = their email
    user_rows = q(
        f"SELECT distinct_id, person.properties.email as email, count() as events, "
        f"min(timestamp) as first_seen, max(timestamp) as last_seen "
        f"FROM events WHERE timestamp >= now() - interval {d} day "
        f"GROUP BY distinct_id, email ORDER BY events DESC LIMIT 20"
    )
    if not user_rows:
        print("  (no user events)")
    for did, email, events, first, last in user_rows:
        label = email or f"anon({did[:8] if did else '?'})"
        # Timestamps come back as ISO strings from HogQL — slice to YYYY-MM-DD HH:MM
        first_s = str(first)[:16] if first else "?"
        last_s = str(last)[:16] if last else "?"
        print(f"\n  user {did} ({label}) — {events} events, {first_s} → {last_s}")
        # Event-type breakdown for this user, excluding pageviews/noisy PostHog internals
        ev_rows = q(
            f"SELECT event, count() as c FROM events "
            f"WHERE distinct_id = '{did}' AND timestamp >= now() - interval {d} day "
            f"AND event NOT LIKE '$%' GROUP BY event ORDER BY c DESC LIMIT 12"
        )
        if not ev_rows:
            print("    (pageviews only, no custom events)")
            continue
        for ev, c in ev_rows:
            print(f"    {c:>3}  {ev}")


if __name__ == "__main__":
    main()
