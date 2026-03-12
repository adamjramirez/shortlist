"""Resume tailoring routes — generate and download tailored resumes."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.crypto import decrypt
from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import Job, Profile, Resume, User
from shortlist.api.storage import Storage, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["tailor"])


class TailorResponse(BaseModel):
    filename: str
    changes_made: list[str]
    interest_note: str


async def _get_user_job(job_id: int, user: User, session: AsyncSession) -> Job:
    """Fetch a job, verify ownership."""
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _get_best_resume(user: User, matched_track: str | None,
                           session: AsyncSession, storage: Storage) -> tuple[str, str]:
    """Pick best resume by track, download tex content. Returns (tex, filename)."""
    query = select(Resume).where(Resume.user_id == user.id)
    if matched_track:
        # Try track-specific first
        result = await session.execute(
            query.where(Resume.track == matched_track).order_by(Resume.uploaded_at.desc())
        )
        resume = result.scalar_one_or_none()
        if resume:
            data = await storage.get(resume.s3_key)
            return data.decode("utf-8"), resume.filename

    # Fallback: any resume
    result = await session.execute(
        query.order_by(Resume.uploaded_at.desc())
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=400, detail="No resumes uploaded. Upload a .tex resume first.")
    data = await storage.get(resume.s3_key)
    return data.decode("utf-8"), resume.filename


@router.post("/{job_id}/tailor", response_model=TailorResponse)
async def tailor_job(
    job_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    """Generate a tailored resume for a specific job."""
    job = await _get_user_job(job_id, user, session)

    # Already tailored — return existing
    if job.tailored_resume_key:
        return TailorResponse(
            filename=f"tailored-{job.company.lower().replace(' ', '-')}.tex",
            changes_made=[],
            interest_note="",
        )

    resume_tex, _ = await _get_best_resume(user, job.matched_track, session, storage)

    # Configure LLM with user's API key
    result = await session.execute(
        select(Profile).where(Profile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not profile.config:
        raise HTTPException(status_code=400, detail="Profile not configured")

    config = profile.config
    encrypted_key = config.get("llm", {}).get("encrypted_api_key", "")
    if not encrypted_key:
        raise HTTPException(status_code=400, detail="No API key configured. Set one in your profile.")

    import os
    from shortlist import llm as llm_module

    api_key = decrypt(encrypted_key)
    model = config.get("llm", {}).get("model", "gemini-2.0-flash")
    provider = llm_module.detect_provider(model)
    env_key = llm_module._ENV_KEYS[provider]
    os.environ[env_key] = api_key
    llm_module.configure(model)

    # Run LLM tailoring in thread to avoid blocking
    from shortlist.processors.resume import tailor_resume_from_text

    tailored = await asyncio.to_thread(
        tailor_resume_from_text,
        resume_tex, job.title, job.company, job.description or "",
    )
    if not tailored:
        raise HTTPException(status_code=500, detail="Resume tailoring failed. Try again.")

    # Store in Tigris
    s3_key = f"{user.id}/tailored/{job_id}.tex"
    await storage.put(s3_key, tailored.tailored_tex.encode("utf-8"))

    # Update job
    job.tailored_resume_key = s3_key
    await session.commit()

    return TailorResponse(
        filename=f"tailored-{job.company.lower().replace(' ', '-')}.tex",
        changes_made=tailored.changes_made,
        interest_note=tailored.interest_note,
    )


@router.get("/{job_id}/resume")
async def download_resume(
    job_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    """Download a tailored resume .tex file."""
    job = await _get_user_job(job_id, user, session)

    if not job.tailored_resume_key:
        raise HTTPException(status_code=404, detail="No tailored resume. Generate one first.")

    data = await storage.get(job.tailored_resume_key)
    safe_company = job.company.lower().replace(" ", "-")
    filename = f"tailored-{safe_company}.tex"

    return Response(
        content=data,
        media_type="application/x-tex",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
