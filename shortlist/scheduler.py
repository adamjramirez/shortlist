"""Scheduler — polls DB and fires auto runs when due.

Entry point: python -m shortlist.scheduler
Runs as a separate supervisord process alongside FastAPI.

Design principles:
- All state in PostgreSQL. No in-memory schedule. Restart-safe.
- Commit run rows BEFORE firing tasks (execute_run needs a committed row).
- _fire_and_update() updates the profile after each run completes —
  no dependency on a last_tick window, works correctly after restarts.
- Single NOT EXISTS query per tick — no N+1 active-run checks.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from shortlist.expiry import check_expiry_batch  # noqa: F401 — imported for monkeypatching

from sqlalchemy import not_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.models import Profile, Run, User

logger = logging.getLogger(__name__)
TICK_INTERVAL = 60  # seconds
ZOMBIE_RUN_TIMEOUT_MINUTES = 45  # runs stuck in 'running' longer than this are dead


async def reap_zombie_runs(session: AsyncSession) -> int:
    """Mark runs stuck in 'running' for too long as 'failed'.

    Zombies occur when the process is OOM-killed mid-run — the finally block
    in _fire_and_update never executes, leaving the run row in 'running' forever.
    The scheduler's NOT EXISTS check then blocks all future runs for that user.

    Returns the number of runs reaped.
    """
    from sqlalchemy import update, and_
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ZOMBIE_RUN_TIMEOUT_MINUTES)
    result = await session.execute(
        update(Run)
        .where(
            and_(
                Run.status == "running",
                Run.created_at <= cutoff,
            )
        )
        .values(status="failed")
        .returning(Run.id)
    )
    reaped = result.fetchall()
    if reaped:
        ids = [r[0] for r in reaped]
        logger.warning("Reaped %d zombie run(s): %s", len(ids), ids)
    return len(reaped)


async def trigger_due_users(session: AsyncSession) -> list[dict]:
    """Find users whose auto-run is due, create Run rows, return metadata list.

    The caller MUST commit the session before firing the returned tasks so
    that execute_run receives committed run rows.

    Returns list of dicts with keys: run_id, user_id, config, db_url, interval_h
    """
    now = datetime.now(timezone.utc)
    db_url = os.environ.get("DATABASE_URL", "")

    # Single query: due users with no active run (NOT EXISTS avoids N+1)
    active_subq = exists().where(
        Run.user_id == Profile.user_id,
        Run.status.in_(("pending", "running")),
    )
    result = await session.execute(
        select(Profile, User)
        .join(User, Profile.user_id == User.id)
        .where(
            Profile.auto_run_enabled == True,  # noqa: E712
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
            logger.warning("user %d: incomplete profile, disabling auto-run", user.id)
            profile.auto_run_enabled = False
            continue

        run = Run(user_id=user.id, status="pending", trigger="auto")
        session.add(run)
        await session.flush()  # get run.id before commit

        # Set next_run_at now — prevents double-trigger on the next tick
        profile.next_run_at = now + timedelta(hours=profile.auto_run_interval_h)

        pending.append({
            "run_id": run.id,
            "user_id": user.id,
            "config": dict(config),
            "db_url": db_url,
            "interval_h": profile.auto_run_interval_h,
        })
        logger.info(
            "user %d: auto-run queued (run #%d, next in %dh)",
            user.id, run.id, profile.auto_run_interval_h,
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
    Restart-safe: no dependency on in-memory state or last_tick window.
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
                    logger.info("user %d: auto-run #%d completed, failures reset", user_id, run_id)

                elif run.status == "failed":
                    profile.consecutive_failures = (profile.consecutive_failures or 0) + 1

                    if profile.consecutive_failures >= 5:
                        profile.auto_run_enabled = False
                        logger.warning(
                            "user %d: auto-run disabled after %d consecutive failures",
                            user_id, profile.consecutive_failures,
                        )
                    else:
                        backoff_h = min(2 ** profile.consecutive_failures, 24)
                        profile.next_run_at = now + timedelta(hours=backoff_h)
                        logger.info(
                            "user %d: auto-run #%d failed (#%d), backoff %dh",
                            user_id, run_id, profile.consecutive_failures, backoff_h,
                        )
    except Exception:
        logger.exception(
            "Failed to update profile after auto-run %d for user %d", run_id, user_id
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
    execute_run catches its own exceptions internally and sets run.status='failed',
    so we only need to handle unexpected raises here.
    """
    try:
        await execute_run_fn(
            run_id=run_id,
            user_id=user_id,
            config=config,
            db_url=db_url,
        )
    except Exception:
        logger.exception("auto-run %d raised unexpectedly", run_id)
    finally:
        await _update_profile_after_run(run_id, user_id, interval_h, session_factory)


_URL_CHECK_DISABLED_LOGGED = False


async def run_expiry_checks(db_url: str) -> None:
    """Run a batch of proactive job expiry checks. Called each scheduler tick.

    Errors are caught and logged — must never crash the scheduler tick.
    """
    global _URL_CHECK_DISABLED_LOGGED
    if os.environ.get("DISABLE_URL_CHECK") == "1":
        if not _URL_CHECK_DISABLED_LOGGED:
            logger.warning("url_check DISABLED via DISABLE_URL_CHECK env var — skipping expiry checks")
            _URL_CHECK_DISABLED_LOGGED = True
        return
    try:
        import shortlist.scheduler as _self
        result = await asyncio.to_thread(_self.check_expiry_batch, db_url)
        if result["closed"] > 0:
            logger.info(
                "Expiry check: %d closed, %d checked, %d errors",
                result["closed"], result["checked"], result["errors"],
            )
    except Exception:
        logger.exception("run_expiry_checks failed")


async def run_scheduler() -> None:
    """Main scheduler loop. Polls every TICK_INTERVAL seconds."""
    from shortlist.api.db import _clean_url, _get_connect_args
    from shortlist.api.worker import execute_run
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL", "")
    clean_url = _clean_url(db_url)
    # Ensure asyncpg driver for PostgreSQL
    if "postgresql://" in clean_url and "+asyncpg" not in clean_url:
        clean_url = clean_url.replace("postgresql://", "postgresql+asyncpg://")
    clean_url = clean_url.replace("postgres://", "postgresql+asyncpg://")

    engine = create_async_engine(clean_url, connect_args=_get_connect_args(clean_url))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    logger.info("Scheduler started (tick every %ds)", TICK_INTERVAL)

    while True:
        await asyncio.sleep(TICK_INTERVAL)
        try:
            # Step 1: Reap zombies + create new run rows (same transaction)
            async with async_session() as session:
                async with session.begin():
                    await reap_zombie_runs(session)
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

            # Step 3: Proactive expiry checks (non-blocking, own DB connection)
            asyncio.create_task(run_expiry_checks(db_url))

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
