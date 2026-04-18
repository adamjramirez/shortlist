"""Sentry telemetry helpers.

All calls are safe to make unconditionally:
- If SENTRY_DSN is unset, init_sentry() is a no-op.
- If sentry-sdk isn't installed, the import-guard makes everything a no-op.
- No helper ever raises — telemetry must not break the error path it's monitoring.

Use this module for all Sentry interaction. Do not import sentry_sdk in routes.
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def init_sentry() -> bool:
    """Initialise Sentry if SENTRY_DSN is set.

    Call before any route modules are imported so the FastAPI auto-integration
    hooks land before route handlers are registered. Returns True on success,
    False if skipped (no DSN / missing sdk / init error).
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed — skipping init")
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            # Errors-only: exception triage, not APM. Keeps event count under
            # the free-tier 5k/mo quota.
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            send_default_pii=True,  # captures identified user email + request URL
            environment=_environment(),
            release=os.environ.get("FLY_MACHINE_VERSION") or os.environ.get("GIT_COMMIT"),
        )
        logger.info("Sentry enabled (env=%s)", _environment())
        return True
    except Exception as e:
        logger.warning("Sentry init failed: %s", e)
        return False


def _environment() -> str:
    return "production" if os.environ.get("FLY_APP_NAME") else "local"


def _llm_provider(model: str | None) -> str:
    if not model:
        return "unknown"
    if "gemini" in model:
        return "gemini"
    if "gpt" in model or "openai" in model:
        return "openai"
    if "claude" in model:
        return "anthropic"
    return "unknown"


def capture_llm_error(
    exc: Exception,
    *,
    user_id: int | None = None,
    user_email: str | None = None,
    model: str | None = None,
    status: int | None = None,
    response_body: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Capture an LLM call failure to Sentry with user + model + provider context.

    No-op if Sentry isn't initialised. Never raises.

    Args:
        exc: the exception to report
        user_id / user_email: identify which user hit this
        model: the LLM model the caller was using
        status: HTTP status code from the provider (None for non-HTTP failures)
        response_body: truncated provider response body (for 4xx/5xx debugging)
        extra: additional context sections, each becomes a "context" block in Sentry
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        with sentry_sdk.isolation_scope() as scope:
            if user_id is not None:
                scope.set_user({"id": user_id, "email": user_email})
            if model:
                scope.set_tag("llm_provider", _llm_provider(model))
                scope.set_tag("llm_model", model)
            if status is not None:
                scope.set_tag("provider_status", str(status))
            if response_body is not None or status is not None:
                scope.set_context("provider_response", {
                    "status": status,
                    "body": response_body,
                })
            if extra:
                for name, data in extra.items():
                    scope.set_context(name, data)
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Telemetry failures must never surface as user-visible errors.
        pass
