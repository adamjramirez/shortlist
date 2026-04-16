"""Jobs routes — list, detail, status update, view tracking."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import Job, Run, User
from shortlist.api.schemas import (
    JobDetail,
    JobListResponse,
    JobStatusUpdate,
    JobSummary,
)
from shortlist.config import SCORE_VISIBLE
from shortlist.processors.filter import is_listed_salary

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _is_job_board(company: str) -> bool:
    """Check if company is a recruiter/aggregator."""
    from shortlist.processors.enricher import is_job_board
    return is_job_board(company)


def _enrichment_summary(enrichment: dict | None) -> str | None:
    """One-line company intel from enrichment dict. Every field labeled."""
    if not enrichment:
        return None
    parts = []
    stage = enrichment.get("stage")
    if stage and stage != "unknown":
        parts.append(f"Stage: {stage}")
    hc = enrichment.get("headcount_estimate")
    if hc:
        parts.append(f"~{hc} people")
    gr = enrichment.get("glassdoor_rating")
    if gr:
        parts.append(f"Glassdoor {gr}/5")
    gs = enrichment.get("growth_signal")
    if gs and gs != "unknown":
        parts.append(f"Growth: {gs}")
    oss = enrichment.get("oss_presence")
    if oss and oss not in ("unknown", "weak"):
        parts.append(f"OSS: {oss}")
    return " · ".join(parts) if parts else None


async def _get_latest_run_id(session: AsyncSession, user_id: int) -> int | None:
    """Get the latest non-failed/cancelled run ID for a user."""
    result = await session.execute(
        select(func.max(Run.id)).where(
            Run.user_id == user_id,
            Run.status.not_in(["failed", "cancelled"]),
        )
    )
    return result.scalar()


def _job_to_summary(job: Job, latest_run_id: int | None = None) -> JobSummary:
    return JobSummary(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        fit_score=job.fit_score,
        matched_track=job.matched_track,
        salary_estimate=job.salary_estimate,
        url=job.url,
        status=job.status,
        user_status=job.user_status,
        sources_seen=job.sources_seen or [],
        first_seen=job.first_seen.isoformat() if job.first_seen else None,
        posted_at=job.posted_at.isoformat() if job.posted_at else None,
        has_tailored_resume=bool(job.tailored_resume_key),
        has_tailored_pdf=bool(job.tailored_resume_pdf_key),
        is_new=(latest_run_id is not None and job.run_id == latest_run_id),
        is_closed=bool(job.is_closed),
        closed_reason=job.closed_reason,
        prestige_tier=job.prestige_tier,
        viewed_at=job.viewed_at.isoformat() if job.viewed_at else None,
        company_intel=(f"⚠️ Posted by {job.company} (recruiter/job board). The actual hiring company isn't listed — no company intel available."
                       if _is_job_board(job.company)
                       else _enrichment_summary(job.enrichment)),
        score_reasoning=_clean_reasoning(job.score_reasoning),
        salary_text=job.salary_text,
        salary_confidence=job.salary_confidence,
        salary_listed=is_listed_salary(job.salary_text),
        salary_basis=job.salary_basis,
    )


def _clean_reasoning(text: str | None) -> str | None:
    """Strip internal [Re-scored: ...] annotations from reasoning."""
    if not text:
        return text
    import re
    return re.sub(r"\s*\[Re-scored:.*?\]", "", text).strip()


def _job_to_detail(job: Job, latest_run_id: int | None = None) -> JobDetail:
    summary = _job_to_summary(job, latest_run_id).model_dump()
    return JobDetail(
        **summary,
        description=job.description,
        yellow_flags=job.yellow_flags,
        enrichment=job.enrichment,
        interest_note=job.interest_note,
        career_page_url=job.career_page_url,
        cover_letter=job.cover_letter,
        notes=job.notes,
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    min_score: int | None = Query(None),
    track: str | None = Query(None),
    user_status: str | None = Query(None),
    prestige: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    # Build filters once, apply to both count and data queries
    filters = [Job.user_id == user.id]
    # Enforce minimum visible score — lower scores stored but not exposed
    effective_min = max(min_score or SCORE_VISIBLE, SCORE_VISIBLE)
    filters.append(Job.fit_score >= effective_min)
    if track:
        filters.append(Job.matched_track == track)
    if prestige:
        filters.append(Job.prestige_tier == prestige.upper())
    if user_status == "new":
        filters.append(Job.user_status.is_(None))
        filters.append(Job.is_closed == False)  # noqa: E712
    elif user_status in ("saved", "applied"):
        filters.append(Job.user_status == user_status)
        # Keep closed jobs in saved/applied — user may have applied before it closed
    elif user_status:
        filters.append(Job.user_status == user_status)
        filters.append(Job.is_closed == False)  # noqa: E712
    else:
        # Default (no user_status filter) — hide closed from main view
        filters.append(Job.is_closed == False)  # noqa: E712

    total = (await session.execute(
        select(func.count()).select_from(Job).where(*filters)
    )).scalar() or 0

    # Counts by status (unfiltered by user_status, but respecting score/track)
    base_filters = [Job.user_id == user.id, Job.fit_score >= effective_min]
    if track:
        base_filters.append(Job.matched_track == track)
    count_result = await session.execute(
        select(
            func.count().filter(Job.user_status.is_(None), Job.is_closed == False).label("new"),  # noqa: E712
            func.count().filter(Job.user_status == "saved").label("saved"),
            func.count().filter(Job.user_status == "applied").label("applied"),
            func.count().filter(Job.user_status == "skipped").label("skipped"),
        ).select_from(Job).where(*base_filters)
    )
    row = count_result.one()
    counts = {"new": row.new, "saved": row.saved, "applied": row.applied, "skipped": row.skipped}

    offset = (page - 1) * per_page
    result = await session.execute(
        select(Job)
        .where(*filters)
        .order_by(Job.fit_score.desc().nulls_last())
        .offset(offset)
        .limit(per_page)
    )
    latest_run_id = await _get_latest_run_id(session, user.id)
    jobs = [_job_to_summary(j, latest_run_id) for j in result.scalars().all()]

    return JobListResponse(jobs=jobs, total=total, page=page, per_page=per_page, counts=counts)


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(
    job_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    latest_run_id = await _get_latest_run_id(session, user.id)
    return _job_to_detail(job, latest_run_id)


@router.put("/{job_id}/status", response_model=JobDetail)
async def update_job_status(
    job_id: int,
    req: JobStatusUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if req.status == "closed":
        job.is_closed = not job.is_closed
        if job.is_closed:
            job.closed_reason = "user"
            job.closed_at = datetime.now(timezone.utc)
        else:
            job.closed_reason = None
            job.closed_at = None
    elif req.status == "clear":
        job.user_status = None
    else:
        job.user_status = req.status
    await session.flush()
    latest_run_id = await _get_latest_run_id(session, user.id)
    return _job_to_detail(job, latest_run_id)


@router.patch("/{job_id}/view", status_code=204)
async def mark_job_viewed(
    job_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Mark a job as viewed. Idempotent — only sets viewed_at on first call."""
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.viewed_at:
        job.viewed_at = datetime.now(timezone.utc)
        await session.flush()
