"""In-process pipeline worker.

Runs the pipeline in a background thread. Pipeline writes directly to
PostgreSQL via psycopg2 — no SQLite, no copy step.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from shortlist.api.crypto import decrypt
from shortlist.api.models import Run
from shortlist.config import SCORE_VISIBLE

logger = logging.getLogger(__name__)


def _pg_sync_url(async_url: str) -> str:
    """Convert async SQLAlchemy URL to sync psycopg2 URL.

    sqlite+aiosqlite:///... → not applicable
    postgresql+asyncpg://... → postgresql://...
    postgresql://... → postgresql://...
    """
    url = async_url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")
    return url


async def execute_run(run_id: int, user_id: int, config: dict, db_url: str) -> None:
    """Execute a pipeline run in background."""
    from shortlist.api.db import _clean_url, _get_connect_args

    clean_url = _clean_url(db_url)
    engine = create_async_engine(
        clean_url,
        connect_args=_get_connect_args(clean_url),
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Sync PG URL for the pipeline thread
    raw_db_url = os.environ.get("DATABASE_URL", db_url)
    sync_db_url = _pg_sync_url(raw_db_url)

    async def update_run(**kwargs):
        async with async_session() as session:
            await session.execute(
                update(Run).where(Run.id == run_id).values(**kwargs)
            )
            await session.commit()

    try:
        await update_run(
            status="running",
            started_at=datetime.now(timezone.utc),
            progress={"phase": "starting"},
        )

        # Build Config from profile
        from shortlist.config import Config, Track, Filters, LocationFilter, SalaryFilter, RoleTypeFilter, LLMConfig

        tracks_raw = config.get("tracks", {})
        tracks = {}
        for key, val in tracks_raw.items():
            tracks[key] = Track(
                title=val.get("title", key),
                search_queries=val.get("search_queries", []),
                resume=val.get("resume", ""),
                target_orgs=val.get("target_orgs", "any"),
                min_reports=val.get("min_reports", 0),
            )

        filters_raw = config.get("filters", {})
        loc = filters_raw.get("location", {})
        sal = filters_raw.get("salary", {})
        role = filters_raw.get("role_type", {})

        pipeline_config = Config(
            fit_context=config.get("fit_context", ""),
            tracks=tracks,
            filters=Filters(
                location=LocationFilter(
                    remote=loc.get("remote", True),
                    local_zip=loc.get("local_zip", ""),
                    max_commute_minutes=loc.get("max_commute_minutes", 30),
                    local_cities=loc.get("local_cities", []),
                ),
                salary=SalaryFilter(
                    min_base=sal.get("min_base", 0),
                    currency=sal.get("currency", "USD"),
                ),
                role_type=RoleTypeFilter(
                    reject_explicit_ic=role.get("reject_explicit_ic", True),
                ),
            ),
            llm=LLMConfig(
                model=config.get("llm", {}).get("model", "gemini-2.0-flash"),
                max_jobs_per_run=150,
            ),
        )

        # Configure LLM with user's API key
        encrypted_key = config.get("llm", {}).get("encrypted_api_key", "")
        if not encrypted_key:
            raise ValueError("No API key configured")

        api_key = decrypt(encrypted_key)

        from shortlist import llm as llm_module
        model = pipeline_config.llm.model
        provider = llm_module.detect_provider(model)
        env_key = llm_module._ENV_KEYS[provider]
        os.environ[env_key] = api_key
        llm_module.configure(model)

        # Set Substack SID if user provided one
        substack_sid = config.get("substack_sid", "")
        if substack_sid:
            os.environ["SUBSTACK_SID"] = substack_sid

        # Shared progress dict — sync thread writes, async flush loop reads
        progress = {}
        run_start_time = time.monotonic()

        def on_progress(data: dict):
            elapsed = time.monotonic() - run_start_time
            data["elapsed_seconds"] = int(elapsed)
            progress.update(data)

        # Cancel event — checked by pipeline at phase boundaries
        import threading as _threading
        cancel_event = _threading.Event()

        async def flush_progress():
            """Push progress to DB every 2s. Also check if run was cancelled."""
            try:
                while True:
                    await asyncio.sleep(2)
                    if progress:
                        await update_run(progress=dict(progress))
                    # Check if user cancelled
                    async with async_session() as session:
                        result = await session.execute(
                            select(Run.status).where(Run.id == run_id)
                        )
                        status = result.scalar_one_or_none()
                        if status == "cancelled":
                            logger.info(f"Run {run_id} cancelled by user, setting cancel event")
                            cancel_event.set()
                            return
            except asyncio.CancelledError:
                pass

        flush_task = asyncio.create_task(flush_progress())

        try:
            def _run_pipeline():
                from shortlist.pipeline import run_pipeline_pg
                return run_pipeline_pg(
                    pipeline_config,
                    db_url=sync_db_url,
                    user_id=user_id,
                    on_progress=on_progress,
                    cancel_event=cancel_event,
                )

            result = await asyncio.to_thread(_run_pipeline)

            # Final flush
            flush_task.cancel()
            if progress:
                await update_run(progress=dict(progress))

        except Exception:
            flush_task.cancel()
            raise

        visible = result.get("visible_matches", 0)
        await update_run(
            status="completed",
            finished_at=datetime.now(timezone.utc),
            progress={
                "phase": "done",
                "detail": f"Complete — {visible} matches found",
                "matches": visible,
                "jobs_collected": result.get("jobs_collected", 0),
            },
        )

    except Exception as e:
        from shortlist.pipeline import CancelledError
        if isinstance(e, CancelledError):
            logger.info(f"Run {run_id} cancelled")
        else:
            logger.exception(f"Run {run_id} failed")
            await update_run(
                status="failed",
                finished_at=datetime.now(timezone.utc),
                error=str(e)[:500],
            )
    finally:
        await engine.dispose()
