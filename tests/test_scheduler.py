"""Tests for the auto-run scheduler.

Uses in-memory SQLite via the API test conftest session fixtures.
All scheduler functions are pure (take session/session_factory) — no HTTP needed.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shortlist.api.models import Base, Profile, Run, User


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def engine(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'sched.db'}"
    e = create_async_engine(url, echo=False)
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _past(minutes=1):
    return _now() - timedelta(minutes=minutes)


def _future(hours=6):
    return _now() + timedelta(hours=hours)


def _as_utc(dt):
    """Ensure datetime is UTC-aware (SQLite returns naive datetimes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _make_user(session, email="user@example.com"):
    user = User(email=email, password_hash="x")
    session.add(user)
    await session.flush()
    return user


async def _make_profile(
    session,
    user,
    *,
    enabled=True,
    interval_h=12,
    next_run_at=None,
    failures=0,
    complete=True,  # whether config has fit_context + api key
):
    config = (
        {
            "fit_context": "Senior engineer",
            "llm": {"encrypted_api_key": "enc_key"},
            "tracks": {"em": {"title": "EM", "search_queries": ["eng manager"]}},
        }
        if complete
        else {}
    )
    profile = Profile(
        user_id=user.id,
        config=config,
        auto_run_enabled=enabled,
        auto_run_interval_h=interval_h,
        next_run_at=next_run_at if next_run_at is not None else _past(),
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
    @pytest.mark.asyncio
    async def test_fires_run_for_due_user(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert len(pending) == 1
        assert pending[0]["user_id"] == user.id
        assert "run_id" in pending[0]
        assert pending[0]["interval_h"] == 12

    @pytest.mark.asyncio
    async def test_run_committed_before_execute_run_called(self, session_factory):
        """execute_run receives a committed run_id — not a phantom row."""
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)
        # Transaction committed above. Verify run exists in fresh session.

        captured = []
        async def fake_execute(run_id, **kwargs):
            async with session_factory() as s:
                run = await s.get(Run, run_id)
                captured.append(run)

        for meta in pending:
            await fake_execute(**meta)

        assert len(captured) == 1
        assert captured[0] is not None, "Run must be committed before execute_run is called"
        assert captured[0].trigger == "auto"
        assert captured[0].status == "pending"

    @pytest.mark.asyncio
    async def test_skips_user_with_running_run(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)
                await _make_run(s, user, status="running")

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    @pytest.mark.asyncio
    async def test_skips_user_with_pending_run(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)
                await _make_run(s, user, status="pending")

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    @pytest.mark.asyncio
    async def test_skips_disabled_auto_run(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, enabled=False)

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    @pytest.mark.asyncio
    async def test_skips_future_next_run_at(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, next_run_at=_future(hours=6))

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert pending == []

    @pytest.mark.asyncio
    async def test_sets_next_run_at_after_trigger(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, interval_h=12)

        before = _now()

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                await trigger_due_users(s)

        async with session_factory() as s:
            profile = await s.get(Profile, user.id)
            assert profile.next_run_at is not None
            assert _as_utc(profile.next_run_at) > before + timedelta(hours=11)
            assert _as_utc(profile.next_run_at) < before + timedelta(hours=13)

    @pytest.mark.asyncio
    async def test_idempotent_second_tick(self, session_factory):
        """Second tick in the same window must not create a second run."""
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending1 = await trigger_due_users(s)

        async with session_factory() as s:
            async with s.begin():
                pending2 = await trigger_due_users(s)

        assert len(pending1) == 1
        assert len(pending2) == 0

    @pytest.mark.asyncio
    async def test_incomplete_profile_disables_auto_run(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, complete=False)

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.auto_run_enabled is False

        assert pending == []

    @pytest.mark.asyncio
    async def test_multiple_users_all_triggered(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                u1 = await _make_user(s, "a@x.com")
                u2 = await _make_user(s, "b@x.com")
                await _make_profile(s, u1)
                await _make_profile(s, u2)

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert len(pending) == 2
        assert {m["user_id"] for m in pending} == {u1.id, u2.id}

    @pytest.mark.asyncio
    async def test_completed_run_does_not_block_next_trigger(self, session_factory):
        """A completed (non-active) run does not prevent a new auto run."""
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)
                await _make_run(s, user, status="completed")

        from shortlist.scheduler import trigger_due_users
        async with session_factory() as s:
            async with s.begin():
                pending = await trigger_due_users(s)

        assert len(pending) == 1


# ── _update_profile_after_run ───────────────────────────────────────────────

class TestUpdateProfileAfterRun:
    @pytest.mark.asyncio
    async def test_success_resets_consecutive_failures(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, failures=3)
                run = await _make_run(s, user, status="completed", finished_at=_now())

        from shortlist.scheduler import _update_profile_after_run
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_failure_increments_failures_and_backs_off(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, failures=0)
                run = await _make_run(s, user, status="failed", finished_at=_now())

        before = _now()

        from shortlist.scheduler import _update_profile_after_run
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 1
            # backoff: 2^1 = 2 hours
            assert _as_utc(p.next_run_at) > before + timedelta(hours=1, minutes=50)
            assert _as_utc(p.next_run_at) < before + timedelta(hours=2, minutes=10)

    @pytest.mark.asyncio
    async def test_second_failure_doubles_backoff(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, failures=1)
                run = await _make_run(s, user, status="failed", finished_at=_now())

        before = _now()

        from shortlist.scheduler import _update_profile_after_run
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 2
            # backoff: 2^2 = 4 hours
            assert _as_utc(p.next_run_at) > before + timedelta(hours=3, minutes=50)

    @pytest.mark.asyncio
    async def test_fifth_failure_disables_auto_run(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, failures=4)
                run = await _make_run(s, user, status="failed", finished_at=_now())

        from shortlist.scheduler import _update_profile_after_run
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 5
            assert p.auto_run_enabled is False

    @pytest.mark.asyncio
    async def test_backoff_capped_at_24h(self, session_factory):
        """Backoff never exceeds 24h regardless of failure count."""
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                # failures=4 → 2^5=32h, capped at 24
                await _make_profile(s, user, failures=4)
                run = await _make_run(s, user, status="failed", finished_at=_now())

        before = _now()

        from shortlist.scheduler import _update_profile_after_run
        await _update_profile_after_run(run.id, user.id, interval_h=12,
                                        session_factory=session_factory)

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            if p.auto_run_enabled:  # only relevant if not disabled
                assert _as_utc(p.next_run_at) < before + timedelta(hours=25)

    @pytest.mark.asyncio
    async def test_tolerates_missing_run(self, session_factory):
        """Doesn't crash if run_id doesn't exist."""
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)

        from shortlist.scheduler import _update_profile_after_run
        # Should not raise
        await _update_profile_after_run(99999, user.id, interval_h=12,
                                        session_factory=session_factory)

    @pytest.mark.asyncio
    async def test_tolerates_missing_profile(self, session_factory):
        """Doesn't crash if profile doesn't exist for user_id."""
        from shortlist.scheduler import _update_profile_after_run
        await _update_profile_after_run(1, 99999, interval_h=12,
                                        session_factory=session_factory)


# ── _fire_and_update ────────────────────────────────────────────────────────

class TestFireAndUpdate:
    @pytest.mark.asyncio
    async def test_calls_execute_run(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)
                run = await _make_run(s, user, status="pending")

        called = []
        async def fake_execute(run_id, **kwargs):
            called.append(run_id)

        from shortlist.scheduler import _fire_and_update
        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=fake_execute,
        )
        assert called == [run.id]

    @pytest.mark.asyncio
    async def test_resets_failures_after_success(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, failures=2)
                run = await _make_run(s, user, status="pending")

        async def fake_success(run_id, **kwargs):
            async with session_factory() as s:
                async with s.begin():
                    r = await s.get(Run, run_id)
                    r.status = "completed"
                    r.finished_at = _now()

        from shortlist.scheduler import _fire_and_update
        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=fake_success,
        )

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_increments_failures_after_failure(self, session_factory):
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user, failures=0)
                run = await _make_run(s, user, status="pending")

        async def fake_failure(run_id, **kwargs):
            async with session_factory() as s:
                async with s.begin():
                    r = await s.get(Run, run_id)
                    r.status = "failed"
                    r.finished_at = _now()

        from shortlist.scheduler import _fire_and_update
        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=fake_failure,
        )

        async with session_factory() as s:
            p = await s.get(Profile, user.id)
            assert p.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_survives_execute_run_exception(self, session_factory):
        """Unhandled exception in execute_run is caught; profile update still runs."""
        async with session_factory() as s:
            async with s.begin():
                user = await _make_user(s)
                await _make_profile(s, user)
                run = await _make_run(s, user, status="pending")

        async def exploding_execute(**kwargs):
            raise RuntimeError("boom")

        from shortlist.scheduler import _fire_and_update
        # Must not raise
        await _fire_and_update(
            run_id=run.id, user_id=user.id,
            config={}, db_url="", interval_h=12,
            session_factory=session_factory,
            execute_run_fn=exploding_execute,
        )
