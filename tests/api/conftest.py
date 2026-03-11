"""Shared fixtures for API tests."""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shortlist.api.app import create_app
from shortlist.api.db import get_session
from shortlist.api.models import Base
from shortlist.api.storage import MemoryStorage, get_storage


@pytest_asyncio.fixture
async def engine(tmp_path):
    """Async SQLite engine with tables created."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    e = create_async_engine(url, echo=False)
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory):
    """Raw async session for model tests."""
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def test_storage():
    """Single MemoryStorage instance shared across all requests in a test."""
    return MemoryStorage()


@pytest_asyncio.fixture
async def app(session_factory, test_storage):
    """FastAPI app with all external dependencies overridden for tests."""
    application = create_app()

    async def override_get_session():
        async with session_factory() as s:
            async with s.begin():
                yield s

    application.dependency_overrides[get_session] = override_get_session
    application.dependency_overrides[get_storage] = lambda: test_storage
    return application


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client for route tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    """Sign up a test user and return auth headers."""
    resp = await client.post("/api/auth/signup", json={
        "email": "testuser@example.com",
        "password": "pass123",
    })
    return {"Authorization": f"Bearer {resp.json()['token']}"}
