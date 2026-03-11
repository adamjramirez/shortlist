"""Tests for the rate-limited HTTP client."""
import time
from unittest.mock import patch

import pytest

from shortlist import http


@pytest.fixture(autouse=True)
def reset_state():
    http.reset()
    yield
    http.reset()


class TestRateLimiting:
    def test_first_request_not_delayed(self):
        """First request to a domain should not sleep."""
        with patch("shortlist.http.time.sleep") as mock_sleep:
            with patch("shortlist.http.httpx.get") as mock_get:
                mock_get.return_value = "resp"
                http.get("https://example.com/test")
                mock_sleep.assert_not_called()

    def test_second_request_delayed(self):
        """Second request within the limit window should sleep."""
        with patch("shortlist.http.time.sleep") as mock_sleep:
            with patch("shortlist.http.httpx.get") as mock_get:
                mock_get.return_value = "resp"
                http.get("https://example.com/a")
                http.get("https://example.com/b")
                assert mock_sleep.call_count == 1

    def test_different_domains_independent(self):
        """Requests to different domains don't block each other."""
        with patch("shortlist.http.time.sleep") as mock_sleep:
            with patch("shortlist.http.httpx.get") as mock_get:
                mock_get.return_value = "resp"
                http.get("https://a.example.com/test")
                http.get("https://b.example.com/test")
                mock_sleep.assert_not_called()

    def test_known_domain_uses_configured_limit(self):
        """Known domains use their configured rate limit."""
        assert http.DOMAIN_LIMITS["hn.algolia.com"] == 1.0
        assert http.DOMAIN_LIMITS["www.linkedin.com"] == 3.0
        assert http.DOMAIN_LIMITS["generativelanguage.googleapis.com"] == 0.5

    def test_post_also_rate_limited(self):
        """POST requests are also rate limited."""
        with patch("shortlist.http.time.sleep") as mock_sleep:
            with patch("shortlist.http.httpx.post") as mock_post:
                mock_post.return_value = "resp"
                http.post("https://example.com/a", json={})
                http.post("https://example.com/b", json={})
                assert mock_sleep.call_count == 1

    def test_reset_clears_state(self):
        """reset() allows immediate requests again."""
        with patch("shortlist.http.time.sleep") as mock_sleep:
            with patch("shortlist.http.httpx.get") as mock_get:
                mock_get.return_value = "resp"
                http.get("https://example.com/a")
                http.reset()
                http.get("https://example.com/b")
                mock_sleep.assert_not_called()

    def test_default_headers_applied(self):
        """Requests include default User-Agent header."""
        with patch("shortlist.http.httpx.get") as mock_get:
            mock_get.return_value = "resp"
            http.get("https://example.com/test")
            headers = mock_get.call_args[1]["headers"]
            assert "User-Agent" in headers
            assert "Mozilla" in headers["User-Agent"]
