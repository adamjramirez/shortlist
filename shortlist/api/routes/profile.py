"""Profile routes — get/update user profile config."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from shortlist.api.crypto import decrypt, encrypt
from shortlist.api.db import get_session
from shortlist.api.deps import get_current_user
from shortlist.api.llm_client import LLMProfileGenerator, ProfileGenerator
from shortlist.api.models import Profile, Resume, User
from shortlist.api.schemas import (
    GenerateProfileRequest,
    GenerateProfileResponse,
    ProfileResponse,
    ProfileUpdate,
)
from shortlist.api.storage import Storage, get_storage

router = APIRouter(prefix="/api/profile", tags=["profile"])


def get_profile_generator() -> ProfileGenerator | None:
    """Dependency — override in tests with FakeProfileGenerator."""
    return None  # Sentinel: route constructs real one from user's credentials

EMPTY_CONFIG = {
    "fit_context": "",
    "tracks": {},
    "filters": {},
    "preferences": {},
    "llm": {},
    "brief": {},
    "substack_sid": "",
}


def _redact_config(config: dict) -> dict:
    """Return config with API keys redacted."""
    out = dict(config)
    llm = dict(out.get("llm", {}))
    if llm.pop("encrypted_api_key", None):
        llm["has_api_key"] = True
    out["llm"] = llm
    return out


def _to_response(config: dict) -> ProfileResponse:
    """Ensure all expected keys exist, redact secrets."""
    merged = {**EMPTY_CONFIG, **config}
    return ProfileResponse(**_redact_config(merged))


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.profile is None:
        return _to_response({})
    return _to_response(user.profile.config)


@router.put("", response_model=ProfileResponse)
async def update_profile(
    req: ProfileUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Start from existing config or empty
    existing = user.profile.config if user.profile else dict(EMPTY_CONFIG)
    updates = req.model_dump(exclude_none=True)

    # Handle API key: encrypt if provided, preserve existing if not
    llm_updates = updates.pop("llm", None)
    if llm_updates is not None:
        existing_llm = dict(existing.get("llm", {}))
        api_key = llm_updates.pop("api_key", None)
        if api_key:
            llm_updates["encrypted_api_key"] = encrypt(api_key)
        elif "encrypted_api_key" in existing_llm:
            # Preserve existing encrypted key if no new one provided
            llm_updates["encrypted_api_key"] = existing_llm["encrypted_api_key"]
        existing["llm"] = llm_updates
    
    # Merge remaining top-level fields
    existing.update(updates)

    if user.profile is None:
        profile = Profile(user_id=user.id, config=existing)
        session.add(profile)
    else:
        user.profile.config = dict(existing)
        flag_modified(user.profile, "config")
        user.profile.updated_at = datetime.now(timezone.utc)

    await session.flush()
    return _to_response(existing)


@router.post("/generate", response_model=GenerateProfileResponse)
async def generate_profile(
    req: GenerateProfileRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
    generator: ProfileGenerator | None = Depends(get_profile_generator),
):
    """Analyze a resume with AI and return suggested profile fields.

    Does NOT save — user reviews suggestions first.
    """
    # Verify resume exists and belongs to user
    result = await session.execute(
        select(Resume).where(Resume.id == req.resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Get user's LLM config
    config = user.profile.config if user.profile else {}
    llm_config = config.get("llm", {})
    encrypted_key = llm_config.get("encrypted_api_key")
    model = llm_config.get("model", "gemini-2.0-flash")

    if not encrypted_key and generator is None:
        raise HTTPException(
            status_code=400,
            detail="Set up your AI provider and API key first",
        )

    # Use injected generator (tests) or build real one
    if generator is None:
        api_key = decrypt(encrypted_key)
        generator = LLMProfileGenerator(model=model, api_key=api_key)

    # Fetch resume content
    resume_bytes = await storage.get(resume.s3_key)
    resume_text = resume_bytes.decode("utf-8", errors="replace")

    try:
        result = await generator.generate_profile(resume_text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {str(e)}",
        )

    return GenerateProfileResponse(
        fit_context=result.get("fit_context", ""),
        tracks=result.get("tracks", {}),
        filters=result.get("filters", {}),
    )
