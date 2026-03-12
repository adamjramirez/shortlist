"""Jobs routes — list, detail, status update."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import Job, User
from shortlist.api.schemas import (
    JobDetail,
    JobListResponse,
    JobStatusUpdate,
    JobSummary,
)
from shortlist.config import SCORE_VISIBLE

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _is_job_board(company: str) -> bool:
    """Check if company is a recruiter/aggregator."""
    from shortlist.processors.enricher import is_job_board
    return is_job_board(company)


def _enrichment_summary(enrichment: dict | None) -> str | None:
    """One-line company intel from enrichment dict."""
    if not enrichment:
        return None
    parts = []
    if enrichment.get("stage") and enrichment["stage"] != "unknown":
        parts.append(enrichment["stage"])
    hc = enrichment.get("headcount_estimate")
    if hc:
        parts.append(f"~{hc} people")
    gr = enrichment.get("glassdoor_rating")
    if gr:
        parts.append(f"Glassdoor {gr}")
    gs = enrichment.get("growth_signal")
    if gs and gs != "unknown":
        parts.append(gs)
    oss = enrichment.get("oss_presence")
    if oss and oss not in ("unknown", "weak"):
        parts.append(f"OSS: {oss}")
    return " · ".join(parts) if parts else None


def _job_to_summary(job: Job) -> JobSummary:
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
        has_tailored_resume=bool(job.tailored_resume_key),
        is_new=(job.brief_count or 0) == 0,
        company_intel=(f"⚠️ Posted by {job.company} (recruiter/job board). The actual hiring company isn't listed — no company intel available."
                       if _is_job_board(job.company)
                       else _enrichment_summary(job.enrichment)),
    )


def _clean_reasoning(text: str | None) -> str | None:
    """Strip internal [Re-scored: ...] annotations from reasoning."""
    if not text:
        return text
    import re
    return re.sub(r"\s*\[Re-scored:.*?\]", "", text).strip()


def _job_to_detail(job: Job) -> JobDetail:
    summary = _job_to_summary(job).model_dump()
    return JobDetail(
        **summary,
        description=job.description,
        score_reasoning=_clean_reasoning(job.score_reasoning),
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
    if user_status:
        filters.append(Job.user_status == user_status)

    total = (await session.execute(
        select(func.count()).select_from(Job).where(*filters)
    )).scalar() or 0

    offset = (page - 1) * per_page
    result = await session.execute(
        select(Job)
        .where(*filters)
        .order_by(Job.fit_score.desc().nulls_last())
        .offset(offset)
        .limit(per_page)
    )
    jobs = [_job_to_summary(j) for j in result.scalars().all()]

    return JobListResponse(jobs=jobs, total=total, page=page, per_page=per_page)


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
    return _job_to_detail(job)


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

    job.user_status = req.status
    await session.flush()
    return _job_to_detail(job)
