"""Tests for LLM client retry logic."""
from unittest.mock import patch, AsyncMock

import pytest
import httpx

from shortlist.api.llm_client import _retry_on_transient


@pytest.fixture(autouse=True)
def no_sleep():
    """Skip actual backoff sleeps in tests."""
    with patch("shortlist.api.llm_client.asyncio.sleep", new_callable=AsyncMock):
        yield


def _make_status_error(status: int) -> httpx.HTTPStatusError:
    resp = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
    return httpx.HTTPStatusError(f"HTTP {status}", request=resp.request, response=resp)


@pytest.mark.asyncio
async def test_retry_on_429_succeeds_second_attempt():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_status_error(429)
        return "ok"

    result = await _retry_on_transient(flaky, "test")
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_on_500_succeeds():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_status_error(500)
        return "ok"

    result = await _retry_on_transient(flaky, "test")
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    async def always_429():
        raise _make_status_error(429)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _retry_on_transient(always_429, "test")
    assert exc_info.value.response.status_code == 429


@pytest.mark.asyncio
async def test_no_retry_on_400():
    call_count = 0

    async def bad_request():
        nonlocal call_count
        call_count += 1
        raise _make_status_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        await _retry_on_transient(bad_request, "test")
    assert call_count == 1


@pytest.mark.asyncio
async def test_no_retry_on_success():
    call_count = 0

    async def ok():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await _retry_on_transient(ok, "test")
    assert result == "ok"
    assert call_count == 1
