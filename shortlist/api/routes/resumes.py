"""Resume routes — upload, list, delete LaTeX resumes."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import Resume, User
from shortlist.api.schemas import ResumeResponse
from shortlist.api.storage import Storage, get_storage

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_FILE_SIZE = 1024 * 1024  # 1MB


def _resume_to_response(r: Resume) -> ResumeResponse:
    return ResumeResponse(
        id=r.id, filename=r.filename, track=r.track,
        uploaded_at=r.uploaded_at.isoformat(),
    )


@router.post("", response_model=ResumeResponse, status_code=201)
async def upload_resume(
    file: UploadFile,
    track: str | None = Form(None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    if not file.filename or not file.filename.endswith(".tex"):
        raise HTTPException(status_code=400, detail="Only .tex files accepted")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 1MB limit")

    s3_key = f"{user.id}/resumes/{file.filename}"
    await storage.put(s3_key, data)

    resume = Resume(
        user_id=user.id,
        filename=file.filename,
        track=track,
        s3_key=s3_key,
    )
    session.add(resume)
    await session.flush()

    return _resume_to_response(resume)


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.uploaded_at.desc())
    )
    resumes = result.scalars().all()
    return [_resume_to_response(r) for r in resumes]


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    result = await session.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    await storage.delete(resume.s3_key)
    await session.delete(resume)
