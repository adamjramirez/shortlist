"""Tests for AWW client — slice pulling from AWW server."""
import httpx
import pytest

from shortlist.aww_client import pull_networking_slice


class FakeHeaders:
    def __init__(self, content_type: str = "text/markdown"):
        self._ct = content_type

    def get(self, key: str, default: str = "") -> str:
        return self._ct if key == "content-type" else default


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", content_type: str = "text/markdown"):
        self.status_code = status_code
        self.text = text
        self.headers = FakeHeaders(content_type)


def test_pull_success(monkeypatch):
    content = "# Adam Ramirez\n\n## About\nA software engineer based in Dallas, TX with experience in Python, Go, and distributed systems. Currently building products."
    monkeypatch.setattr(
        httpx, "get",
        lambda url, **kw: FakeResponse(200, content),
    )
    result = pull_networking_slice("107f0a25c6fd")
    assert result is not None
    assert "Adam Ramirez" in result


def test_pull_404_returns_none(monkeypatch):
    monkeypatch.setattr(
        httpx, "get",
        lambda url, **kw: FakeResponse(404),
    )
    assert pull_networking_slice("000000000000") is None


def test_pull_empty_node_id():
    assert pull_networking_slice("") is None
    assert pull_networking_slice(None) is None


def test_pull_network_error_returns_none(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("connection timed out")
    monkeypatch.setattr(httpx, "get", raise_timeout)
    assert pull_networking_slice("107f0a25c6fd") is None


def test_pull_tiny_response_rejected(monkeypatch):
    monkeypatch.setattr(
        httpx, "get",
        lambda url, **kw: FakeResponse(200, "tiny"),
    )
    assert pull_networking_slice("107f0a25c6fd") is None


def test_pull_uses_correct_url(monkeypatch):
    captured = {}
    def fake_get(url, **kw):
        captured["url"] = url
        return FakeResponse(404)
    monkeypatch.setattr(httpx, "get", fake_get)

    pull_networking_slice("abc123def456", base_url="https://example.com")
    assert captured["url"] == "https://example.com/api/nodes/abc123def456/slices/networking"
