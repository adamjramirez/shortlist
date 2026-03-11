"""Pipeline run routes — create, list, get status."""
import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import Run, User
from shortlist.api.schemas import RunResponse

router = APIRouter(prefix="/api/runs", tags=["runs"])

ACTIVE_STATUSES = ("pending", "running")


def _run_to_response(run: Run) -> RunResponse:
    return RunResponse(
        id=run.id,
        status=run.status,
        progress=run.progress or {},
        error=run.error,
        machine_id=run.machine_id,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        created_at=run.created_at.isoformat(),
    )


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Require profile with fit_context and API key
    if user.profile is None:
        raise HTTPException(status_code=400, detail="Set up your profile before running")

    config = user.profile.config or {}
    if not config.get("fit_context"):
        raise HTTPException(status_code=400, detail="Add a description of what you're looking for first")

    if not config.get("llm", {}).get("encrypted_api_key"):
        raise HTTPException(status_code=400, detail="Connect your AI provider first")

    if not config.get("tracks"):
        raise HTTPException(status_code=400, detail="Add at least one role to search for")

    # One active run at a time
    result = await session.execute(
        select(Run).where(Run.user_id == user.id, Run.status.in_(ACTIVE_STATUSES))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A run is already in progress")

    run = Run(user_id=user.id, status="pending")
    session.add(run)
    await session.flush()

    # Launch background worker
    db_url = os.environ.get("DATABASE_URL", "")
    from shortlist.api import worker

    asyncio.create_task(
        worker.execute_run(
            run_id=run.id,
            user_id=user.id,
            config=dict(config),
            db_url=db_url,
        )
    )

    return _run_to_response(run)


@router.get("", response_model=list[RunResponse])
async def list_runs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Run)
        .where(Run.user_id == user.id)
        .order_by(Run.created_at.desc())
        .limit(20)
    )
    return [_run_to_response(r) for r in result.scalars().all()]


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Run).where(Run.id == run_id, Run.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Run is not active")

    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    run.error = "Cancelled by user"
    await session.flush()
    return _run_to_response(run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Run).where(Run.id == run_id, Run.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_response(run)
