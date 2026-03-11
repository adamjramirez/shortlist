"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shortlist.api.routes import auth, jobs, profile, resumes, runs


def create_app() -> FastAPI:
    app = FastAPI(title="Shortlist", version="0.1.0")

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

    return app
