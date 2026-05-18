# DECISIONS — Shortlist

Architectural and product decisions with rationale. Most recent first.

Inherits: `~/Code/DECISIONS.md` (T1 — agency-level decisions)

Implemented/closed decisions move to `docs/archive/decisions/` per `~/Code/ARCHIVE_SYSTEM.md`. See `docs/archive/INDEX.md`.

---

## D-SL-019: CSVFirst data is a feature data source + QA oracle, not a recurring collector (2026-05-17)

**Chose:** Ingest CSVFirst's per-company "long-open jobs" stats into a new `company_hiring_stats` table; surface as an **evergreen warning badge** in the UI (jobs at companies where >40% of reqs stay open 6+ months). Also keep `scripts/qa_against_csvfirst.py` as an audit cross-check against pipeline failure modes.

**Over:** (a) building CSVFirst into a recurring `Collector`, (b) using only as internal QA, (c) ignoring entirely.

**Why:** Two trips through framing. First take ("more job coverage") was wrong — LinkedIn already covers ~all of CSVFirst's 200+ companies, marginal new jobs would be ~5-15/run, mostly noise. Reframed as candidate-protection: CSVFirst's core product is identifying jobs/companies that stay open suspiciously long (evergreen funnels, "always-on" pipelines, structural recruiting inefficiency — applicants get ghosted). That signal isn't available anywhere else in our stack and maps directly to a user-visible feature. The QA value (caught 1,610+ false closures, see D-SL-018) is bonus, not the primary use.

**Evidence:** Shipped 2026-05-17 (`f64163f`, `ec68902`, `001d1d8`). `EvergreenBadge` popover on `JobCard` with structured stats + source attribution. Phase A coverage: 50 companies → 4 badge in user 2's inbox. Scaling to full ~200-company dataset blocked on API access request.

**Revisit when:** (a) CSVFirst full API access lands and we evaluate paid tier; (b) user feedback shows the badge is noise (false positives at companies that DO respond); (c) we find a second source for the same signal (could deprecate dependence on one vendor).

---

## D-SL-018: `last_seen_stale` Pass 1 requires an active observer before closing (2026-05-17)

**Chose:** Tri-state guard on `pgdb.mark_stale_jobs` Pass 1 — close greenhouse/lever/ashby jobs only when the company has an active `career_page_sources` row that fetched non-empty within 7 days. No observer → no closure, regardless of `last_seen` age.

**Over:** Keeping the unconditional 3-day cutoff; or kill-switching the sweep entirely; or raising the cutoff to 30+ days.

**Why:** CSVFirst QA on 2026-05-17 surfaced 1,610+ jobs incorrectly closed across 7 companies (Anthropic, Anduril, Figma, Workato, Airbnb, Five9, Samsara). All were batch-seeded once via earlier collection paths but never added to `career_page_sources`, so `last_seen` froze at the seed date and the 3-day cutoff fired against rows nothing was refreshing. Same structural bug class as the 2026-04-16 expiry-checker incident (SL-019 in `CONSTRAINTS.md`): treating absence of signal as evidence of closure. Kill-switch would also block legitimate closures from observed-but-empty sources; cutoff extension only delays the same failure. Tri-state is the correct semantics.

**Evidence:** Commit `341ed95`. 3 new unit tests in `tests/test_job_expiry.py` covering no-observer, stale-observer, and observer-returned-zero cases. CLAUDE.md anti-pattern entry added.

**Revisit when:** A new failure mode where a CPS observer is "fresh-but-wrong" (e.g., greenhouse returns a partial page due to a vendor bug, sweep then closes legitimately-missing URLs). At that point we'd need per-URL evidence, not just per-company observer presence.

---

## D-SL-017: Whether expiry checking should run continuously at all — deferred (2026-04-26)

**Chose:** Keep continuous expiry checks running, but at sharply reduced rate (~60 HEAD/hr). Defer the bigger question.

**Over:** Switching to nightly batch, or removing expiry checking entirely.

**Why:** The signal value of "Closed" badges is dubious for the current usage pattern — most users see closed badges on jobs they've already triaged, so the badge rarely changes a decision. But killing it removes a real (if low-value) freshness signal, and we don't have user-traffic data to confirm nobody relies on it. Cheaper to throttle now and revisit with data than to make the call cold.

**Evidence:** D-SL-016 (the throttle) ships the immediate proxy-cost fix. CLAUDE.md "Expiry checker is a continuous proxy-traffic source" pattern entry.

**Revisit when:** (a) Decodo bill notably drops but still feels excessive, (b) PostHog data shows users don't engage with closed-state UI, or (c) we add a second always-on background process and need to budget proxy spend across both.

---

## D-SL-016: Expiry checker throttled — `limit=5`, `TICK_INTERVAL=300s` (2026-04-26)

**Chose:** `expiry._run_batch(limit=5)` (was 20) and `scheduler.TICK_INTERVAL=300` (was 60). Combined effect: ~1200 HEAD/hr → ~60 HEAD/hr through Decodo. Each open job still re-checked every ~10–50h on average.

**Over:**
- Status quo (`limit=20`, `60s` tick) — burning Decodo bandwidth 24/7 for closure signals of marginal value.
- Mass-closing stale rows (`last_seen >30d`) — only 61 rows matched; doesn't reduce sustained rate because the driver is the 3000 rows at >24h that aren't getting re-collected.
- Killing the expiry loop entirely — see D-SL-017.

**Why:** Closure-signal freshness from <60s to <5min latency is invisible to the user (jobs don't close in real-time anyway). Each row re-checked every ~10h is still well within useful for "did this Greenhouse posting come down?" Tradeoff is 20× lower proxy spend.

**Evidence:** Commits 9056e29 (batch size) + 18878a9 (tick interval). Pre-throttle: log spot-check showed ~50 LinkedIn HEAD/min sustained.

**Revisit when:**
- A user-facing feature starts depending on near-real-time job-closure signals
- We add `last_check_at` separately from `last_seen` so the long tail can self-throttle (then we can raise these defaults safely)
- D-SL-017 resolves to "kill expiry loop" or "move to nightly batch"

---

## D-SL-012: CLI frozen on SQLite (no active development) (2026-04)

**Chose:** Freeze CLI development. All active work goes to the web app.

**Over:** Maintaining CLI and web in parallel.

**Why:** CLI uses SQLite, web uses PostgreSQL. Keeping both in sync doubles the surface area with no user value. Web is the primary development path.

**Evidence:** CLAUDE.md explicitly marks CLI as "frozen on SQLite — don't maintain alongside web."

**Revisit when:** A specific CLI use case can't be addressed by the web API.
