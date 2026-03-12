"""FastAPI application factory."""
import logging
import sys
from contextlib import asynccontextmanager

# Configure shortlist loggers to output to stdout (uvicorn overrides root logger)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
logging.getLogger("shortlist").addHandler(_handler)
logging.getLogger("shortlist").setLevel(logging.INFO)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from shortlist.api.routes import auth, jobs, profile, resumes, runs

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

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/debug/llm-test")
    async def llm_test():
        """Test LLM via subprocess curl (same as scorer now)."""
        import asyncio, os, time, json as _json, subprocess, tempfile

        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return {"error": "no key"}

        def _call():
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
            payload = {"contents": [{"parts": [{"text": "Say hello"}]}]}
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                _json.dump(payload, f)
                path = f.name
            start = time.time()
            try:
                r = subprocess.run(
                    ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json", "-d", f"@{path}", "--max-time", "15"],
                    capture_output=True, text=True, timeout=20,
                )
                os.unlink(path)
                elapsed = round(time.time() - start, 1)
                if r.returncode != 0:
                    return {"ok": False, "error": r.stderr[:200], "time": elapsed}
                data = _json.loads(r.stdout)
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return {"ok": True, "text": text, "time": elapsed}
            except Exception as e:
                os.unlink(path)
                return {"ok": False, "error": str(e), "time": round(time.time() - start, 1)}

        return await asyncio.to_thread(_call)

    return app
