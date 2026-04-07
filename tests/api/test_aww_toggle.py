"""Tests for use_aww_slice toggle via the profile API."""
import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from shortlist.api.crypto import _get_fernet
    _get_fernet.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.mark.asyncio
async def test_use_aww_slice_defaults_true(client, auth_headers):
    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["use_aww_slice"] is True


@pytest.mark.asyncio
async def test_disable_aww_slice(client, auth_headers):
    resp = await client.put(
        "/api/profile",
        json={"use_aww_slice": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["use_aww_slice"] is False


@pytest.mark.asyncio
async def test_re_enable_aww_slice(client, auth_headers):
    await client.put("/api/profile", json={"use_aww_slice": False}, headers=auth_headers)
    resp = await client.put("/api/profile", json={"use_aww_slice": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["use_aww_slice"] is True


@pytest.mark.asyncio
async def test_aww_node_id_preserved_when_toggling(client, auth_headers):
    """Toggling use_aww_slice must not clear aww_node_id."""
    await client.put(
        "/api/profile",
        json={"aww_node_id": "abc123def456"},
        headers=auth_headers,
    )
    resp = await client.put(
        "/api/profile",
        json={"use_aww_slice": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["use_aww_slice"] is False
    assert data["aww_node_id"] == "abc123def456"


@pytest.mark.asyncio
async def test_use_aww_slice_independent_of_other_fields(client, auth_headers):
    """Saving fit_context does not reset use_aww_slice."""
    await client.put("/api/profile", json={"use_aww_slice": False}, headers=auth_headers)
    resp = await client.put(
        "/api/profile",
        json={"fit_context": "updated context"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["use_aww_slice"] is False
