"""Pipeline run routes — create, list, get status."""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.machines import MachineSpawner, get_machine_spawner
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
    spawner: MachineSpawner = Depends(get_machine_spawner),
):
    # Require profile
    if user.profile is None or not user.profile.config.get("fit_context"):
        raise HTTPException(status_code=400, detail="Set up your profile before running")

    # One active run at a time
    result = await session.execute(
        select(Run).where(Run.user_id == user.id, Run.status.in_(ACTIVE_STATUSES))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A run is already in progress")

    run = Run(user_id=user.id, status="pending")
    session.add(run)
    await session.flush()

    # Build env for the worker machine
    worker_env = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        "ENCRYPTION_KEY": os.environ.get("ENCRYPTION_KEY", ""),
    }

    machine_id = await spawner.spawn(run.id, worker_env)
    if machine_id:
        run.machine_id = machine_id
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
    else:
        run.status = "failed"
        run.error = "Failed to spawn worker machine"

    await session.flush()
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
