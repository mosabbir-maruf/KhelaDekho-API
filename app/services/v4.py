from __future__ import annotations

import asyncio

import httpx
import structlog

from app.config import settings
from app.models.v4 import ProxybdixChannel
from app.services.cache import cache

logger = structlog.get_logger(__name__)

if not settings.v4_home_url:
    raise ValueError("KHELADEKHO_V4_HOME_URL setting is required")

_API_BASE = settings.v4_home_url.rstrip("/")
_API_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "application/json",
}


async def fetch_all_channels() -> list[ProxybdixChannel]:
    config_url = f"{_API_BASE}/api.php?action=config&id="

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(config_url, headers=_API_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("v4_config_fetch_failed", url=config_url, error=str(e))
            return []

    if not isinstance(data, dict) or "categories" not in data:
        return []

    # Map categories -> channels
    raw_channels = []
    for cat in data["categories"]:
        if "channels" in cat:
            for ch in cat["channels"]:
                ch["category"] = cat.get("name")
                raw_channels.append(ch)

    # Resolve all stream URLs concurrently
    sem = asyncio.Semaphore(15)

    async def resolve_one(ch: dict) -> ProxybdixChannel | None:
        if not ch.get("id"):
            return None
        url = f"{_API_BASE}/api.php?action=stream&id={ch['id']}"
        async with sem:
            try:
                r = await client.get(url, headers=_API_HEADERS)
                r.raise_for_status()
                res = r.json()
                if isinstance(res, dict) and res.get("url"):
                    return ProxybdixChannel(
                        id=str(ch["id"]),
                        name=ch.get("name") or "Channel",
                        stream_url=res["url"],
                        stream_type="dash" if ".mpd" in res["url"] else "hls",
                        drm_kid=res.get("kid"),
                        drm_key=res.get("key"),
                        is_alive=True,
                    )
            except Exception as e:
                logger.debug("v4_resolve_failed", channel_id=ch["id"], error=str(e))
        return None

    async with httpx.AsyncClient(timeout=8.0) as client:
        tasks = [resolve_one(ch) for ch in raw_channels]
        results = await asyncio.gather(*tasks)

    return [r for r in results if r is not None]


async def get_cached_channels() -> list[ProxybdixChannel]:
    return await cache.get_or_set(
        prefix="v4_service", identifier="channels", factory=fetch_all_channels, ttl=120
    )


async def get_cached_channel(channel_id: str) -> ProxybdixChannel | None:
    all_channels = await get_cached_channels()
    for ch in all_channels:
        if ch.id == channel_id:
            return ch
    return None


async def fetch_user_count() -> int:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_API_BASE}/api.php?action=count", headers=_API_HEADERS
            )
            resp.raise_for_status()
            data = resp.json()
            return int(data.get("users", 0))
    except Exception as e:
        logger.warning("v4_count_fetch_failed", error=str(e))
        return 0


async def get_cached_user_count() -> int:
    return await cache.get_or_set(
        prefix="v4_service",
        identifier="user_count",
        factory=fetch_user_count,
        ttl=60,
    )
