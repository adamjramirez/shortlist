"""Tests for pipeline run routes."""
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from shortlist.api.crypto import _get_fernet
    _get_fernet.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture()
def mock_worker():
    """Mock execute_run so we don't run the actual pipeline."""
    import shortlist.api.worker  # ensure module is imported before patching
    with patch("shortlist.api.worker.execute_run", new_callable=AsyncMock) as mock:
        yield mock


async def _setup_profile(client, auth_headers):
    """Set up a complete profile with fit_context, tracks, and API key."""
    await client.put("/api/profile", json={
        "fit_context": "Senior backend engineer looking for staff roles",
        "tracks": {"backend": {"title": "Backend Engineer", "search_queries": ["python backend"]}},
        "llm": {"model": "gemini-2.5-flash", "api_key": "test-key-123"},
    }, headers=auth_headers)


@pytest.mark.asyncio
async def test_create_run(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)

    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert "id" in data
    mock_worker.assert_called_once()


@pytest.mark.asyncio
async def test_create_run_requires_profile(client):
    resp = await client.post("/api/auth/signup", json={
        "email": "noprofile@example.com", "password": "pass123",
    })
    headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.post("/api/runs", headers=headers)
    assert resp.status_code == 400
    assert "profile" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_run_requires_api_key(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "test",
        "tracks": {"em": {"title": "EM", "search_queries": ["eng manager"]}},
    }, headers=auth_headers)

    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 400
    assert "AI provider" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_run_requires_tracks(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "test",
        "llm": {"model": "gemini-2.5-flash", "api_key": "test-key"},
    }, headers=auth_headers)

    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 400
    assert "role" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_run_requires_fit_context(client, auth_headers):
    await client.put("/api/profile", json={
        "tracks": {"em": {"title": "EM", "search_queries": ["eng manager"]}},
        "llm": {"model": "gemini-2.5-flash", "api_key": "test-key"},
    }, headers=auth_headers)

    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 400
    assert "description" in resp.json()["detail"].lower() or "looking" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_one_active_run_per_user(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)

    resp1 = await client.post("/api/runs", headers=auth_headers)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/runs", headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_list_runs(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    await client.post("/api/runs", headers=auth_headers)

    resp = await client.get("/api/runs", headers=auth_headers)
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_get_run(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    create = await client.post("/api/runs", headers=auth_headers)
    run_id = create.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == run_id


@pytest.mark.asyncio
async def test_get_other_users_run(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    create = await client.post("/api/runs", headers=auth_headers)
    run_id = create.json()["id"]

    resp = await client.post("/api/auth/signup", json={
        "email": "other@example.com", "password": "pass123",
    })
    other_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.get(f"/api/runs/{run_id}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_run(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    create = await client.post("/api/runs", headers=auth_headers)
    run_id = create.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Can start a new run after cancelling
    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_cancel_completed_run_fails(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    create = await client.post("/api/runs", headers=auth_headers)
    run_id = create.json()["id"]

    # Cancel it first
    await client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)

    # Can't cancel again
    resp = await client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_hourly_rate_limit(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)

    # First 3 runs succeed (cancel each so we can start another)
    for _ in range(3):
        resp = await client.post("/api/runs", headers=auth_headers)
        assert resp.status_code == 201
        run_id = resp.json()["id"]
        await client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)

    # 4th run hits rate limit
    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 429
    assert "3 runs per hour" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_runs_require_auth(client):
    assert (await client.post("/api/runs")).status_code == 401
    assert (await client.get("/api/runs")).status_code == 401
    assert (await client.get("/api/runs/1")).status_code == 401


@pytest.mark.asyncio
async def test_manual_run_has_trigger_manual(client, auth_headers, mock_worker):
    await _setup_profile(client, auth_headers)
    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["trigger"] == "manual"


@pytest.mark.asyncio
async def test_manual_run_resets_next_run_at_when_auto_run_enabled(client, auth_headers, mock_worker):
    """Manual run pushes next_run_at forward so scheduler doesn't fire immediately after."""
    await _setup_profile(client, auth_headers)
    await client.put("/api/profile", json={"auto_run": {"enabled": True, "interval_h": 6}},
                     headers=auth_headers)

    before_str = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]["next_run_at"]
    await client.post("/api/runs", headers=auth_headers)
    after_str = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]["next_run_at"]

    assert after_str > before_str


@pytest.mark.asyncio
async def test_manual_run_no_error_when_auto_run_disabled(client, auth_headers, mock_worker):
    """Manual run with auto-run disabled works fine."""
    await _setup_profile(client, auth_headers)
    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["trigger"] == "manual"
