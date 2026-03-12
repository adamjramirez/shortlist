"""Resume routes — upload, list, delete resumes (.tex or .pdf)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.models import Resume, User
from shortlist.api.schemas import ResumeResponse
from shortlist.api.storage import Storage, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_FILE_SIZE = 1024 * 1024  # 1MB
ALLOWED_EXTENSIONS = (".tex", ".pdf")


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF.

    PyMuPDF handles custom fonts (fontspec/XeLaTeX) much better than
    pdfplumber — preserves word boundaries regardless of font or kerning.
    """
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text()
        if text and text.strip():
            pages.append(text.strip())
    doc.close()
    return "\n\n".join(pages)


def _resume_to_response(r: Resume) -> ResumeResponse:
    return ResumeResponse(
        id=r.id, filename=r.filename, track=r.track,
        resume_type=r.resume_type or "tex",
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
    if not file.filename or not file.filename.endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only .tex and .pdf files accepted")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 1MB limit")

    is_pdf = file.filename.endswith(".pdf")
    s3_key = f"{user.id}/resumes/{file.filename}"
    extracted_text_key = None
    resume_type = "tex"

    if is_pdf:
        resume_type = "pdf"
        try:
            extracted = _extract_pdf_text(data)
        except Exception as e:
            logger.warning(f"PDF text extraction failed for {file.filename}: {e}")
            raise HTTPException(status_code=400, detail="Could not read this PDF. Try a different file.")

        if not extracted or not extracted.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from this PDF. It may be image-based or empty.")

        # Store both the PDF and extracted text
        await storage.put(s3_key, data)
        extracted_text_key = f"{user.id}/resumes/{file.filename}.txt"
        await storage.put(extracted_text_key, extracted.encode("utf-8"))
        logger.info(f"PDF uploaded: {file.filename} → {len(extracted)} chars extracted")
    else:
        await storage.put(s3_key, data)

    resume = Resume(
        user_id=user.id,
        filename=file.filename,
        track=track,
        s3_key=s3_key,
        resume_type=resume_type,
        extracted_text_key=extracted_text_key,
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
