"""FastAPI application factory."""
import logging
import os
import sys
from contextlib import asynccontextmanager

# Configure shortlist loggers to output to stdout (uvicorn overrides root logger)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
logging.getLogger("shortlist").addHandler(_handler)
logging.getLogger("shortlist").setLevel(logging.INFO)

# Initialise Sentry BEFORE importing app modules so the FastAPI auto-integration
# hooks are installed before any routes are imported. If SENTRY_DSN is unset
# (local dev, tests), init is a no-op and there is zero overhead.
_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_sentry_dsn,
        # Errors-only: we want exception triage, not APM. Keeps event count
        # on the free tier well below the 5k/mo quota.
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        send_default_pii=True,   # captures user-identified email + request URL
        environment=(
            "production" if os.environ.get("FLY_APP_NAME") else "local"
        ),
        # Release tagging — if Fly passes a commit SHA via env var, use it.
        release=os.environ.get("FLY_MACHINE_VERSION") or os.environ.get("GIT_COMMIT"),
    )
    logging.getLogger("shortlist").info(
        "Sentry enabled (env=%s)",
        "production" if os.environ.get("FLY_APP_NAME") else "local",
    )

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from shortlist.api.routes import auth, jobs, profile, resumes, runs, tailor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Clear stale runs on startup (zombie runs from previous deploys)."""
    from shortlist.api.db import get_session
    from shortlist.api.models import Run

    try:
        async for session in get_session():
            result = await session.execute(
                update(Run)
                .where(Run.status.in_(("pending", "running")))
                .values(status="failed", error="Server restarted")
            )
            await session.commit()
            if result.rowcount:
                logger.info(f"Cleared {result.rowcount} stale run(s) on startup")
    except Exception as e:
        logger.warning(f"Could not clear stale runs on startup: {e}")

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Shortlist", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(resumes.router)
    app.include_router(runs.router)
    app.include_router(jobs.router)
    app.include_router(tailor.router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app
