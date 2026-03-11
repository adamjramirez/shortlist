"""Tests for DB connection layer."""
import pytest
from shortlist.api.db import _get_database_url, _get_connect_args


def test_postgres_url_conversion(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db")
    assert _get_database_url().startswith("postgresql+asyncpg://")


def test_postgresql_url_conversion(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    assert _get_database_url().startswith("postgresql+asyncpg://")


def test_missing_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL not set"):
        _get_database_url()


def test_fly_internal_disables_ssl():
    args = _get_connect_args("postgresql+asyncpg://user:pass@shortlist-db.flycast:5432/db")
    assert args.get("ssl") is False


def test_external_url_no_special_args():
    args = _get_connect_args("postgresql+asyncpg://user:pass@db.example.com:5432/db")
    assert "ssl" not in args
