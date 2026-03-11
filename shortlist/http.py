"""Rate-limited HTTP client.

All external requests go through this module. No exceptions.
Rate limiting is automatic based on the request domain.
LinkedIn requests are routed through a proxy when PROXY_URL is set.
"""
import logging
import os
import threading
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
    "www.linkedin.com": 3.0,   # conservative — with 6 proxies, each IP sees 1 req/18s
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

# Domains that should be routed through the proxy when available
PROXY_DOMAINS = {"www.linkedin.com"}

_last_request: dict[str, float] = defaultdict(float)

# Global lock for LinkedIn — serializes all requests across threads/users
# so ThreadPoolExecutor workers don't bypass the rate limiter
_linkedin_lock = threading.Lock()


def _get_proxy_urls() -> list[str]:
    """Get proxy URLs from environment. Supports rotating through multiple ports."""
    base = os.environ.get("PROXY_URL")
    if not base:
        return []

    extra = os.environ.get("PROXY_URLS")  # comma-separated additional URLs
    if extra:
        return [base] + [u.strip() for u in extra.split(",") if u.strip()]
    return [base]


_proxy_index = 0


def _next_proxy() -> str | None:
    """Round-robin through available proxy URLs."""
    global _proxy_index
    urls = _get_proxy_urls()
    if not urls:
        return None
    url = urls[_proxy_index % len(urls)]
    _proxy_index += 1
    return url


def _should_proxy(domain: str) -> bool:
    """Check if this domain should use the proxy."""
    return domain in PROXY_DOMAINS and bool(_get_proxy_urls())


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
    """Rate-limited GET request. Routes through proxy for LinkedIn."""
    domain = _domain(url)
    use_proxy = _should_proxy(domain)

    # LinkedIn: serialize all requests globally (across threads/users)
    if domain in PROXY_DOMAINS:
        with _linkedin_lock:
            return _do_get(url, domain, params, headers, cookies, timeout,
                           follow_redirects, use_proxy)

    return _do_get(url, domain, params, headers, cookies, timeout,
                   follow_redirects, use_proxy)


def _do_get(url: str, domain: str, params, headers, cookies, timeout,
            follow_redirects, use_proxy) -> httpx.Response:
    """Internal GET with rate limiting and optional proxy."""
    _wait(domain)
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}

    if use_proxy:
        proxy_url = _next_proxy()
        if proxy_url:
            try:
                with httpx.Client(proxy=proxy_url, timeout=timeout,
                                  follow_redirects=follow_redirects) as client:
                    resp = client.get(url, params=params, headers=merged_headers,
                                      cookies=cookies)
                    if resp.status_code != 407:  # proxy auth failure
                        return resp
                    logger.warning(f"Proxy auth failed for {domain}, falling back to direct")
            except (httpx.ProxyError, httpx.ConnectError) as e:
                logger.warning(f"Proxy error for {domain}: {e}, falling back to direct")

    return httpx.get(
        url, params=params, headers=merged_headers,
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
