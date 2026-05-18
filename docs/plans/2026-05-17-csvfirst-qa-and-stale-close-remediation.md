# CSVFirst QA + `last_seen_stale` false-closure remediation

**Created:** 2026-05-17
**Driver:** CSVFirst QA run surfaced ~1,610+ live jobs across 7 companies that were closed by the `last_seen_stale` sweep with no real signal. Anduril/Anthropic/Figma/Workato pilot proved the fix path (4/5 canary refreshed). This plan finishes the remediation, prevents recurrence, and turns the QA discovery loop into a recurring guardrail.

---

## Problem (one paragraph for context)

`pgdb.mark_stale_jobs` Pass 1 closes any greenhouse/lever/ashby job whose `last_seen` is older than **3 days before the run start**. The assumption baked in: "if we haven't seen it in 3 days, the listing is gone." That assumption fails silently when *we never had an observer for that company*. Jobs batch-seeded once (Anthropic 446 on 2026-03-12; Samsara 349 on 2026-03-12; Airbnb 239 on 2026-04-07; etc.) had no `career_page_sources` entry, so nothing refreshed `last_seen` after the seed → the 3-day cutoff fired → every job from those companies died on schedule. CSVFirst confirms most are still live. This is structurally identical to the 2026-04-16 expiry-checker incident (treating absence of signal as evidence of closure), just at a different layer.

## Open decisions (need answers before implementation starts)

| # | Decision | Default I'd take | Why it matters |
|---|---|---|---|
| D1 | **Bulk-reopen scope** — only the 7 affected companies, or all `last_seen_stale` closures system-wide? | Only the 7, until Tier 2 (sweep fix) is in | System-wide is bigger blast radius; some closures may be legitimate. Until the sweep is tri-state, system-wide reopen is theater. |
| D2 | **Per-user or all users?** Reopens are stored per-user-row. | All users | The closure was a global bug; remediation should match. |
| D3 | **Tri-state sweep cutoff** — keep 3 days, or extend? | Keep 3 days but only fire when an active observer exists | The 3-day cutoff is fine if we trust the observer; the bug was firing without one. |
| D4 | **QA cadence** | Weekly, manual to start | Recurring automation has its own risks (orphan processes, cost). Start manual, scale once it earns trust. |
| D5 | **Full CSVFirst dataset access** | Request the 35k full snapshot for one-time seed of `career_page_sources` | Closes the long tail of "company we never seeded." Doesn't need recurring API access. |
| D6 | **Slug discovery method for proxied companies** (Airbnb, Five9, Samsara) | Probe `boards.greenhouse.io/<lowercase-name>` with a HEAD request; fall back to manual lookup if 404 | Lowest-traffic discovery path; ~3 probes total. |

---

## Tier 1 — Stop the bleeding (1-2 days, mostly ops)

Goal: refresh `last_seen` on every job that's actually still alive, and reopen the false closes.

### Task 1.1: Discover slugs for Airbnb, Five9, Samsara

**File:** `scripts/discover_greenhouse_slug.py` (create)
**Purpose:** Given a company name, probe canonical greenhouse boards and confirm the slug.

#### Steps

1. Write a one-shot script that takes `--names "Airbnb,Five9,Samsara"`, lowercases each, hits `https://boards.greenhouse.io/<slug>` with a `HEAD` request via `shortlist.http`, and prints the slug + first-fetched job count.
2. Fall back: if 404, try removing punctuation/spaces (`anduril industries` → `andurilindustries`). If still 404, print the company name with `<MANUAL>` and continue.
3. Verify by running:
   ```bash
   uv run python scripts/discover_greenhouse_slug.py --names "Airbnb,Five9,Samsara"
   ```
   Expected output: 3 lines with confirmed slugs.

**Risk:** This sends ≤6 HEAD requests, well below any rate limit. No prod data writes.

### Task 1.2: Seed the 3 proxied companies + any other companies from the affected list

**File:** `data/career_pages/csvfirst_recovery_2026-05-17.json` (create — manual edit using slugs from 1.1)
**Then run:** `scripts/seed_career_pages.py csvfirst_recovery_2026-05-17`

Use the existing `scripts/extract_csvfirst_career_pages.py` if the slugs are now known, or hand-edit the JSON.

Verify: 3 new rows in `career_page_sources`, `status='active'`. (Same query as pilot verify.)

### Task 1.3: Pilot verify for each newly-seeded company

For each of Airbnb / Five9 / Samsara:
1. Pick 5 canary IDs (same method as the Anthropic pilot — `closed_reason='last_seen_stale'` ∩ CSVFirst-confirmed-alive).
2. Reopen them via SQL.
3. Trigger a pipeline run for user 2.
4. After the run, check that ≥4/5 canaries got `last_seen` refreshed.

Stop and escalate if any company falls below 4/5 — could indicate a slug/fetch bug specific to that company.

### Task 1.4: Bulk reopen false closes

**File:** `scripts/bulk_reopen_false_closes.py` (create)
**Purpose:** For each company whose `career_page_sources` row was checked successfully in the last N runs, reopen rows that were closed with `closed_reason='last_seen_stale'` AND whose URL appears in the most recent fetch result for that company.

**Critical predicates** (don't reopen blindly):
- `closed_reason = 'last_seen_stale'` (not user/expiry/age_expired)
- The job's URL must currently exist in our DB on another user with `is_closed=false` and `last_seen > NOW() - INTERVAL '1 day'` (i.e., the URL was just successfully refreshed for someone). This is the strongest in-DB signal that the URL is alive.

#### Steps

1. Write the script with `--dry-run` default; print count + sample by company; require explicit `--apply` to write.
2. Run dry-run; review output against expectations (~600 Anthropic, ~120 Anduril, ~155 Figma, ~110 Workato + whatever the 3 newly-seeded companies surface).
3. Apply with explicit go-ahead.
4. Verify: re-run `qa_against_csvfirst.py`; check #1 (false closes) should drop dramatically.

**Rollback:** This is a forward-only data fix, but reversible — `closed_reason='last_seen_stale'` rows reopened by this script can be re-closed by running another sweep cycle if the fix turns out wrong.

---

## Tier 2 — Prevent recurrence (~1 day; code change)

Goal: make Pass 1 of `mark_stale_jobs` tri-state. Only close greenhouse/lever/ashby jobs whose company has an active observer that *was attempted* in a recent run but didn't surface this URL. No observer → no closure.

### Task 2.1: Define "active observer" predicate

Decision points encoded in the SQL:
- A company has an active observer if `career_page_sources` contains a row for its `slug` (or `company_name`) with `status='active'` AND `last_checked_at > NOW() - INTERVAL '7 days'`.
- For jobs that pre-date `career_page_sources` (sources_seen=["greenhouse"] but no matching CPS row), Pass 1 must NOT fire. They stay open until either (a) the company gets seeded into CPS, or (b) the expiry checker actively HEAD-confirms they're gone, or (c) the user closes them.

### Task 2.2: TDD the tri-state Pass 1

**File:** `tests/test_pgdb_stale_close.py` (create)
**Purpose:** Cover the three states.

#### Steps

1. Write failing tests:
   ```python
   def test_pass1_closes_jobs_when_company_has_active_observer(...):
       """Seed CPS with anthropic (last_checked recent), insert job last_seen 10d ago.
          Run mark_stale_jobs. Expect job is_closed=true."""

   def test_pass1_skips_jobs_when_no_active_observer(...):
       """Insert greenhouse job last_seen 10d ago, NO CPS entry for its company.
          Run mark_stale_jobs. Expect job stays open (is_closed=false)."""

   def test_pass1_skips_jobs_when_observer_stale(...):
       """CPS entry exists but last_checked > 7d ago. Job stays open."""
   ```
2. Run: `pytest tests/test_pgdb_stale_close.py -q` → expect 3 failures.
3. Modify `shortlist/pgdb.py:mark_stale_jobs` Pass 1 to add a join on `career_page_sources`:
   ```sql
   UPDATE jobs SET is_closed = true, closed_at = %s, closed_reason = 'last_seen_stale'
   FROM career_page_sources cps
   WHERE last_seen < %s
     AND (sources_seen::text LIKE %s OR sources_seen::text LIKE %s OR sources_seen::text LIKE %s)
     AND cps.status = 'active'
     AND cps.last_checked_at > NOW() - INTERVAL '7 days'
     AND LOWER(jobs.company) = LOWER(cps.company_name)  -- or match on slug if more reliable
     AND user_id = %s ...
   ```
4. Run tests again → expect green.
5. Run full suite: `pytest tests/ -q` → no regressions.
6. Update `CLAUDE.md` "Common Mistakes to Avoid" with the lesson:
   > `❌ Closing greenhouse/lever/ashby jobs based on `last_seen` alone — requires an active observer in `career_page_sources` that fetched recently. No observer = no signal to disprove the close. Burned 2026-05-17: 1,610+ false closes across 7 companies seeded but never re-fetched.`
7. Commit: `fix(stale-close): require active observer before closing ATS jobs`.

### Task 2.3: Add closure-reason logging

**File:** `shortlist/pgdb.py:mark_stale_jobs`
**Purpose:** When a row is closed, log which pass fired and the predicate values that triggered it. Goes to stdout so it shows in `fly logs`.

Modify the function to log per-pass counts at INFO. Doesn't need a test (logging-only).

---

## Tier 3 — Make QA recurring (~1 day)

Goal: turn the one-off `scripts/qa_against_csvfirst.py` into a weekly heartbeat that alerts when drift exceeds a threshold.

### Task 3.1: Add a `--alert-threshold` mode to the QA script

**File:** `scripts/qa_against_csvfirst.py` (modify)
**Purpose:** Exit non-zero if check #1 (false closes after dedupe) exceeds N, so a cron/CI wrapper can alert.

Steps:
1. Add CLI arg `--alert-on-false-closes N` (default unset → no exit code).
2. If hit count > N, exit 2 and print a one-line summary to stderr.
3. Test by running against current DB with `--alert-on-false-closes 50` — should not alert post-remediation.

### Task 3.2: Decide cadence + invocation point

Two options:
- **A.** Local cron on your laptop, runs `fly proxy` + the script + emails/Slacks output. Simple, no prod cost.
- **B.** Add a tick handler in `shortlist/scheduler.py` that runs the QA weekly and writes the markdown report into Tigris. Requires the QA script to be runnable in-container (so check `shortlist/` imports cleanly).

**Recommended:** A first. B once the script earns weekly trust (3 runs without surprises).

### Task 3.3: Document the workflow in CLAUDE.md

Add a section under "Common Patterns" or near the expiry checker patterns:

```
**External-source QA (CSVFirst):** Weekly drift check against an independent observer of
~35,000 active jobs across 200+ companies. Run via:
    DATABASE_URL=... uv run python scripts/qa_against_csvfirst.py --csv <latest> --oldest <latest>
        --out docs/qa/csvfirst_<date>.md --alert-on-false-closes 50
Reports go to docs/qa/. Alerts fire when false-close count exceeds threshold.
```

---

## Tier 4 — Use CSVFirst data more broadly (later; conditional on API access)

Only relevant once you've requested + received API access to the full 35k snapshot.

### Task 4.1: Bulk-seed missing companies from CSVFirst

When the full snapshot lands, run `scripts/extract_csvfirst_career_pages.py csvfirst_bulk_<date> --csv <full> --all` to extract every canonical greenhouse company. Diff against existing `career_page_sources`; seed the gap. Pilot 5 canaries from a randomly-chosen company per batch of 20 to confirm refresh works.

### Task 4.2: Replace one-off CSV reads with HTTP fetches

Update `qa_against_csvfirst.py` to optionally read from the CSVFirst API endpoint. Cache locally per-day. Don't make this a recurring collector — QA only.

---

## Risks + edge cases

| Risk | Mitigation |
|---|---|
| Tri-state sweep change leaks: some companies have `sources_seen=["greenhouse"]` but no CPS entry → those jobs stay open *forever* even after the actual job closes | Acceptable for the window before Tier 4 ships. The expiry checker (HEAD-based) will eventually catch genuinely-closed URLs. Pre-2026-05-17 batch-seeded rows are the bulk of these — once we seed those companies into CPS, the problem dissolves. |
| Bulk reopen reopens a job that's actually closed (CSVFirst snapshot lag) | The "URL appears live for another user with recent last_seen" predicate guards against this. CSVFirst is up to ~24h stale; cross-user freshness is up to ~1h. |
| Slug-discovery probes flagged as bot traffic by Greenhouse | 3-6 HEAD requests total; far below any reasonable threshold. Use `shortlist.http` (rate-limited). |
| Pilot canary verify fails for one of Airbnb/Five9/Samsara | Investigate per-company. Could mean slug is wrong, ATS migration happened, or careers page changed. Don't proceed with bulk reopen for that company. |
| Tri-state SQL join performance regression | Pass 1 already scans `jobs` with several LIKE predicates. Adding a JOIN on `career_page_sources` (22 rows today) is cheap. Verify with EXPLAIN on a sample query before/after. |
| Logging-only Task 2.3 adds noise | INFO level only, structured per-pass. Easy to filter in `fly logs`. |

---

## Verification gates

Each tier has explicit gates:

- **Tier 1 done when:**
  - All 7 affected companies have CPS entries (`status='active'`)
  - Each company's pilot canary shows ≥4/5 refreshed
  - Bulk reopen executed; QA re-run shows check #1 dropped from current (~57 dedupe) to <10
- **Tier 2 done when:**
  - 3 unit tests covering tri-state behavior pass
  - Full suite (`pytest tests/ -q`) green, no regressions
  - One pipeline run on prod shows `closed_count` < 50 (compare to current ~442)
  - CLAUDE.md updated
- **Tier 3 done when:**
  - QA script supports `--alert-on-false-closes`
  - Weekly cron on local machine running for 3 weeks with reports landing in `docs/qa/`
- **Tier 4 done when:**
  - CSVFirst API access granted + integrated
  - Full-snapshot seed run completed, with sampled-canary verification per batch

---

## Sequencing

Tier 1 and Tier 2 can run in parallel — they touch different files. Tier 1 unblocks the user immediately (jobs come back). Tier 2 prevents recurrence. Tier 3 is "after the dust settles." Tier 4 waits on external dependency.

Recommended order:
1. **Day 1:** Tier 1 — slug discovery, seed, pilot verify (3 companies), bulk reopen
2. **Day 1-2 (parallel):** Tier 2 — TDD tri-state + ship
3. **Day 3+:** Tier 3 — recurring QA
4. **Whenever:** Tier 4 — when API access lands
