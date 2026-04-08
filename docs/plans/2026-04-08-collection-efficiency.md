# Collection Efficiency

**Goal:** Stop re-processing jobs we've already seen. Two targeted fixes — time filter for LinkedIn, URL pre-filter for NextPlay.

**Approach:**
- **LinkedIn**: Change `time_filter` from `r604800` (1 week) to `r86400` (24h). With a 12h run interval, a 24h window catches every new job with 2x safety margin. Exception: first run for a new user uses `r604800` to populate their initial inbox.
- **NextPlay**: Before upserting collected jobs, batch-check which URLs already exist in `jobs`. Known jobs get a lightweight `last_seen` bump. Unknown jobs go through the full upsert → filter → score path. Curated sources keep their own code path (separate callback, not `_process_collected`) — can be a follow-up.

**What this does NOT change:**
- `last_seen` is still updated for known jobs (expiry detection depends on it).
- NextPlay's 24h ATS discovery cache — already working well, no change.
- HN — no proxy, fast, low volume. Not worth changing.

**Files affected:**
- `shortlist/pipeline.py` (modify — LinkedIn time filter, `_split_known_new` helper, wire-up in `_process_collected`)
- `shortlist/pgdb.py` (modify — `get_existing_urls`, `bulk_update_last_seen`)
- `tests/test_pgdb.py` (modify — tests for new pgdb functions)
- `tests/test_pipeline_efficiency.py` (create — LinkedIn filter test + `_split_known_new` tests)

---

## Task 1: LinkedIn — `r604800` → `r86400` with first-run fallback

**Files:** `shortlist/pipeline.py`
**Purpose:** Only fetch jobs posted in the last 24h on recurring runs. First run for a new user uses a week window to populate their initial inbox.

### Steps

1. Write failing tests in `tests/test_pipeline_efficiency.py`:

```python
"""Tests for collection efficiency improvements."""
import pytest
from unittest.mock import patch, MagicMock


def _make_config():
    from shortlist.config import Config, Track, Filters, LocationFilter, SalaryFilter
    return Config(
        tracks={"vp": Track(title="VP Engineering", search_queries=["VP Engineering"])},
        filters=Filters(location=LocationFilter(remote=True), salary=SalaryFilter()),
    )


def _capture_linkedin_time_filter(config, li_time_filter):
    """Call _get_collectors with a capturing subclass, return list of time_filter values used."""
    import shortlist.pipeline as pm
    import shortlist.collectors.linkedin as li_mod

    created = []

    class CapturingLinkedIn(li_mod.LinkedInCollector):
        def __init__(self, *args, **kwargs):
            created.append(kwargs.get("time_filter"))
            # Don't call super — avoids real network setup

    with patch.object(li_mod, "LinkedInCollector", CapturingLinkedIn):
        pm._get_collectors(config=config, db=None, pg_db_url=None,
                           li_time_filter=li_time_filter)
    return created


def test_linkedin_uses_24h_filter_on_recurring_runs():
    """Recurring runs use r86400 (24h) — no re-fetching jobs from the past week."""
    config = _make_config()
    created = _capture_linkedin_time_filter(config, li_time_filter="r86400")
    assert created, "LinkedInCollector was never instantiated"
    assert all(t == "r86400" for t in created), f"Expected r86400, got {created}"


def test_linkedin_uses_week_filter_on_first_run():
    """First run uses r604800 (1 week) to populate the user's initial inbox."""
    config = _make_config()
    created = _capture_linkedin_time_filter(config, li_time_filter="r604800")
    assert created, "LinkedInCollector was never instantiated"
    assert all(t == "r604800" for t in created), f"Expected r604800, got {created}"
```

2. Verify fail:
```bash
cd /Users/adam1/Code/shortlist
python3 -m pytest tests/test_pipeline_efficiency.py -q
```
Expected: FAIL — `_get_collectors` doesn't accept `li_time_filter` yet.

3. Implement in `shortlist/pipeline.py`:

**a.** Add `li_time_filter` param to `_get_collectors`:
```python
def _get_collectors(config: Config | None = None, db: sqlite3.Connection | None = None,
                    pg_db_url: str | None = None, li_time_filter: str = "r86400") -> dict:
```
Replace both `time_filter="r604800"` occurrences inside with `time_filter=li_time_filter`.

**b.** In `run_pipeline_pg`, determine the filter before calling `_get_collectors`:
```python
# Use 24h filter for recurring runs; week filter for first run (populates initial inbox).
with conn.cursor() as cur:
    cur.execute(
        "SELECT COUNT(*) as n FROM jobs WHERE user_id = %s AND status IN ('scored', 'low_score')",
        (user_id,),
    )
    has_prior_jobs = cur.fetchone()["n"] > 0
li_time_filter = "r86400" if has_prior_jobs else "r604800"

collectors = _get_collectors(config=config, db=None, pg_db_url=db_url,
                             li_time_filter=li_time_filter)
```

4. Verify pass:
```bash
python3 -m pytest tests/test_pipeline_efficiency.py -q
```

5. Full suite:
```bash
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass.

---

## Task 2: pgdb helpers — `get_existing_urls` + `bulk_update_last_seen`

**File:** `shortlist/pgdb.py`
**Purpose:**
- `get_existing_urls(conn, user_id, urls)` — batch check which URLs already exist for this user.
- `bulk_update_last_seen(conn, user_id, urls)` — lightweight timestamp refresh without a status or source change.

### Steps

1. Write failing tests in `tests/test_pgdb.py`:

```python
def test_get_existing_urls_returns_known_urls(pg_conn):
    """get_existing_urls returns only URLs that exist in jobs table."""
    from shortlist.collectors.base import RawJob
    from shortlist.pgdb import upsert_job, get_existing_urls

    job = RawJob(title="VP Eng", company="Acme", url="https://acme.com/job/1",
                 description="desc", source="greenhouse", location="Remote")
    upsert_job(pg_conn, user_id=1, job=job)
    pg_conn.commit()

    result = get_existing_urls(pg_conn, user_id=1,
                               urls=["https://acme.com/job/1", "https://acme.com/job/2"])
    assert "https://acme.com/job/1" in result
    assert "https://acme.com/job/2" not in result


def test_get_existing_urls_empty_input(pg_conn):
    """get_existing_urls returns empty set for empty input."""
    from shortlist.pgdb import get_existing_urls
    assert get_existing_urls(pg_conn, user_id=1, urls=[]) == set()


def test_bulk_update_last_seen_advances_timestamp(pg_conn):
    """bulk_update_last_seen updates last_seen without changing status or first_seen."""
    import time
    from datetime import datetime, timezone
    from shortlist.collectors.base import RawJob
    from shortlist.pgdb import upsert_job, bulk_update_last_seen

    job = RawJob(title="Dir Eng", company="Corp", url="https://corp.com/job/1",
                 description="desc", source="lever", location="Remote")
    upsert_job(pg_conn, user_id=1, job=job)
    pg_conn.commit()

    time.sleep(0.05)
    later = datetime.now(timezone.utc)
    bulk_update_last_seen(pg_conn, user_id=1, urls=["https://corp.com/job/1"],
                          now=later)
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT first_seen, last_seen, status FROM jobs WHERE url = %s",
            ("https://corp.com/job/1",),
        )
        row = cur.fetchone()
    assert row["last_seen"] > row["first_seen"], "last_seen should advance"
    assert row["status"] == "new", "status must not change"


def test_bulk_update_last_seen_empty_input(pg_conn):
    """bulk_update_last_seen is a no-op for empty input."""
    from shortlist.pgdb import bulk_update_last_seen
    from datetime import datetime, timezone
    # Should not raise
    bulk_update_last_seen(pg_conn, user_id=1, urls=[], now=datetime.now(timezone.utc))
```

2. Verify fail:
```bash
python3 -m pytest tests/test_pgdb.py::test_get_existing_urls_returns_known_urls \
  tests/test_pgdb.py::test_get_existing_urls_empty_input \
  tests/test_pgdb.py::test_bulk_update_last_seen_advances_timestamp \
  tests/test_pgdb.py::test_bulk_update_last_seen_empty_input -q
```
Expected: FAIL — functions don't exist yet.

3. Implement in `shortlist/pgdb.py` — add after `upsert_job`:

```python
def get_existing_urls(conn, user_id: int, urls: list[str]) -> set[str]:
    """Return the subset of urls already in the jobs table for this user."""
    if not urls:
        return set()
    placeholders = ", ".join(["%s"] * len(urls))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT url FROM jobs WHERE user_id = %s AND url IN ({placeholders})",
            (user_id, *urls),
        )
        return {row["url"] for row in cur.fetchall()}


def bulk_update_last_seen(conn, user_id: int, urls: list[str],
                          now: "datetime | None" = None) -> None:
    """Refresh last_seen for already-known jobs without changing status or source list.

    Accepts an explicit `now` so callers control the timestamp (testable, consistent
    within a single pipeline run). Falls back to current UTC time if omitted.
    """
    if not urls:
        return
    if now is None:
        now = datetime.now(timezone.utc)
    placeholders = ", ".join(["%s"] * len(urls))
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE jobs SET last_seen = %s "
            f"WHERE user_id = %s AND url IN ({placeholders})",
            (now, user_id, *urls),
        )
```

4. Verify pass:
```bash
python3 -m pytest tests/test_pgdb.py::test_get_existing_urls_returns_known_urls \
  tests/test_pgdb.py::test_get_existing_urls_empty_input \
  tests/test_pgdb.py::test_bulk_update_last_seen_advances_timestamp \
  tests/test_pgdb.py::test_bulk_update_last_seen_empty_input -q
```

5. Full suite:
```bash
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass.

---

## Task 3: Extract `_split_known_new` + wire into `_process_collected`

**File:** `shortlist/pipeline.py`
**Purpose:** Extract the URL pre-filter logic into a named, testable module-level function. Wire it into `_process_collected` for the `nextplay` source only.

Curated sources use a different code path (`_on_curated_fetched` callback with direct `pgdb.upsert_job` calls — not `_process_collected`). Curated pre-filter is a follow-up.

### Steps

1. Write failing tests in `tests/test_pipeline_efficiency.py`:

```python
def test_split_known_new_separates_by_url():
    """Known URLs are split from new jobs for nextplay source."""
    import shortlist.pipeline as pm
    import shortlist.pgdb as pgdb_mod
    from shortlist.collectors.base import RawJob
    from unittest.mock import MagicMock, patch

    job_known = RawJob(title="VP Eng", company="Acme", url="https://acme.com/1",
                       description="d1", source="greenhouse", location="Remote")
    job_new = RawJob(title="Dir Eng", company="Corp", url="https://corp.com/1",
                     description="d2", source="greenhouse", location="Remote")

    conn = MagicMock()
    with patch.object(pgdb_mod, "get_existing_urls",
                      return_value={"https://acme.com/1"}):
        known_urls, new_jobs = pm._split_known_new(
            conn, user_id=1, name="nextplay", jobs=[job_known, job_new]
        )

    assert known_urls == ["https://acme.com/1"]
    assert len(new_jobs) == 1
    assert new_jobs[0].url == "https://corp.com/1"


def test_split_known_new_linkedin_bypasses_check():
    """LinkedIn source skips the DB check — all jobs returned as new."""
    import shortlist.pipeline as pm
    import shortlist.pgdb as pgdb_mod
    from shortlist.collectors.base import RawJob
    from unittest.mock import MagicMock, patch

    job = RawJob(title="VP Eng", company="Acme", url="https://linkedin.com/1",
                 description="d1", source="linkedin", location="Remote")
    conn = MagicMock()
    with patch.object(pgdb_mod, "get_existing_urls") as mock_get:
        known_urls, new_jobs = pm._split_known_new(
            conn, user_id=1, name="linkedin", jobs=[job]
        )

    mock_get.assert_not_called()
    assert known_urls == []
    assert len(new_jobs) == 1


def test_split_known_new_null_url_treated_as_new():
    """Jobs with no URL bypass the check and are treated as new."""
    import shortlist.pipeline as pm
    import shortlist.pgdb as pgdb_mod
    from shortlist.collectors.base import RawJob
    from unittest.mock import MagicMock, patch

    job = RawJob(title="VP Eng", company="Acme", url=None,
                 description="d1", source="greenhouse", location="Remote")
    conn = MagicMock()
    with patch.object(pgdb_mod, "get_existing_urls", return_value=set()):
        known_urls, new_jobs = pm._split_known_new(
            conn, user_id=1, name="nextplay", jobs=[job]
        )

    assert known_urls == []
    assert len(new_jobs) == 1
```

2. Verify fail:
```bash
python3 -m pytest tests/test_pipeline_efficiency.py::test_split_known_new_separates_by_url \
  tests/test_pipeline_efficiency.py::test_split_known_new_linkedin_bypasses_check \
  tests/test_pipeline_efficiency.py::test_split_known_new_null_url_treated_as_new -q
```
Expected: FAIL — `_split_known_new` doesn't exist yet.

3. Add `_split_known_new` as a module-level function in `shortlist/pipeline.py` (above `run_pipeline_pg`):

```python
def _split_known_new(conn, user_id: int, name: str, jobs: list) -> tuple[list, list]:
    """Split a job list into (known_urls, new_jobs) for sources that benefit from pre-filtering.

    Sources in _PREFILTER_SOURCES get a batch URL lookup before upserting.
    Other sources (linkedin uses f_TPR, hn is low volume) bypass the check.

    Returns:
        known_urls: list of URL strings already in the DB (need last_seen bump only)
        new_jobs:   list of RawJob objects with URLs not yet in DB (full pipeline)
    """
    from shortlist import pgdb
    _PREFILTER_SOURCES = {"nextplay"}
    if name not in _PREFILTER_SOURCES:
        return [], list(jobs)

    checkable = [j.url for j in jobs if j.url]
    existing = pgdb.get_existing_urls(conn, user_id, checkable)
    known_urls = [j.url for j in jobs if j.url and j.url in existing]
    new_jobs = [j for j in jobs if not j.url or j.url not in existing]
    return known_urls, new_jobs
```

4. Wire into `_process_collected` in `run_pipeline_pg`. Find:
```python
        for job in jobs_list:
            pgdb.upsert_job(conn, user_id, job)
        jobs_collected += len(jobs_list)
```
Replace with:
```python
        known_urls, new_jobs = _split_known_new(conn, user_id, name, jobs_list)
        if known_urls:
            pgdb.bulk_update_last_seen(conn, user_id, known_urls)
        for job in new_jobs:
            pgdb.upsert_job(conn, user_id, job)
        jobs_collected += len(new_jobs)
        if known_urls:
            logger.info(
                f"{name}: {len(new_jobs)} new, {len(known_urls)} already known "
                f"(last_seen updated)"
            )
```

5. Verify:
```bash
python3 -m pytest tests/test_pipeline_efficiency.py -q
python3 -m pytest tests/ -q --ignore=tests/api
```
Expected: all pass.

---

## Task 4: Deploy + verify

```bash
cd /Users/adam1/Code/shortlist
fly deploy --app shortlist-web
```

After next pipeline run, check for efficiency signals in logs:
```bash
fly logs --app shortlist-web --no-tail 2>/dev/null | grep -E "already known|new, [0-9]+ already" | tail -20
```

Expected:
```
nextplay: 2 new, 51 already known (last_seen updated)
```

Also check LinkedIn volume dropped — should see far fewer jobs_collected from LinkedIn on recurring runs vs the first run after deploy.

---

## Expected impact

| Source | Before | After |
|--------|--------|-------|
| LinkedIn | Fetches 7 days of jobs each run; most already in DB | Recurring: 24h only. First run: 1 week to populate inbox |
| NextPlay | Upserts all cached jobs every run; filter/score runs but finds nothing new | Batch URL check first; known jobs get a timestamp bump only |
| HN | Unchanged | Unchanged |
| Curated | Unchanged (follow-up) | Unchanged |
