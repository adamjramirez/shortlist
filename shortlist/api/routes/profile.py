"""Profile routes — get/update user profile config."""
from datetime import datetime, timedelta, timezone

import httpx
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
    AutoRunConfig,
    AutoRunUpdate,
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
    "aww_node_id": "",
    "use_aww_slice": True,
}


def _to_auto_run(profile: "Profile | None") -> AutoRunConfig:
    """Build AutoRunConfig from dedicated profile columns."""
    if profile is None:
        return AutoRunConfig()
    return AutoRunConfig(
        enabled=profile.auto_run_enabled,
        interval_h=profile.auto_run_interval_h,
        next_run_at=profile.next_run_at.isoformat() if profile.next_run_at else None,
        consecutive_failures=profile.consecutive_failures,
    )


def _redact_config(config: dict) -> dict:
    """Return config with API keys redacted."""
    out = dict(config)
    llm = dict(out.get("llm", {}))
    if llm.pop("encrypted_api_key", None):
        llm["has_api_key"] = True
    # Redact per-provider keys — just expose which providers have keys
    api_keys = llm.pop("api_keys", {})
    if api_keys:
        llm["providers_with_keys"] = sorted(
            k for k, v in api_keys.items() if v
        )
    out["llm"] = llm
    return out


def _to_response(config: dict, profile: "Profile | None" = None) -> ProfileResponse:
    """Ensure all expected keys exist, redact secrets."""
    merged = {**EMPTY_CONFIG, **config}
    return ProfileResponse(**_redact_config(merged), auto_run=_to_auto_run(profile))


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.profile is None:
        return _to_response({})
    return _to_response(user.profile.config, user.profile)


@router.put("", response_model=ProfileResponse)
async def update_profile(
    req: ProfileUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Start from existing config or empty
    existing = user.profile.config if user.profile else dict(EMPTY_CONFIG)
    updates = req.model_dump(exclude_none=True)

    # Extract auto_run before merging into config JSON (it lives in dedicated columns)
    auto_run_update = updates.pop("auto_run", None)

    # Handle API keys: encrypt if provided, preserve existing if not
    llm_updates = updates.pop("llm", None)
    if llm_updates is not None:
        existing_llm = dict(existing.get("llm", {}))
        existing_api_keys = dict(existing_llm.get("api_keys", {}))

        # Legacy single key (backward compat)
        api_key = llm_updates.pop("api_key", None)
        if api_key:
            from shortlist.llm import detect_provider
            provider = detect_provider(llm_updates.get("model", existing_llm.get("model", "gemini-2.0-flash")))
            existing_api_keys[provider] = encrypt(api_key)
            llm_updates["encrypted_api_key"] = encrypt(api_key)
        elif "encrypted_api_key" in existing_llm:
            llm_updates["encrypted_api_key"] = existing_llm["encrypted_api_key"]

        # Per-provider keys: { "gemini": "sk-...", "anthropic": "sk-..." }
        provider_keys = llm_updates.pop("provider_keys", None)
        if provider_keys:
            for provider, key in provider_keys.items():
                if provider in ("gemini", "openai", "anthropic") and key:
                    existing_api_keys[provider] = encrypt(key)

        llm_updates["api_keys"] = existing_api_keys
        existing["llm"] = llm_updates
    
    # Merge remaining top-level fields
    existing.update(updates)

    if user.profile is None:
        profile = Profile(user_id=user.id, config=existing)
        session.add(profile)
    else:
        profile = user.profile
        user.profile.config = dict(existing)
        flag_modified(user.profile, "config")
        user.profile.updated_at = datetime.now(timezone.utc)

    # Handle auto_run — stored in dedicated columns, not config JSON
    if auto_run_update is not None:
        enabled = auto_run_update.get("enabled")
        # Fall back to existing column value, then model default (12)
        interval_h = auto_run_update.get("interval_h") or profile.auto_run_interval_h or 12

        if enabled is not None:
            profile.auto_run_enabled = enabled
            profile.auto_run_interval_h = interval_h
            if enabled:
                profile.next_run_at = datetime.now(timezone.utc) + timedelta(hours=interval_h)
            else:
                profile.next_run_at = None
                profile.consecutive_failures = 0
        elif "interval_h" in auto_run_update and profile.auto_run_enabled:
            # Interval change only while enabled — recalculate from now
            profile.auto_run_interval_h = interval_h
            profile.next_run_at = datetime.now(timezone.utc) + timedelta(hours=interval_h)

    await session.flush()
    return _to_response(existing, profile)


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

    # Fetch resume content — use extracted text for PDFs
    if resume.resume_type == "pdf" and resume.extracted_text_key:
        resume_bytes = await storage.get(resume.extracted_text_key)
    else:
        resume_bytes = await storage.get(resume.s3_key)
    resume_text = resume_bytes.decode("utf-8", errors="replace")

    try:
        result = await generator.generate_profile(resume_text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Your API key hit rate limits. Wait a minute and try again. "
                    "Tip: Gemini keys have generous free-tier limits \u2014 "
                    "switch to Gemini 2.0 Flash in your profile settings."
                ),
            )
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error ({e.response.status_code}). Try again shortly.",
        )
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
