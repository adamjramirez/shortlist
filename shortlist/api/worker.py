"""In-process pipeline worker.

Runs the existing sync pipeline in a background thread, then copies
results from the temp SQLite DB to PostgreSQL.
"""
import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from shortlist.api.crypto import decrypt
from shortlist.api.models import Run, Job, Company

logger = logging.getLogger(__name__)


async def execute_run(run_id: int, user_id: int, config: dict, db_url: str) -> None:
    """Execute a pipeline run in background.

    1. Build a Config from the user's profile
    2. Run the sync pipeline in a thread (temp SQLite)
    3. Copy results to PostgreSQL
    4. Update run status
    """
    from shortlist.api.db import _clean_url, _get_connect_args

    clean_url = _clean_url(db_url)
    engine = create_async_engine(
        clean_url,
        connect_args=_get_connect_args(clean_url),
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
                model=config.get("llm", {}).get("model", "gemini-2.5-flash"),
                max_jobs_per_run=50,
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

        # Shared progress dict — sync thread writes, async flush loop reads
        progress = {}
        import time
        run_start_time = time.monotonic()

        # Phase timing: based on observed runs
        # HN ~10s, LinkedIn ~45s (rate-limited detail fetches), NextPlay ~10s
        # Filter ~2s, Score ~60s (50 jobs, 10 parallel), Enrich ~40s, Tailor ~25s, Brief ~5s
        # Total typical run: 3-4 minutes
        PHASE_ORDER = ["collecting", "filtering", "fetching", "scoring", "enriching", "tailoring", "finishing"]
        PHASE_SECONDS = {
            "collecting": 30,   # fast now — no LinkedIn descriptions
            "filtering": 5,
            "fetching": 60,     # LinkedIn descriptions for ~30 filtered jobs
            "scoring": 60,
            "enriching": 40,
            "tailoring": 25,
            "finishing": 5,
        }

        def on_progress(data: dict):
            phase = data.get("phase", progress.get("phase", "collecting"))
            elapsed = time.monotonic() - run_start_time

            # Sum remaining phase durations
            if phase in PHASE_ORDER:
                idx = PHASE_ORDER.index(phase)
                remaining_phases = PHASE_ORDER[idx + 1:]
                remaining = sum(PHASE_SECONDS.get(p, 0) for p in remaining_phases)

                # Current phase: use scored/total ratio if scoring, else half
                current_est = PHASE_SECONDS.get(phase, 10)
                scored = data.get("scored")
                total = data.get("total")
                if phase == "scoring" and scored is not None and total and total > 0:
                    remaining += current_est * (1 - scored / total)
                else:
                    remaining += current_est * 0.5

                data["eta_seconds"] = max(0, int(remaining))
            else:
                data["eta_seconds"] = 0

            data["elapsed_seconds"] = int(elapsed)
            progress.update(data)

        async def flush_progress():
            """Push progress to DB every 2s while pipeline runs."""
            try:
                while True:
                    await asyncio.sleep(2)
                    if progress:
                        await update_run(progress=dict(progress))
            except asyncio.CancelledError:
                pass

        flush_task = asyncio.create_task(flush_progress())

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                project_root = Path(tmpdir)

                def _run_pipeline():
                    from shortlist.pipeline import run_pipeline
                    return run_pipeline(pipeline_config, project_root, on_progress=on_progress)

                brief_path = await asyncio.to_thread(_run_pipeline)

                # Final flush before saving results
                flush_task.cancel()
                if progress:
                    await update_run(progress=dict(progress))

                await update_run(progress={"phase": "saving results", "detail": "Saving results to database…"})

                # Copy results from SQLite to PostgreSQL
                import sqlite3
                sqlite_db = sqlite3.connect(str(project_root / "jobs.db"))
                sqlite_db.row_factory = sqlite3.Row

                jobs = sqlite_db.execute(
                    "SELECT * FROM jobs WHERE status IN ('scored', 'low_score', 'filtered', 'rejected')"
                ).fetchall()

                async with async_session() as session:
                    for row in jobs:
                        existing = await session.execute(
                            select(Job).where(
                                Job.user_id == user_id,
                                Job.description_hash == row["description_hash"],
                            )
                        )
                        existing_job = existing.scalar_one_or_none()

                        if existing_job:
                            if row["fit_score"] is not None:
                                existing_job.fit_score = row["fit_score"]
                                existing_job.score_reasoning = row["score_reasoning"]
                                existing_job.yellow_flags = row["yellow_flags"]
                                existing_job.salary_estimate = row["salary_estimate"]
                                existing_job.salary_confidence = row["salary_confidence"]
                                existing_job.matched_track = row["matched_track"]
                            if row["enrichment"]:
                                existing_job.enrichment = json.loads(row["enrichment"]) if isinstance(row["enrichment"], str) else row["enrichment"]
                            existing_job.last_seen = datetime.now(timezone.utc)
                            existing_job.status = row["status"]
                        else:
                            sources = json.loads(row["sources_seen"]) if row["sources_seen"] else []
                            job = Job(
                                user_id=user_id,
                                title=row["title"],
                                company=row["company"],
                                location=row["location"],
                                url=row["url"],
                                description=row["description"],
                                description_hash=row["description_hash"],
                                salary_text=row["salary_text"],
                                sources_seen=sources,
                                status=row["status"],
                                reject_reason=row["reject_reason"],
                                fit_score=row["fit_score"],
                                matched_track=row["matched_track"],
                                score_reasoning=row["score_reasoning"],
                                yellow_flags=row["yellow_flags"],
                                salary_estimate=row["salary_estimate"],
                                salary_confidence=row["salary_confidence"],
                                enrichment=json.loads(row["enrichment"]) if row["enrichment"] else None,
                            )
                            session.add(job)

                    await session.commit()

                scored_count = len([j for j in jobs if j["fit_score"] and j["fit_score"] >= 60])
                sqlite_db.close()

        except Exception:
            flush_task.cancel()
            raise

        await update_run(
            status="completed",
            finished_at=datetime.now(timezone.utc),
            progress={
                "phase": "done",
                "detail": f"Complete — {scored_count} matches found",
                "jobs_found": len(jobs),
                "scored": scored_count,
            },
        )

    except Exception as e:
        logger.exception(f"Run {run_id} failed")
        await update_run(
            status="failed",
            finished_at=datetime.now(timezone.utc),
            error=str(e)[:500],
        )
    finally:
        await engine.dispose()
