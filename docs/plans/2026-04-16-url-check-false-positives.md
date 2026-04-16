# 2026-04-16 — `url_check` false-positive closures

## Problem

User-visible inbox dropped 54 → 25 → 3 over ~4 hours on 2026-04-16. Prod diagnostic shows **59 visible jobs (fit_score ≥ 75) auto-closed in the last 48h, all via `closed_reason='url_check'`** — 29 of them in the 2026-04-16 10:00-17:00 UTC window that matches the user's observation.

Closures include jobs that are almost certainly still live:
- **id=11179** "Jobgether: VP of Automation Engineering" — posted 2026-04-16, last_seen 2026-04-16 10:17 UTC, closed 2026-04-16 16:01 UTC. 6 hours between "saw it fine" and "marked gone."
- Reputable companies that don't flash-remove postings: **Oracle, Pinterest, Lyra Health, AlphaSense, Coinbase, Fivetran, Natera**.

Meanwhile, the 2026-04-15 18:00 UTC `last_seen_stale` sweep hit 2285 jobs — only 3 of those were visible. That sweep is working correctly. **The per-URL checker is the one producing false positives.**

## Non-goal

Don't touch the `last_seen_stale` pass — it's healthy. Don't change `closed_reason='user'` handling — sacred.

## Execution order

1. **Step 1** — Live URL test (verify hypothesis on id=11179 before changing anything)
2. **Step 2** — Ship `DISABLE_URL_CHECK` env-var gate (prevents re-closure between reopen and fix)
3. **Step 3** — SQL reopen on prod (all users, 7 days, score≥75, not-skipped)
4. **Step 4** — Read `shortlist/expiry.py`; document per-source behavior
5. **Step 5** — Implement fix (4a per-source gone signals + 4b recency skip)
6. **Step 6** — Tests
7. **Step 7** — Deploy, remove gate, monitor 48h
8. **Step 8** — Decide whether 4c (2-strike rule) is needed

## Step 1 — Live URL test

Before touching code, confirm the hypothesis. Pick id=11179 from prod. Fetch its stored URL through `shortlist.http` with the same path the expiry checker uses. Record: status, headers, body first 500 chars. Confirm whether the checker's current logic would mark it gone on this response.

Fail-fast check that tells us whether the bug is in the URL checker or somewhere weirder (e.g., URL got rewritten, proxy returned captcha page the parser mis-reads as "gone").

**Proceed only if confirmed.** If the URL genuinely returns 404 or a "gone" page, the problem is upstream (why is something that was live 6 hours ago now 404?) and this plan is wrong.

## Step 2 — Ship `DISABLE_URL_CHECK` env-var gate

The scheduler's expiry checker fires every tick. If we reopen at T and the fix deploys at T+1 hour, the next expiry pass can close them all again before the code change lands.

Add a one-line gate at the top of `run_expiry_checks` in `shortlist/scheduler.py` (or wherever the scheduler tick calls the expiry pass):

```python
if os.environ.get("DISABLE_URL_CHECK") == "1":
    return
```

Deploy this small change first. Then set the Fly secret. Then proceed to Step 3.

Alternatives considered and rejected:
- **Ship the full fix first, reopen second** — safest but leaves users with a broken inbox until all code lands. Not acceptable given impact.
- **Reopen and accept re-closure risk** — requires babysitting. Ugly.

## Step 3 — SQL reopen on prod

```sql
UPDATE jobs
SET is_closed = false,
    closed_at = NULL,
    closed_reason = NULL
WHERE is_closed = true
  AND closed_reason = 'url_check'
  AND closed_at > NOW() - INTERVAL '7 days'
  AND fit_score >= 75
  AND (user_status IS NULL OR user_status IN ('saved', 'applied'));
```

**Scoping decisions:**
- **All users, not just user_id=2.** The bug is in `expiry.py`, not per-user. 10 users on prod — any of them hit by the same checker.
- **7-day window** — widen so we also recover earlier false positives not yet noticed.
- **Include `saved`/`applied`, exclude `skipped`.** A saved job that falsely closed shows as "saved + closed" (confusing UI). Skipped stays closed — resurrecting user-skipped jobs would be worse.

**Verify after:**
- User 2's inbox (score>=75, open, untriaged) should jump from 3 to ~60+
- Per-user counts logged so we know blast radius across accounts
- Spot-check 3-5 URLs in a browser **before** running (id=11179 is the cleanest test case)

## Step 4 — Read `shortlist/expiry.py`

For each source's URL-check function, document:
- What HTTP status codes are treated as "gone"
- What happens on timeout / DNS failure / proxy error / 403 / 429 / 5xx
- Whether redirects are followed

**Hypothesis (confirm, don't assume):** the checker treats non-200 / non-404 responses as "gone" when it should treat them as "unknown." Proxy transient failures on LinkedIn HEAD checks are the most likely offender — we rotate through 6 Decodo endpoints; any single one returning 502/timeout could trigger a close if the code doesn't distinguish "definitely gone" from "couldn't check right now."

Also suspicious: **Jobgether** is a job aggregator, not a standalone ATS. How is its URL being checked? Probably falls through to the LinkedIn-style HEAD path or a generic handler — unclear it's even matched to a real checker.

## Step 5 — Implement the fix

### 5a — Per-source explicit gone signals. Everything else = unknown.

Not a blanket "only 404" rule — each source has its own gone signal:

| Source | Gone signal | Everything else |
|---|---|---|
| LinkedIn | HEAD → 404 | 403/429/5xx/timeout/proxy-error → unknown |
| Greenhouse | API 404 | unknown |
| Lever | API 404 | unknown |
| Ashby | GET 200 + title === "Jobs" | non-200 / title mismatch / parse error → unknown |
| HN | (verify — likely no url_check, age-based only via `last_seen_stale`) | — |
| Generic/career_page | **No url_check at all** — too many shapes to classify reliably | — |

Change each source's check function to return a tri-state: `gone=True` (explicit), `gone=False` (explicit live), `gone=None` (unknown).

Caller (`run_expiry_checks`) closes only on explicit `gone=True`. `gone=None` = skip, retry next tick.

### 5b — Recency skip (primary defense)

Before any HTTP call in the checker, skip `url_check` entirely if `last_seen > NOW() - 24 hours`.

Rationale: if we've successfully collected the job in the last day, a failed HEAD right now is vastly more likely to be a transient network issue than the job actually being removed. id=11179 (last_seen 10:17, closed 16:01) would have been saved with this alone.

**Zero new schema.** Cheapest, highest-leverage change. Keeps the checker useful for the old-backlog cleanup case (jobs last seen days ago) without chasing ghosts on fresh data.

### 5c — 2-strike rule (deferred — only if 5a+5b are insufficient)

If false positives persist after 5a+5b are live for 48h, add migration 014:

- `jobs.expiry_fail_count INTEGER NOT NULL DEFAULT 0`
- `gone=True` → increment. Close at 2.
- `gone=False` → reset to 0.
- `gone=None` → no change.

**Why 5b over 5c as primary:** Recency-skip is one line of code, zero schema, would have prevented today's incident. 2-strike is more robust but more code. Ship 5a+5b first, measure, add 5c only if still leaking.

## Step 6 — Tests

`tests/test_expiry.py` additions:

Per source (LinkedIn/Greenhouse/Lever/Ashby):
- The explicit gone signal → `gone=True`
- 403/429/5xx/timeout → `gone=None`
- Healthy live response → `gone=False`

Ashby-specific:
- Title === "Jobs" → gone
- Title === "@Company Name" → live
- Parse error → unknown

Integration:
- Recency-skip: `last_seen < 24h ago` → checker returns early without an HTTP call
- Caller: `gone=True` → close, `gone=None` → skip, `gone=False` → no change

If 5c ships: single "gone" doesn't close (fail_count=1); two-in-a-row closes; "live" between two "gone" resets.

## Step 7 — Observability

Structured log in `run_expiry_checks` on every **close decision** at INFO level: `job_id`, `url`, `source`, HTTP status, decision (close/skip), why.

At ~187 jobs/cycle full-INFO would be noisy. Volume control:
- `close` → INFO
- `skip because live` → DEBUG
- `skip because last_seen<24h` → DEBUG
- `skip because unknown response` → DEBUG

Bounded INFO volume, actionable signal.

## Step 8 — Deploy and monitor

1. Deploy Step 2 (env-var gate).
2. `fly secrets set DISABLE_URL_CHECK=1 --app shortlist-web`.
3. Run Step 3 SQL reopen. Verify inbox counts jump.
4. Ship the Step 5 fix (code + tests green locally first).
5. `fly secrets unset DISABLE_URL_CHECK --app shortlist-web`.
6. Watch `fly logs --app shortlist-web | grep url_check` for 24h.
7. Compare `closed_reason='url_check'` count over the next 48h vs. the 56-in-48h baseline. Target: dramatic reduction on recent/well-known postings. Expect non-zero — genuine expiry is still a thing.
8. After 48h of healthy behavior, decide whether 5c is needed based on actual false-positive rate.

## Risks

- **5a "unknown" handling could leak dead jobs** if a site permanently 403s us. Mitigation: `last_seen_stale` sweep still runs — a job we can't check AND haven't collected in 3+ days closes via that path anyway.
- **5b recency skip means a truly-removed job stays in the inbox for up to 24h after its last successful collection.** Acceptable — `last_seen_stale` picks it up after 3 days, and the UX cost of a handful of dead jobs visible for a day is tiny compared to an inbox that loses 56 real jobs.
- **SQL reopen wipes `closed_at`/`closed_reason` for reopened rows** — no audit trail for the one-time remediation. Tracking "auto-reopened from false positive" isn't worth a schema change for this.
- **`DISABLE_URL_CHECK` env var is a foot-gun if forgotten.** Mitigation: add a startup log line "`url_check` DISABLED via env var" at WARN so it's visible in `fly logs`.

## Out of scope

- Dedup across sources (LinkedIn+Greenhouse duplicates). Separate issue.
- The 3 `closed_reason IS NULL` visible closures (59 total - 56 `url_check`). Investigate post-fix; if count drops to 0, the mystery was likely a race in the same code path.

## Verification checklist before declaring done

- [ ] Live URL test (Step 1) confirmed the hypothesis
- [ ] Env-var gate deployed, url_check disabled in prod
- [ ] SQL reopens ~60 jobs; inbox counts jump back per user
- [ ] 5a: per-source check functions return tri-state gone signal
- [ ] 5b: recency skip returns before HTTP call when last_seen<24h
- [ ] Tests pass: each source's status-code handling + recency-skip integration
- [ ] Fix deployed, env var removed
- [ ] `fly logs` shows new decision log format with bounded volume
- [ ] Next auto-run closes dramatically fewer visible jobs via url_check
- [ ] 48h post-deploy: decide on 5c (2-strike rule)
