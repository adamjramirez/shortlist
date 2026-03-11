"""Tests for auth routes."""
import pytest


@pytest.mark.asyncio
async def test_signup(client):
    resp = await client.post("/api/auth/signup", json={
        "email": "new@example.com",
        "password": "securepass123",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "token" in data
    assert data["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_signup_duplicate_email(client):
    await client.post("/api/auth/signup", json={
        "email": "dupe@example.com",
        "password": "pass123",
    })
    resp = await client.post("/api/auth/signup", json={
        "email": "dupe@example.com",
        "password": "pass456",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_signup_missing_fields(client):
    resp = await client.post("/api/auth/signup", json={"email": "no@pass.com"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login(client):
    await client.post("/api/auth/signup", json={
        "email": "login@example.com",
        "password": "mypassword",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "login@example.com",
        "password": "mypassword",
    })
    assert resp.status_code == 200
    assert "token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/auth/signup", json={
        "email": "wrong@example.com",
        "password": "correct",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wrong@example.com",
        "password": "incorrect",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    resp = await client.post("/api/auth/login", json={
        "email": "ghost@example.com",
        "password": "anything",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client):
    signup = await client.post("/api/auth/signup", json={
        "email": "me@example.com",
        "password": "pass123",
    })
    token = signup.json()["token"]

    resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"


@pytest.mark.asyncio
async def test_me_no_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_bad_token(client):
    resp = await client.get("/api/auth/me", headers={
        "Authorization": "Bearer garbage.token.here",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
