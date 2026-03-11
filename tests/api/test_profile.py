"""Tests for profile routes."""
import pytest


@pytest.mark.asyncio
async def test_get_profile_empty(client, auth_headers):
    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Should return empty template structure
    assert "fit_context" in data
    assert data["fit_context"] == ""
    assert data["tracks"] == {}


@pytest.mark.asyncio
async def test_put_profile(client, auth_headers):
    profile = {
        "fit_context": "Looking for EM roles at Series B+",
        "tracks": {
            "em": {
                "title": "Engineering Manager",
                "search_queries": ["Engineering Manager", "Head of Engineering"],
            }
        },
        "filters": {
            "location": {"remote": True, "local_cities": ["new york"]},
            "salary": {"min_base": 200000},
        },
    }
    resp = await client.put("/api/profile", json=profile, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["fit_context"] == "Looking for EM roles at Series B+"
    assert "em" in data["tracks"]


@pytest.mark.asyncio
async def test_put_profile_then_get(client, auth_headers):
    profile = {
        "fit_context": "VP Engineering search",
        "tracks": {"vp": {"title": "VP Engineering", "search_queries": ["VP Engineering"]}},
    }
    await client.put("/api/profile", json=profile, headers=auth_headers)

    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["fit_context"] == "VP Engineering search"


@pytest.mark.asyncio
async def test_put_profile_updates_existing(client, auth_headers):
    await client.put("/api/profile", json={
        "fit_context": "first",
        "tracks": {},
    }, headers=auth_headers)

    await client.put("/api/profile", json={
        "fit_context": "updated",
        "tracks": {"em": {"title": "EM", "search_queries": []}},
    }, headers=auth_headers)

    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.json()["fit_context"] == "updated"
    assert "em" in resp.json()["tracks"]


@pytest.mark.asyncio
async def test_put_profile_with_llm_key(client, auth_headers, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

    profile = {
        "fit_context": "test",
        "tracks": {},
        "llm": {
            "model": "gemini-2.5-flash",
            "api_key": "sk-secret-key-12345",
        },
    }
    resp = await client.put("/api/profile", json=profile, headers=auth_headers)
    assert resp.status_code == 200
    # API key should NOT be returned in plaintext
    llm = resp.json().get("llm", {})
    assert llm.get("api_key") != "sk-secret-key-12345"
    assert llm.get("has_api_key") is True


@pytest.mark.asyncio
async def test_put_profile_preserves_api_key_on_update(client, auth_headers, monkeypatch):
    """Updating profile without sending api_key must not wipe the stored key."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

    # Set profile with API key
    await client.put("/api/profile", json={
        "fit_context": "initial",
        "tracks": {},
        "llm": {"model": "gemini-2.5-flash", "api_key": "sk-secret-12345"},
    }, headers=auth_headers)

    # Update just fit_context, no api_key
    await client.put("/api/profile", json={
        "fit_context": "updated",
    }, headers=auth_headers)

    resp = await client.get("/api/profile", headers=auth_headers)
    data = resp.json()
    assert data["fit_context"] == "updated"
    assert data["llm"]["has_api_key"] is True  # key preserved


@pytest.mark.asyncio
async def test_put_partial_update_preserves_other_fields(client, auth_headers):
    """Updating one field must not wipe other fields."""
    await client.put("/api/profile", json={
        "fit_context": "original context",
        "tracks": {"em": {"title": "EM", "search_queries": ["EM"]}},
        "filters": {"location": {"remote": True}},
    }, headers=auth_headers)

    # Update only fit_context
    await client.put("/api/profile", json={
        "fit_context": "new context",
    }, headers=auth_headers)

    resp = await client.get("/api/profile", headers=auth_headers)
    data = resp.json()
    assert data["fit_context"] == "new context"
    assert "em" in data["tracks"]  # tracks preserved
    assert data["filters"]["location"]["remote"] is True  # filters preserved


@pytest.mark.asyncio
async def test_profile_requires_auth(client):
    resp = await client.get("/api/profile")
    assert resp.status_code == 401

    resp = await client.put("/api/profile", json={"fit_context": "test", "tracks": {}})
    assert resp.status_code == 401
