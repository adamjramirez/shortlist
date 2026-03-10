"""Rate-limited HTTP client.

All external requests go through this module. No exceptions.
Rate limiting is automatic based on the request domain.
"""
import logging
import time
from collections import defaultdict
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Minimum seconds between requests to each domain
DOMAIN_LIMITS: dict[str, float] = {
    "jobs.ashbyhq.com": 2.0,
    "boards-api.greenhouse.io": 2.0,
    "api.lever.co": 2.0,
    "www.linkedin.com": 2.0,
    "hn.algolia.com": 1.0,
    "nextplayso.substack.com": 2.0,
    "generativelanguage.googleapis.com": 0.5,  # Gemini Flash handles rapid fire
}

DEFAULT_LIMIT = 2.0
DEFAULT_TIMEOUT = 15

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_last_request: dict[str, float] = defaultdict(float)


def _wait(domain: str) -> None:
    """Block until it's safe to make a request to this domain."""
    limit = DOMAIN_LIMITS.get(domain, DEFAULT_LIMIT)
    elapsed = time.time() - _last_request[domain]
    if elapsed < limit:
        sleep_time = limit - elapsed
        logger.debug(f"Rate limit: sleeping {sleep_time:.1f}s for {domain}")
        time.sleep(sleep_time)
    _last_request[domain] = time.time()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def get(url: str, *, params: dict | None = None, headers: dict | None = None,
        cookies: dict | None = None, timeout: int = DEFAULT_TIMEOUT,
        follow_redirects: bool = True) -> httpx.Response:
    """Rate-limited GET request."""
    _wait(_domain(url))
    return httpx.get(
        url, params=params, headers={**DEFAULT_HEADERS, **(headers or {})},
        cookies=cookies, timeout=timeout, follow_redirects=follow_redirects,
    )


def post(url: str, *, json: dict | None = None, headers: dict | None = None,
         timeout: int = DEFAULT_TIMEOUT) -> httpx.Response:
    """Rate-limited POST request."""
    _wait(_domain(url))
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    if json is not None:
        merged["Content-Type"] = "application/json"
    return httpx.post(url, json=json, headers=merged, timeout=timeout)


def reset() -> None:
    """Reset all rate limit state. For testing."""
    _last_request.clear()
