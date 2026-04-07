"""Tests for auto-run scheduling via the profile API."""
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from shortlist.api.models import Profile


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from shortlist.api.crypto import _get_fernet
    _get_fernet.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


# ── Defaults ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_run_defaults_to_disabled(client, auth_headers):
    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.status_code == 200
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is False
    assert ar["next_run_at"] is None
    assert ar["consecutive_failures"] == 0
    assert ar["interval_h"] == 12


# ── Enable / disable ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enable_auto_run_sets_next_run_at(client, auth_headers):
    resp = await client.put(
        "/api/profile",
        json={"auto_run": {"enabled": True, "interval_h": 12}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is True
    assert ar["interval_h"] == 12
    assert ar["next_run_at"] is not None
    # next_run_at should be ~12h from now
    next_run = datetime.fromisoformat(ar["next_run_at"])
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    assert next_run > datetime.now(timezone.utc) + timedelta(hours=11)
    assert next_run < datetime.now(timezone.utc) + timedelta(hours=13)


@pytest.mark.asyncio
async def test_disable_auto_run_clears_next_run_at_and_failures(client, auth_headers):
    await client.put(
        "/api/profile",
        json={"auto_run": {"enabled": True, "interval_h": 6}},
        headers=auth_headers,
    )
    resp = await client.put(
        "/api/profile",
        json={"auto_run": {"enabled": False}},
        headers=auth_headers,
    )
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is False
    assert ar["next_run_at"] is None
    assert ar["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_change_interval_only_updates_next_run_at(client, auth_headers):
    await client.put(
        "/api/profile",
        json={"auto_run": {"enabled": True, "interval_h": 24}},
        headers=auth_headers,
    )
    resp = await client.put(
        "/api/profile",
        json={"auto_run": {"interval_h": 6}},
        headers=auth_headers,
    )
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is True
    assert ar["interval_h"] == 6
    # next_run_at should be ~6h from now (recalculated)
    next_run = datetime.fromisoformat(ar["next_run_at"])
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    assert next_run < datetime.now(timezone.utc) + timedelta(hours=7)


@pytest.mark.asyncio
async def test_change_interval_when_disabled_does_not_set_next_run_at(client, auth_headers):
    """Changing interval while disabled must not activate scheduling."""
    resp = await client.put(
        "/api/profile",
        json={"auto_run": {"interval_h": 6}},
        headers=auth_headers,
    )
    ar = resp.json()["auto_run"]
    assert ar["enabled"] is False
    assert ar["next_run_at"] is None


# ── Preservation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_run_preserved_when_field_absent(client, auth_headers):
    """PUT without auto_run key does not touch scheduler state."""
    await client.put(
        "/api/profile",
        json={"auto_run": {"enabled": True, "interval_h": 12}},
        headers=auth_headers,
    )
    original = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]

    # Update something unrelated
    await client.put("/api/profile", json={"fit_context": "updated"}, headers=auth_headers)
    after = (await client.get("/api/profile", headers=auth_headers)).json()["auto_run"]

    assert after["enabled"] == original["enabled"]
    assert after["next_run_at"] == original["next_run_at"]


# ── Column isolation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_run_not_stored_in_config_json(client, auth_headers, session):
    """auto_run data lives in dedicated columns, not inside config JSON."""
    await client.put(
        "/api/profile",
        json={"auto_run": {"enabled": True, "interval_h": 8}},
        headers=auth_headers,
    )
    result = await session.execute(select(Profile))
    profile = result.scalar_one()
    assert "auto_run" not in (profile.config or {})
    assert profile.auto_run_enabled is True
    assert profile.auto_run_interval_h == 8
