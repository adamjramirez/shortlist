"""Tests for pipeline run routes."""
import pytest


@pytest.mark.asyncio
async def test_create_run(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "test", "tracks": {"em": {"title": "EM", "search_queries": []}},
    }, headers=auth_headers)

    resp = await client.post("/api/runs", headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "running"  # spawner succeeded → running
    assert data["machine_id"] is not None
    assert "id" in data


@pytest.mark.asyncio
async def test_create_run_requires_profile(client):
    """User without profile can't start a run."""
    # Sign up a fresh user (no profile set)
    resp = await client.post("/api/auth/signup", json={
        "email": "noprofile@example.com",
        "password": "pass123",
    })
    headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.post("/api/runs", headers=headers)
    assert resp.status_code == 400
    assert "profile" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_one_active_run_per_user(client, auth_headers):
    # Set up profile first
    await client.put("/api/profile", json={
        "fit_context": "test", "tracks": {"em": {"title": "EM", "search_queries": []}},
    }, headers=auth_headers)

    resp1 = await client.post("/api/runs", headers=auth_headers)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/runs", headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_list_runs(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "test", "tracks": {"em": {"title": "EM", "search_queries": []}},
    }, headers=auth_headers)

    await client.post("/api/runs", headers=auth_headers)

    resp = await client.get("/api/runs", headers=auth_headers)
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "running"


@pytest.mark.asyncio
async def test_get_run(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "test", "tracks": {"em": {"title": "EM", "search_queries": []}},
    }, headers=auth_headers)

    create = await client.post("/api/runs", headers=auth_headers)
    run_id = create.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == run_id
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_get_other_users_run(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "test", "tracks": {"em": {"title": "EM", "search_queries": []}},
    }, headers=auth_headers)

    create = await client.post("/api/runs", headers=auth_headers)
    run_id = create.json()["id"]

    # Different user
    resp = await client.post("/api/auth/signup", json={
        "email": "other@example.com", "password": "pass123",
    })
    other_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.get(f"/api/runs/{run_id}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_runs_require_auth(client):
    assert (await client.post("/api/runs")).status_code == 401
    assert (await client.get("/api/runs")).status_code == 401
    assert (await client.get("/api/runs/1")).status_code == 401
