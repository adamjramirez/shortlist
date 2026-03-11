"""Database connection for the web API."""
import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _clean_url(url: str) -> str:
    """Convert a DATABASE_URL to asyncpg format."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # asyncpg doesn't support sslmode param — strip it
    if "?" in url:
        base, params = url.split("?", 1)
        filtered = "&".join(p for p in params.split("&") if not p.startswith("sslmode="))
        url = f"{base}?{filtered}" if filtered else base

    return url


def _get_database_url() -> str:
    """Get async database URL from environment."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return _clean_url(url)


def _get_connect_args(url: str) -> dict:
    """Get connection args. Disable SSL for Fly internal networking."""
    if "flycast" in url or "internal" in url:
        return {"ssl": False}
    return {}


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    """Create engine + session factory once, cached."""
    url = _get_database_url()
    engine = create_async_engine(
        url,
        echo=False,
        connect_args=_get_connect_args(url),
        pool_size=10,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=300,
    )
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    """FastAPI dependency that yields a DB session with auto-commit."""
    factory = _session_factory()
    async with factory() as session:
        async with session.begin():
            yield session
