from __future__ import annotations

import asyncio
import time
import structlog
from typing import Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import httpx

from app.config import settings

logger = structlog.get_logger(__name__)


class RateLimiter:
    def __init__(self, rpm: int = 30):
        self.rpm = rpm
        self.interval = 60.0 / rpm
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self._last_call = time.monotonic()


rate_limiter = RateLimiter(rpm=settings.rate_limit_rpm)


def is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 502, 503, 504)
    if isinstance(exc, httpx.RequestError):
        return True
    return False


RETRY_POLICY = retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=1, min=settings.retry_backoff, max=30),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError)),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)


def build_headers() -> dict[str, str]:
    return {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    await rate_limiter.acquire()

    @RETRY_POLICY
    async def _fetch():
        response = await client.get(
            url,
            headers=build_headers(),
            follow_redirects=True,
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        return response.text

    return await _fetch()


async def fetch_page_with_proxy(
    client: httpx.AsyncClient,
    url: str,
    proxy_url: str | None = None,
) -> str:
    headers = build_headers()
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
    async with httpx.AsyncClient(
        transport=transport,
        timeout=settings.request_timeout,
        follow_redirects=True,
    ) as proxy_client:
        await rate_limiter.acquire()
        response = await proxy_client.get(url, headers=build_headers())
        response.raise_for_status()
        return response.text


_client_instance: httpx.AsyncClient | None = None


async def get_shared_client() -> httpx.AsyncClient:
    global _client_instance
    if _client_instance is None or _client_instance.is_closed:
        _client_instance = httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        )
    return _client_instance


async def close_shared_client():
    global _client_instance
    if _client_instance and not _client_instance.is_closed:
        await _client_instance.aclose()
        _client_instance = None

