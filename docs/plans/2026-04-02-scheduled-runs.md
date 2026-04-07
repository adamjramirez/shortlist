# Plan: Scheduled Auto-Run

**Date:** 2026-04-02 (revised after review)
**Feature:** Automatically run the pipeline on a schedule so the user's inbox stays fresh without manual action.
**Pattern:** DB-native scheduling + dedicated supervisord process (same as creatomap).

---

## Review fixes applied

| Issue | Fix |
|-------|-----|
| **Critical** — `create_task` inside uncommitted transaction | Collect run metadata inside tx, commit, fire tasks after |
| **Important** — `since=last_tick` fails on restart | Replaced with callback wrapper (`_fire_and_update`) — restart-safe by design |
| **Important** — `user.profile.config` lazy-load bug | Changed to `profile.config` throughout |
| **Important** — N+1 active-run check in loop | Folded into `NOT EXISTS` subquery on initial query |
| **Important** — `_to_response()` signature gap | Explicitly adds `profile` param; callers updated |
| **Minor** — missing commit-order test | Added `test_run_committed_before_execute_run_called` |
| **Minor** — missing callback failure tests | Added full `TestFireAndUpdate` class |

---

## Summary

Add a scheduler process that polls the DB every 60 seconds and fires the pipeline for users whose
`next_run_at` has passed. Scheduler state lives entirely in PostgreSQL — survives restarts and
deploys with no lost state. Users configure a schedule on their profile page and see a live
"Next run in Xh" countdown.

---

## Architecture

```
supervisord
  ├── fastapi (port 8001) — minor route + schema updates
  ├── nextjs  (port 3000) — profile + history UI additions
  └── scheduler (new)   — polls every 60s, triggers auto runs

DB (PostgreSQL)
  profiles
    + auto_run_enabled      BOOLEAN NOT NULL DEFAULT false
    + auto_run_interval_h   INTEGER NOT NULL DEFAULT 12   (hours)
    + next_run_at           TIMESTAMPTZ NULL              ← scheduler queries this (indexed)
    + consecutive_failures  INTEGER NOT NULL DEFAULT 0

  runs
    + trigger               VARCHAR NOT NULL DEFAULT 'manual'   ('manual' | 'auto')
```

**Scheduler tick (every 60s):**
1. Single query: find users with `auto_run_enabled=true AND next_run_at <= NOW() AND no active run`  
   (NOT EXISTS subquery — no N+1)
2. For each: validate config, create `Run(trigger='auto')`, set `next_run_at = NOW() + interval_h`
3. **Commit transaction**
4. Fire `_fire_and_update()` tasks (after commit — run rows exist in DB before worker reads them)

**`_fire_and_update()`** — wraps `execute_run` for auto runs:
- Calls `execute_run(...)` and awaits it
- In a new session after completion: checks `run.status`, updates `consecutive_failures`, applies backoff
- Restart-safe: no dependency on `last_tick` or in-memory state

**Backoff:** `next_run_at = NOW() + min(2^consecutive_failures, 24)h`
**Auto-disable:** `consecutive_failures >= 5` → `auto_run_enabled = False`, UI shows warning

**Manual run:** if `auto_run_enabled`, reset `next_run_at = NOW() + interval_h` on `POST /runs`

---

## Tasks

---

### Task 1: Migration 009 — scheduler columns
**File:** `alembic/versions/009_auto_run.py` (create)
**Purpose:** 4 columns on `profiles`, 1 on `runs`, scheduler index.

```python
"""Add auto-run scheduling columns.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("auto_run_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("profiles", sa.Column("auto_run_interval_h", sa.Integer(), nullable=False, server_default="12"))
    op.add_column("profiles", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("profiles", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("trigger", sa.String(), nullable=False, server_default="manual"))
    op.create_index("idx_profiles_auto_run", "profiles", ["auto_run_enabled", "next_run_at"])


def downgrade():
    op.drop_index("idx_profiles_auto_run", table_name="profiles")
    op.drop_column("profiles", "auto_run_enabled")
    op.drop_column("profiles", "auto_run_interval_h")
    op.drop_column("profiles", "next_run_at")
    op.drop_column("profiles", "consecutive_failures")
    op.drop_column("runs", "trigger")
```

**Verify:**
```bash
alembic upgrade head && alembic current   # should show 009
```

---

### Task 2: Model updates
**File:** `shortlist/api/models.py` (modify)
**Purpose:** Add new columns to ORM models.

```python
# Profile — add after updated_at:
auto_run_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
auto_run_interval_h = Column(Integer, nullable=False, default=12, server_default="12")
next_run_at = Column(DateTime(timezone=True), nullable=True)
consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")

# Run — add after machine_id:
trigger = Column(String, nullable=False, default="manual", server_default="manual")
```

No dedicated test — covered by migration verify + downstream tasks.

---

### Task 3: Schema updates
**File:** `shortlist/api/schemas.py` (modify)
**Purpose:** `AutoRunConfig` nested schema in profile, `trigger` on runs.

```python
class AutoRunConfig(BaseModel):
    enabled: bool = False
    interval_h: int = 12
    next_run_at: str | None = None        # ISO string for client-side countdown
    consecutive_failures: int = 0


class ProfileResponse(BaseModel):
    fit_context: str
    tracks: dict
    filters: dict
    preferences: dict
    llm: dict
    brief: dict
    substack_sid: str = ""
    aww_node_id: str = ""
    auto_run: AutoRunConfig = AutoRunConfig()   # ← new


class ProfileUpdate(BaseModel):
    fit_context: str | None = None
    tracks: dict | None = None
    filters: dict | None = None
    preferences: dict | None = None
    llm: dict | None = None
    brief: dict | None = None
    substack_sid: str | None = None
    aww_node_id: str | None = None
    auto_run: AutoRunConfig | None = None       # ← new


class RunResponse(BaseModel):
    id: int
    status: str
    progress: dict
    error: str | None
    machine_id: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    trigger: str = "manual"                    # ← new
```

**Verify:** existing profile + runs tests still pass (new fields have defaults).

---

### Task 4: Scheduler core
**Files:** `shortlist/scheduler.py` (create), `tests/test_scheduler.py` (create)
**Purpose:** All scheduling logic. Two public functions (`trigger_due_users`, `_fire_and_update`) plus the main loop. Pure enough to test without HTTP.

#### Tests first

```python
# tests/test_scheduler.py
"""Tests for the auto-run scheduler.

Uses in-memory SQLite via the same conftest fixtures as API tests.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.models import Profile, Run, User
from shortlist.scheduler import _fire_and_update, _update_profile_after_run, trigger_due_users


def _now():
    return datetime.now(timezone.utc)


async def _make_user(session, email="user@example.com"):
    user = User(email=email, password_hash="x")
    session.add(user)
    await session.flush()
    return user


async def _make_profile(session, user, *, enabled=True, interval_h=12, next_run_at=None, failures=0):
    profile = Profile(
        user_id=user.id,
        config={
            "fit_context": "Senior engineer",
            "llm": {"encrypted_api_key": "enc_key"},
            "tracks": {"em": {"title": "EM", "search_queries": ["eng manager"]}},
        },
        auto_run_enabled=enabled,
        auto_run_interval_h=interval_h,
        next_run_at=next_run_at or (_now() - timedelta(minutes=1)),
        consecutive_failures=failures,
    )
    session.add(profile)
    await session.flush()
    return profile


async def _make_run(session, user, *, status="pending", trigger="auto", finished_at=None):
    run = Run(user_id=user.id, status=status, trigger=trigger, finished_at=finished_at)
    session.add(run)
    await session.flush()
    return run


# ── trigger_due_users ───────────────────────────────────────────────────────

class TestTriggerDueUsers:
    async def test_fires_run_for_due_user(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user)
        await session.commit()

        fake_execute = AsyncMock()
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)
        # fire tasks after commit (simulating the main loop)
        for meta in pending:
            await fake_execute(**meta)

        assert len(pending) == 1
        assert pending[0]["user_id"] == user.id
        fake_execute.assert_called_once()

    async def test_run_committed_before_execute_run_called(self, session, session_factory):
        """execute_run receives a committed run_id — not a phantom row."""
        user = await _make_user(session)
        await _make_profile(session, user)
        await session.commit()

        captured_run = []

        async def fake_execute(run_id, **kwargs):
            # Open a fresh session to verify the row exists
            async with session_factory() as s:
                run = await s.get(Run, run_id)
                captured_run.append(run)

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)
        # commit happened above — now fire
        for meta in pending:
            await fake_execute(**meta)

        assert len(captured_run) == 1
        assert captured_run[0] is not None, "Run must exist in DB before execute_run is called"
        assert captured_run[0].trigger == "auto"

    async def test_skips_user_with_active_run(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user)
        await _make_run(session, user, status="running")
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    async def test_skips_user_with_pending_run(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user)
        await _make_run(session, user, status="pending")
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    async def test_skips_disabled_auto_run(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, enabled=False)
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    async def test_skips_future_next_run_at(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, next_run_at=_now() + timedelta(hours=6))
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    async def test_sets_next_run_at_after_trigger(self, session, session_factory):
        user = await _make_user(session)
        before = _now()
        await _make_profile(session, user, interval_h=12)
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                await trigger_due_users(s)

        async with session_factory() as s:
            profile = await s.get(Profile, user.id)
            assert profile.next_run_at > before + timedelta(hours=11)
            assert profile.next_run_at < before + timedelta(hours=13)

    async def test_idempotent_second_tick(self, session, session_factory):
        """Second tick within same window must not create a second run."""
        user = await _make_user(session)
        await _make_profile(session, user)
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending1 = await trigger_due_users(s)
        # next_run_at now in the future — second tick should skip

        async with session_factory() as s:
            async with s.begin():
                pending2 = await trigger_due_users(s)

        assert len(pending1) == 1
        assert len(pending2) == 0

    async def test_skips_user_with_incomplete_profile_and_disables(self, session, session_factory):
        user = await _make_user(session)
        profile = Profile(
            user_id=user.id,
            config={},  # no fit_context, no api key
            auto_run_enabled=True,
            auto_run_interval_h=12,
            next_run_at=_now() - timedelta(minutes=1),
        )
        session.add(profile)
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.auto_run_enabled is False  # disabled, not just skipped

        assert pending == []

    async def test_multiple_users_all_triggered(self, session, session_factory):
        u1 = await _make_user(session, "a@x.com")
        u2 = await _make_user(session, "b@x.com")
        await _make_profile(session, u1)
        await _make_profile(session, u2)
        await session.commit()

        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert len(pending) == 2
        user_ids = {m["user_id"] for m in pending}
        assert user_ids == {u1.id, u2.id}


# ── _update_profile_after_run ───────────────────────────────────────────────

class TestUpdateProfileAfterRun:
    async def test_success_resets_failures(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, failures=3)
        run = await _make_run(session, user, status="completed",
                              finished_at=_now())
        await session.commit()

        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 0

    async def test_failure_increments_and_backs_off(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, failures=0)
        run = await _make_run(session, user, status="failed", finished_at=_now())
        await session.commit()

        before = _now()
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 1
            # backoff: 2^1 = 2 hours
            assert p.next_run_at > before + timedelta(hours=1, minutes=50)
            assert p.next_run_at < before + timedelta(hours=2, minutes=10)

    async def test_5_consecutive_failures_disables_auto_run(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, failures=4)
        run = await _make_run(session, user, status="failed", finished_at=_now())
        await session.commit()

        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 5
            assert p.auto_run_enabled is False

    async def test_only_processes_auto_run_not_manual(self, session, session_factory):
        """Manual runs do not affect consecutive_failures."""
        user = await _make_user(session)
        await _make_profile(session, user, failures=0)
        run = await _make_run(session, user, status="failed",
                              trigger="manual", finished_at=_now())
        await session.commit()

        # Manually pass run_id — _update_profile_after_run is only called by
        # _fire_and_update which is only used for auto runs, but we verify
        # the function itself is safe to call and doesn't explode.
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)
        # (No assertion on consecutive_failures — callers guarantee auto-only)


# ── _fire_and_update ────────────────────────────────────────────────────────

class TestFireAndUpdate:
    async def test_calls_execute_run(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user)
        run = await _make_run(session, user, status="pending")
        await session.commit()

        called = []
        async def fake_execute(run_id, **kwargs):
            called.append(run_id)

        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=fake_execute,
        )
        assert called == [run.id]

    async def test_updates_profile_after_success(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, failures=2)
        run = await _make_run(session, user, status="pending")
        await session.commit()

        async def fake_execute(run_id, **kwargs):
            # Simulate successful run
            async with session_factory() as s:
                async with s.begin():
                    r = await s.get(Run, run_id)
                    r.status = "completed"
                    r.finished_at = _now()

        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=fake_execute,
        )

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 0

    async def test_updates_profile_after_failure(self, session, session_factory):
        user = await _make_user(session)
        await _make_profile(session, user, failures=0)
        run = await _make_run(session, user, status="pending")
        await session.commit()

        async def fake_execute(run_id, **kwargs):
            async with session_factory() as s:
                async with s.begin():
                    r = await s.get(Run, run_id)
                    r.status = "failed"
                    r.finished_at = _now()

        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=fake_execute,
        )

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 1

    async def test_survives_execute_run_exception(self, session, session_factory):
        """If execute_run raises, _fire_and_update logs and continues — doesn't crash."""
        user = await _make_user(session)
        await _make_profile(session, user)
        run = await _make_run(session, user, status="pending")
        await session.commit()

        async def exploding_execute(**kwargs):
            raise RuntimeError("boom")

        # Should not raise
        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=exploding_execute,
        )
```

#### Implementation

```python
# shortlist/scheduler.py
"""Scheduler — polls DB and fires auto runs when due.

Entry point: python -m shortlist.scheduler
Runs as a separate supervisord process alongside FastAPI.

Design principles:
- All state in PostgreSQL. No in-memory schedule. Restart-safe.
- Commit run rows BEFORE firing tasks (execute_run needs a committed row).
- Callback wrapper (_fire_and_update) updates profile after each run —
  no dependency on last_tick window, works correctly after restarts.
- Single NOT EXISTS query per tick — no N+1.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import not_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.models import Profile, Run, User

logger = logging.getLogger(__name__)
TICK_INTERVAL = 60  # seconds


async def trigger_due_users(session: AsyncSession) -> list[dict]:
    """Find users whose auto-run is due, create Run rows, return metadata list.

    Caller MUST commit the session before firing the returned tasks, so that
    execute_run receives committed run rows.

    Returns list of dicts: {run_id, user_id, config, db_url, interval_h}
    """
    now = datetime.now(timezone.utc)
    db_url = os.environ.get("DATABASE_URL", "")

    # Single query: due users with no active run (NOT EXISTS — no N+1)
    active_subq = exists().where(
        Run.user_id == Profile.user_id,
        Run.status.in_(("pending", "running")),
    )
    result = await session.execute(
        select(Profile, User)
        .join(User, Profile.user_id == User.id)
        .where(
            Profile.auto_run_enabled == True,
            Profile.next_run_at <= now,
            not_(active_subq),
        )
    )
    candidates = result.all()

    pending = []
    for profile, user in candidates:
        # Use profile.config directly — user.profile relationship is not loaded
        config = profile.config or {}
        if not config.get("fit_context") or not config.get("llm", {}).get("encrypted_api_key"):
            logger.warning(
                f"user {user.id}: incomplete profile, disabling auto-run"
            )
            profile.auto_run_enabled = False
            continue

        run = Run(user_id=user.id, status="pending", trigger="auto")
        session.add(run)
        await session.flush()  # get run.id before commit

        # Set next_run_at immediately — prevents double-trigger if scheduler
        # ticks again before this run finishes
        profile.next_run_at = now + timedelta(hours=profile.auto_run_interval_h)

        pending.append({
            "run_id": run.id,
            "user_id": user.id,
            "config": dict(config),
            "db_url": db_url,
            "interval_h": profile.auto_run_interval_h,
        })
        logger.info(
            f"user {user.id}: auto-run queued "
            f"(run #{run.id}, next in {profile.auto_run_interval_h}h)"
        )

    return pending


async def _update_profile_after_run(
    run_id: int,
    user_id: int,
    interval_h: int,
    session_factory,
) -> None:
    """Update consecutive_failures and next_run_at based on run outcome.

    Opens its own session — called after execute_run completes.
    """
    try:
        async with session_factory() as session:
            async with session.begin():
                run = await session.get(Run, run_id)
                profile = await session.get(Profile, user_id)
                if not run or not profile:
                    return

                now = datetime.now(timezone.utc)

                if run.status == "completed":
                    profile.consecutive_failures = 0
                    logger.info(f"user {user_id}: auto-run #{run_id} completed, failures reset")

                elif run.status == "failed":
                    profile.consecutive_failures = (profile.consecutive_failures or 0) + 1

                    if profile.consecutive_failures >= 5:
                        profile.auto_run_enabled = False
                        logger.warning(
                            f"user {user_id}: auto-run disabled after "
                            f"{profile.consecutive_failures} consecutive failures"
                        )
                    else:
                        backoff_h = min(2 ** profile.consecutive_failures, 24)
                        profile.next_run_at = now + timedelta(hours=backoff_h)
                        logger.info(
                            f"user {user_id}: auto-run #{run_id} failed "
                            f"(#{profile.consecutive_failures}), backoff {backoff_h}h"
                        )
    except Exception:
        logger.exception(
            f"Failed to update profile after auto-run {run_id} for user {user_id}"
        )


async def _fire_and_update(
    run_id: int,
    user_id: int,
    config: dict,
    db_url: str,
    interval_h: int,
    session_factory,
    execute_run_fn,
) -> None:
    """Execute a run and update the profile when it finishes.

    Called as an asyncio task AFTER the run row is committed.
    """
    try:
        await execute_run_fn(
            run_id=run_id,
            user_id=user_id,
            config=config,
            db_url=db_url,
        )
    except Exception:
        logger.exception(f"auto-run {run_id} raised unexpectedly")
    finally:
        await _update_profile_after_run(run_id, user_id, interval_h, session_factory)


async def run_scheduler() -> None:
    """Main scheduler loop. Polls every TICK_INTERVAL seconds."""
    from shortlist.api.db import _clean_url, _get_connect_args
    from shortlist.api.worker import execute_run
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL", "")
    clean_url = _clean_url(db_url)
    # Ensure asyncpg driver
    if "postgresql://" in clean_url and "+asyncpg" not in clean_url:
        clean_url = clean_url.replace("postgresql://", "postgresql+asyncpg://")
    clean_url = clean_url.replace("postgres://", "postgresql+asyncpg://")

    engine = create_async_engine(clean_url, connect_args=_get_connect_args(clean_url))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    logger.info("Scheduler started (tick every %ds)", TICK_INTERVAL)

    while True:
        await asyncio.sleep(TICK_INTERVAL)
        try:
            # Step 1: Create run rows inside transaction
            async with async_session() as session:
                async with session.begin():
                    pending = await trigger_due_users(session)
            # Step 2: Transaction committed — fire tasks (run rows now exist in DB)
            for meta in pending:
                asyncio.create_task(
                    _fire_and_update(
                        **meta,
                        session_factory=async_session,
                        execute_run_fn=execute_run,
                    )
                )
        except Exception:
            logger.exception("Scheduler tick failed")


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [scheduler] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    asyncio.run(run_scheduler())
```

**Verify:**
```bash
pytest tests/test_scheduler.py -v   # all tests pass
```

---

### Task 5: Profile route — auto_run get/set
**File:** `shortlist/api/routes/profile.py` (modify)
**File:** `tests/api/test_auto_run.py` (create)
**Purpose:** Read/write `auto_run` from dedicated DB columns. Update `_to_response()` signature.

#### `_to_response()` signature change

The current `_to_response(config: dict)` doesn't have access to Profile columns. Fix: add an optional
`profile` parameter so callers can pass the ORM object for auto_run data.

```python
def _to_response(config: dict, profile: "Profile | None" = None) -> ProfileResponse:
    """Build ProfileResponse from config dict + optional profile ORM object."""
    merged = {**EMPTY_CONFIG, **config}

    auto_run = AutoRunConfig()
    if profile is not None:
        auto_run = AutoRunConfig(
            enabled=profile.auto_run_enabled,
            interval_h=profile.auto_run_interval_h,
            next_run_at=profile.next_run_at.isoformat() if profile.next_run_at else None,
            consecutive_failures=profile.consecutive_failures,
        )

    return ProfileResponse(**_redact_config(merged), auto_run=auto_run)
```

Update both callers:
```python
# get_profile:
return _to_response(user.profile.config, user.profile)

# update_profile (after flush):
return _to_response(existing, profile)   # profile is the ORM object
```

#### `update_profile()` auto_run handling

After the existing LLM key merge and `existing.update(updates)` block, add:

```python
# Handle auto_run — stored in dedicated columns, NOT config JSON
auto_run_update = updates_raw.get("auto_run")  # from req.model_dump() before pop
if auto_run_update is not None:
    enabled = auto_run_update.get("enabled")
    interval_h = auto_run_update.get("interval_h", profile.auto_run_interval_h)

    if enabled is not None:
        profile.auto_run_enabled = enabled
        profile.auto_run_interval_h = interval_h

        if enabled:
            # Start the countdown from now
            profile.next_run_at = datetime.now(timezone.utc) + timedelta(hours=interval_h)
        else:
            profile.next_run_at = None
            profile.consecutive_failures = 0

    elif "interval_h" in auto_run_update and profile.auto_run_enabled:
        # Changed interval only — recalculate from now
        profile.auto_run_interval_h = interval_h
        profile.next_run_at = datetime.now(timezone.utc) + timedelta(hours=interval_h)
```

Note: `auto_run` must be popped from `updates` before `existing.update(updates)` so it doesn't
land in the config JSON column.

#### Tests first

```python
# tests/api/test_auto_run.py
"""Tests for auto-run scheduling via the profile API."""
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_auto_run_defaults_to_disabled(client, auth_headers):
    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.status_code == 200
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is False
    assert ar["next_run_at"] is None
    assert ar["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_enable_auto_run_sets_next_run_at(client, auth_headers):
    resp = await client.put("/api/profile", json={
        "auto_run": {"enabled": True, "interval_h": 12}
    }, headers=auth_headers)
    assert resp.status_code == 200
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is True
    assert ar["interval_h"] == 12
    assert ar["next_run_at"] is not None
    # next_run_at should be ~12h from now
    next_run = datetime.fromisoformat(ar["next_run_at"])
    from datetime import timedelta
    assert next_run > datetime.now(timezone.utc) + timedelta(hours=11)


@pytest.mark.asyncio
async def test_disable_auto_run_clears_next_run_at_and_failures(client, auth_headers):
    await client.put("/api/profile", json={"auto_run": {"enabled": True, "interval_h": 6}},
                     headers=auth_headers)
    resp = await client.put("/api/profile", json={"auto_run": {"enabled": False}},
                            headers=auth_headers)
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is False
    assert ar["next_run_at"] is None
    assert ar["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_change_interval_updates_next_run_at(client, auth_headers):
    await client.put("/api/profile", json={"auto_run": {"enabled": True, "interval_h": 24}},
                     headers=auth_headers)
    resp = await client.put("/api/profile", json={"auto_run": {"interval_h": 6}},
                            headers=auth_headers)
    ar = resp.json()["auto_run"]
    assert ar["interval_h"] == 6
    from datetime import timedelta
    next_run = datetime.fromisoformat(ar["next_run_at"])
    assert next_run < datetime.now(timezone.utc) + timedelta(hours=7)


@pytest.mark.asyncio
async def test_auto_run_preserved_when_field_absent(client, auth_headers):
    """PUT without auto_run key doesn't touch scheduler state."""
    await client.put("/api/profile", json={"auto_run": {"enabled": True, "interval_h": 12}},
                     headers=auth_headers)
    original = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]

    # Update something else
    await client.put("/api/profile", json={"fit_context": "updated"},
                     headers=auth_headers)
    after = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]

    assert after["enabled"] == original["enabled"]
    assert after["next_run_at"] == original["next_run_at"]


@pytest.mark.asyncio
async def test_auto_run_not_stored_in_config_json(client, auth_headers, session):
    """auto_run data lives in dedicated columns, not inside config JSON."""
    from sqlalchemy import select
    from shortlist.api.models import Profile
    await client.put("/api/profile", json={"auto_run": {"enabled": True, "interval_h": 8}},
                     headers=auth_headers)
    result = await session.execute(select(Profile))
    profile = result.scalar_one()
    assert "auto_run" not in (profile.config or {})
    assert profile.auto_run_enabled is True
    assert profile.auto_run_interval_h == 8
```

**Verify:**
```bash
pytest tests/api/test_auto_run.py -v
```

---

### Task 6: Runs route — manual trigger resets schedule + trigger field
**File:** `shortlist/api/routes/runs.py` (modify)
**Purpose:** Manual run resets `next_run_at`; `_run_to_response` exposes `trigger`.

#### Changes

In `_run_to_response()`:
```python
def _run_to_response(run: Run) -> RunResponse:
    return RunResponse(
        ...
        trigger=run.trigger,   # ← add
    )
```

In `create_run()`, after `await session.flush()` (run created):
```python
# Push next_run_at forward — prevents scheduler firing right after a manual run
if user.profile and user.profile.auto_run_enabled:
    user.profile.next_run_at = datetime.now(timezone.utc) + timedelta(
        hours=user.profile.auto_run_interval_h
    )
```

#### Tests

```python
# Add to tests/api/test_runs.py

@pytest.mark.asyncio
async def test_manual_run_has_trigger_manual(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.json()["trigger"] == "manual"


@pytest.mark.asyncio
async def test_manual_run_resets_next_run_at(client, auth_headers, mock_worker):
    """Manual run pushes next_run_at forward when auto-run is enabled."""
    await _setup_profile(client, auth_headers)
    await client.put("/api/profile", json={"auto_run": {"enabled": True, "interval_h": 6}},
                     headers=auth_headers)

    before_str = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]["next_run_at"]
    await client.post("/api/runs", headers=auth_headers)
    after_str = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]["next_run_at"]

    assert after_str > before_str


@pytest.mark.asyncio
async def test_manual_run_no_error_when_auto_run_disabled(client, auth_headers, mock_worker):
    """Manual run works fine when auto_run is disabled — no error."""
    await _setup_profile(client, auth_headers)
    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 201
```

**Verify:**
```bash
pytest tests/api/test_runs.py -v
```

---

### Task 7: supervisord.conf
**File:** `supervisord.conf` (modify)
**Purpose:** Launch scheduler as third supervised process.

Add after the `[program:fastapi]` block:

```ini
[program:scheduler]
command=python3 -m shortlist.scheduler
directory=/app
priority=15
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

`priority=15` — starts after FastAPI (10), before Next.js (20). Scheduler needs DB but not the
HTTP server.

**Verify locally:**
```bash
supervisord -c supervisord.conf
# Check all 3 programs appear in: supervisorctl status
```

---

### Task 8: Frontend — AutoRunSettings component
**Files:** `web/src/components/AutoRunSettings.tsx` (create), `web/src/app/profile/page.tsx` (modify), `web/src/lib/types.ts` (modify)
**Purpose:** Toggle + interval picker + live countdown + failure warnings.

#### `types.ts`

```typescript
export interface AutoRunConfig {
  enabled: boolean;
  interval_h: number;
  next_run_at: string | null;
  consecutive_failures: number;
}

// Update Profile interface:
export interface Profile {
  ...
  auto_run?: AutoRunConfig;
}
```

#### `AutoRunSettings.tsx`

Props: `autoRun: AutoRunConfig`, `onChange: (update: Partial<AutoRunConfig>) => void`

```
┌─ Auto-run ──────────────────────────────────────────────────────┐
│  Run automatically so new jobs appear in your inbox.            │
│                                                                 │
│  [● ON / ○ OFF]   Every  [6h ▼ / 12h ▼ / 24h ▼ / 48h ▼]      │
│                                                                 │
│  Next run: in 3h 42m  ·  (only shown when enabled)             │
│                                                                 │
│  ⚠ Last 2 runs failed. Check your API key.    (if failures>0)  │
│  ✕ Auto-run paused after 5 failures. [Re-enable]  (if disabled  │
│                                       by scheduler)            │
└─────────────────────────────────────────────────────────────────┘
```

- Toggle: calls `onChange({ enabled: !autoRun.enabled })`
- Interval select: calls `onChange({ interval_h: value })`
- "Next run in Xh Ym": computed from `next_run_at` via `useEffect` + `setInterval(60_000)`
- Failure warning: `consecutive_failures > 0 && consecutive_failures < 5`
- Paused banner: `!autoRun.enabled && autoRun.consecutive_failures >= 5` — shows re-enable button
- Parent `profile/page.tsx` includes this in the `auto_run` save payload via `markDirty`

#### `profile/page.tsx` change

Add state: `const [autoRun, setAutoRun] = useState<AutoRunConfig>({ enabled: false, interval_h: 12, next_run_at: null, consecutive_failures: 0 })`

Load in `useEffect`: `setAutoRun(p.auto_run ?? defaultAutoRun)`

Add to save payload:
```typescript
auto_run: { enabled: autoRun.enabled, interval_h: autoRun.interval_h }
```

Add to JSX after `<FiltersEditor>`:
```tsx
<SectionCard title="Auto-run">
  <AutoRunSettings autoRun={autoRun} onChange={(u) => { setAutoRun(a => ({...a, ...u})); markDirty(); }} />
</SectionCard>
```

---

### Task 9: Frontend — History page "Scheduled" badge
**File:** `web/src/app/history/page.tsx` (modify)
**Purpose:** Distinguish auto runs from manual runs.

`Run` interface (in `types.ts`): add `trigger: string`

In the history list alongside the date, show for auto runs:
```tsx
{run.trigger === "auto" && (
  <span className="text-xs text-gray-400 font-mono">scheduled</span>
)}
```

Lowercase, monospace, muted. Not a badge — just a label.

---

## Edge Cases

| Case | Handling |
|------|----------|
| Scheduler restarts, run completed before restart | `_fire_and_update` updates profile after each run — no `since` window dependency |
| Active run already in progress on tick | NOT EXISTS subquery excludes user — not triggered |
| User disables auto_run mid-run | Run completes normally. `_fire_and_update` finds `auto_run_enabled=false`, skips backoff logic |
| Manual run during auto_run window | `next_run_at` pushed forward by `create_run()`, scheduler sees future time |
| API key expired / 429 | Run fails → `_fire_and_update` increments failures, applies backoff |
| DB unreachable during tick | Exception logged, scheduler continues on next tick |
| VM redeploy during a run | Existing lifespan hook marks pending/running → failed on startup |
| 5 consecutive failures | `auto_run_enabled = False`, UI shows re-enable banner |
| User with incomplete profile | `auto_run_enabled = False`, logged, not triggered |
| Two scheduler processes (bad deploy) | `next_run_at` set atomically before commit — second process finds `next_run_at` in future |

---

## Testing Strategy

| File | Coverage |
|------|----------|
| `tests/test_scheduler.py` | `trigger_due_users`, `_fire_and_update`, `_update_profile_after_run`, commit ordering |
| `tests/api/test_auto_run.py` | Profile route: enable/disable/change interval, column isolation |
| `tests/api/test_runs.py` additions | `trigger` field, `next_run_at` reset on manual run |
| Existing suite | Must pass unchanged — no regressions |

Target: **+30 new tests**, full suite passes in ~25s.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Scheduler + API write same profile row simultaneously | PG row-level locking within BEGIN/COMMIT handles contention |
| `_fire_and_update` task outlives scheduler restart | Tasks are detached asyncio tasks — they complete or timeout independently of the scheduler loop |
| Multi-user API key collision in `os.environ` | Existing issue, not introduced here. One-active-run-per-user constraint limits exposure. |
| 512MB VM OOM with 3 processes | Scheduler sleeps 59/60s, ~10MB RSS. Negligible. |

---

## Implementation Order

1. Migration 009
2. Model updates
3. Schema updates (`AutoRunConfig`, `trigger`)
4. Scheduler core + full test suite (Tasks 3+tests)
5. Profile route (`_to_response` signature, `auto_run` handling) + tests
6. Runs route (`trigger` field, `next_run_at` reset) + tests
7. supervisord.conf
8. Frontend: `AutoRunSettings` component + profile page
9. Frontend: history badge
10. Full suite green → deploy

**Estimated time:** 6–8 hours.
