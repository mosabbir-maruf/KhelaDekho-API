from __future__ import annotations

import asyncio

import httpx
import structlog

from app.config import settings
from app.models.v4 import ProxybdixChannel
from app.services.cache import cache

logger = structlog.get_logger(__name__)

_API_BASE = settings.v4_home_url.rstrip("/")
_API_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "application/json",
}


async def fetch_all_channels() -> list[ProxybdixChannel]:
    config_url = f"{_API_BASE}/api.php?action=config&id="

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{_API_BASE}/api.php?action=list", headers=_API_HEADERS)
            resp.raise_for_status()
            channel_list = resp.json()
        except Exception as e:
            logger.error("proxybdix_list_fetch_failed", error=str(e))
            return []

        if not isinstance(channel_list, list) or not channel_list:
            return []

        valid = [ch for ch in channel_list if isinstance(ch, dict) and ch.get("id")]
        if not valid:
            return []

        config_results = await asyncio.gather(
            *[client.get(f"{config_url}{ch['id']}", headers=_API_HEADERS) for ch in valid],
            return_exceptions=True,
        )

    verify_client = httpx.AsyncClient(timeout=5.0)
    channels: list[ProxybdixChannel] = []

    try:
        for ch, result in zip(valid, config_results):
            stream_url = None
            stream_type = "dash"
            drm_kid = None
            drm_key = None

            if isinstance(result, httpx.Response):
                try:
                    cfg = result.json()
                    if isinstance(cfg, dict) and cfg.get("m"):
                        stream_url = cfg["m"]
                        if ".mpd" in stream_url:
                            stream_type = "dash"
                        elif ".m3u8" in stream_url or ".m3u" in stream_url:
                            stream_type = "hls"
                        drm_kid = cfg.get("k")
                        drm_key = cfg.get("v")
                except Exception:
                    pass

            is_alive = False
            if stream_url:
                try:
                    r = await verify_client.head(stream_url, headers=_API_HEADERS, follow_redirects=True)
                    is_alive = r.is_success or r.status_code == 403
                except Exception:
                    pass

            channels.append(
                ProxybdixChannel(
                    id=ch["id"],
                    name=ch.get("name", ch["id"]),
                    stream_url=stream_url if is_alive else None,
                    stream_type=stream_type,
                    drm_kid=drm_kid if is_alive else None,
                    drm_key=drm_key if is_alive else None,
                    is_alive=is_alive,
                )
            )
    finally:
        await verify_client.aclose()

    logger.info(
        "proxybdix_channels_fetched",
        count=len(channels),
        alive=sum(1 for c in channels if c.is_alive),
    )
    return channels


async def get_cached_channels() -> list[ProxybdixChannel]:
    return await cache.get_or_set(
        prefix="proxybdix",
        identifier="channels",
        factory=fetch_all_channels,
        ttl=120,
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
        logger.warning("proxybdix_count_fetch_failed", error=str(e))
        return 0


async def get_cached_user_count() -> int:
    return await cache.get_or_set(
        prefix="proxybdix",
        identifier="user_count",
        factory=fetch_user_count,
        ttl=60,
    )
