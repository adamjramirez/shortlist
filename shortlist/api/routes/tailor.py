"""Resume tailoring + cover letter routes."""
import asyncio
import logging
import os

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


# --- Shared helpers ---

async def _get_user_job(job_id: int, user: User, session: AsyncSession) -> Job:
    """Fetch a job, verify ownership."""
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _configure_llm(user: User, session: AsyncSession,
                         model_override: str | None = None) -> str:
    """Configure LLM from user's profile. Returns model name.

    If model_override is given, uses that model and looks up the
    matching provider key from api_keys.
    """
    result = await session.execute(
        select(Profile).where(Profile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not profile.config:
        raise HTTPException(status_code=400, detail="Profile not configured")

    from shortlist import llm as llm_module

    llm_config = profile.config.get("llm", {})
    model = model_override or llm_config.get("model", "gemini-2.0-flash")
    provider = llm_module.detect_provider(model)

    # Try per-provider key first, fall back to legacy single key
    api_keys = llm_config.get("api_keys", {})
    encrypted_key = api_keys.get(provider) or llm_config.get("encrypted_api_key", "")

    if not encrypted_key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key for {provider}. Add one in your Profile settings.",
        )

    api_key = decrypt(encrypted_key)
    env_key = llm_module._ENV_KEYS[provider]
    os.environ[env_key] = api_key
    llm_module.configure(model)
    return model


async def _pick_best_resume(user: User, matched_track: str | None,
                            session: AsyncSession) -> Resume:
    """Select the best resume by track match, then recency. Returns Resume model."""
    query = select(Resume).where(Resume.user_id == user.id)

    # Try track match first
    if matched_track:
        result = await session.execute(
            query.where(Resume.track == matched_track).order_by(Resume.uploaded_at.desc())
        )
        resume = result.scalars().first()
        if resume:
            logger.info(f"Picked resume by track '{matched_track}': {resume.filename} ({resume.id})")
            return resume

    # Fallback: most recent resume
    result = await session.execute(
        query.order_by(Resume.uploaded_at.desc())
    )
    resume = result.scalars().first()
    if not resume:
        raise HTTPException(status_code=400, detail="No resumes uploaded. Upload a resume first.")
    logger.info(f"Picked most recent resume: {resume.filename} ({resume.id})")
    return resume


async def _fetch_resume_text(resume: Resume, storage: Storage) -> tuple[str, str, str]:
    """Fetch resume text content from storage. Returns (text, filename, resume_type).

    For PDF resumes, fetches extracted text. For .tex, fetches raw content.
    """
    if resume.resume_type == "pdf" and resume.extracted_text_key:
        data = await storage.get(resume.extracted_text_key)
        return data.decode("utf-8"), resume.filename, "pdf"
    else:
        data = await storage.get(resume.s3_key)
        return data.decode("utf-8"), resume.filename, resume.resume_type or "tex"


# --- Resume tailoring ---

class TailorResponse(BaseModel):
    filename: str
    changes_made: list[str]
    interest_note: str


@router.post("/{job_id}/tailor", response_model=TailorResponse)
async def tailor_job(
    job_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    """Generate a tailored resume for a specific job."""
    job = await _get_user_job(job_id, user, session)

    if job.tailored_resume_key:
        safe_company = job.company.lower().replace(' ', '-')
        ext = "pdf" if job.tailored_resume_pdf_key else "tex"
        return TailorResponse(
            filename=f"tailored-{safe_company}.{ext}",
            changes_made=[],
            interest_note="",
        )

    resume = await _pick_best_resume(user, job.matched_track, session)
    resume_text, _, resume_type = await _fetch_resume_text(resume, storage)
    await _configure_llm(user, session)

    if resume_type == "pdf":
        from shortlist.processors.resume import generate_resume_from_text
        tailored = await asyncio.to_thread(
            generate_resume_from_text,
            resume_text, job.title, job.company, job.description or "",
        )
    else:
        from shortlist.processors.resume import tailor_resume_from_text
        tailored = await asyncio.to_thread(
            tailor_resume_from_text,
            resume_text, job.title, job.company, job.description or "",
        )

    if not tailored:
        raise HTTPException(status_code=500, detail="Resume tailoring failed. Try again.")

    # Store .tex
    s3_key = f"{user.id}/tailored/{job_id}.tex"
    await storage.put(s3_key, tailored.tailored_tex.encode("utf-8"))
    job.tailored_resume_key = s3_key

    # For PDF users, attempt LaTeX → PDF compilation
    if resume_type == "pdf":
        from shortlist.processors.latex_compiler import compile_latex
        pdf_bytes = await asyncio.to_thread(compile_latex, tailored.tailored_tex)
        if pdf_bytes:
            pdf_key = f"{user.id}/tailored/{job_id}.pdf"
            await storage.put(pdf_key, pdf_bytes)
            job.tailored_resume_pdf_key = pdf_key
            logger.info(f"PDF compiled for job {job_id}: {len(pdf_bytes)} bytes")
        else:
            logger.warning(f"PDF compilation failed for job {job_id}, .tex still available")

    await session.commit()

    safe_company = job.company.lower().replace(' ', '-')
    ext = "pdf" if job.tailored_resume_pdf_key else "tex"
    return TailorResponse(
        filename=f"tailored-{safe_company}.{ext}",
        changes_made=tailored.changes_made,
        interest_note=tailored.interest_note,
    )


@router.get("/{job_id}/resume")
async def download_resume(
    job_id: int,
    format: str = "pdf",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    """Download a tailored resume. Serves PDF when available (default), or .tex source."""
    job = await _get_user_job(job_id, user, session)

    if not job.tailored_resume_key:
        raise HTTPException(status_code=404, detail="No tailored resume. Generate one first.")

    safe_company = job.company.lower().replace(" ", "-")

    # Serve PDF if requested and available
    if format == "pdf" and job.tailored_resume_pdf_key:
        data = await storage.get(job.tailored_resume_pdf_key)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="tailored-{safe_company}.pdf"'},
        )

    # Serve .tex (default for LaTeX users, fallback for PDF users)
    data = await storage.get(job.tailored_resume_key)
    return Response(
        content=data,
        media_type="application/x-tex",
        headers={"Content-Disposition": f'attachment; filename="tailored-{safe_company}.tex"'},
    )


# --- Cover letter ---

class CoverLetterResponse(BaseModel):
    cover_letter: str
    model_used: str


class CoverLetterRequest(BaseModel):
    model: str | None = None  # Override model (must have key for that provider)
    regenerate: bool = False  # Force regeneration even if cached


@router.post("/{job_id}/cover-letter", response_model=CoverLetterResponse)
async def generate_cover_letter_endpoint(
    job_id: int,
    body: CoverLetterRequest | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    """Generate a tailored cover letter for a specific job."""
    job = await _get_user_job(job_id, user, session)
    model_choice = body.model if body else None
    regenerate = body.regenerate if body else False

    # Return cached if exists and not regenerating
    if job.cover_letter and not regenerate:
        result = await session.execute(
            select(Profile).where(Profile.user_id == user.id)
        )
        profile = result.scalar_one_or_none()
        model = (profile.config or {}).get("llm", {}).get("model", "gemini-2.0-flash") if profile else "unknown"
        return CoverLetterResponse(cover_letter=job.cover_letter, model_used=model)

    model = await _configure_llm(user, session, model_override=model_choice)

    # Gather all context
    resume_text = ""
    try:
        resume = await _pick_best_resume(user, job.matched_track, session)
        resume_text, _, _ = await _fetch_resume_text(resume, storage)
    except HTTPException:
        pass  # No resume is OK for cover letters — we still have fit_context

    # Get fit_context from profile
    result = await session.execute(
        select(Profile).where(Profile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    fit_context = (profile.config or {}).get("fit_context", "") if profile else ""

    # Build company intel string from enrichment
    company_intel = ""
    if job.enrichment:
        e = job.enrichment
        parts = []
        if e.get("stage") and e["stage"] != "unknown":
            parts.append(f"Stage: {e['stage']}")
        if e.get("headcount_estimate"):
            parts.append(f"~{e['headcount_estimate']} people")
        if e.get("glassdoor_rating"):
            parts.append(f"Glassdoor: {e['glassdoor_rating']}")
        if e.get("growth_signal") and e["growth_signal"] != "unknown":
            parts.append(f"Growth: {e['growth_signal']}")
        if e.get("tech_stack"):
            stack = e["tech_stack"] if isinstance(e["tech_stack"], list) else [e["tech_stack"]]
            parts.append(f"Tech: {', '.join(stack)}")
        if e.get("domain_description") and e["domain_description"] != "unknown":
            parts.append(f"Domain: {e['domain_description']}")
        company_intel = " | ".join(parts)

    from shortlist.processors.cover_letter import generate_cover_letter

    letter = await asyncio.to_thread(
        generate_cover_letter,
        title=job.title,
        company=job.company,
        description=job.description or "",
        fit_context=fit_context,
        resume_tex=resume_text,
        company_intel=company_intel,
        match_reasoning=job.score_reasoning or "",
        interest_note=job.interest_note or "",
    )
    if not letter:
        raise HTTPException(status_code=500, detail="Cover letter generation failed. Try again.")

    job.cover_letter = letter
    await session.commit()

    return CoverLetterResponse(cover_letter=letter, model_used=model)
