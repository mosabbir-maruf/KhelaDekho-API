from __future__ import annotations

import urllib.parse

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import settings
from app.models import StandardResponse
from app.models.v2 import (
    KickbdMatchListResponse,
    MatchChannelListResponse,
    StreamResponse,
)
from app.services.channels import (
    get_cached_match_channels,
    get_cached_matches,
    get_cached_stream,
    public_channels,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v2")

_PROXY_BASE = "/api/v2/proxy?url="


@router.get(
    "/matches",
    response_model=StandardResponse[KickbdMatchListResponse]
)
async def list_matches(live: bool = Query(False)):
    matches = await get_cached_matches()
    if live:
        matches = [m for m in matches if m.is_live]
    return StandardResponse(
        success=True,
        data=KickbdMatchListResponse(matches=matches, total=len(matches)),
    )


@router.get(
    "/matches/{slug}/channels",
    response_model=StandardResponse[MatchChannelListResponse]
)
async def list_match_channels(slug: str):
    raw = await get_cached_match_channels(slug)
    channels = public_channels(raw)
    return StandardResponse(
        success=True,
        data=MatchChannelListResponse(slug=slug, channels=channels, total=len(channels)),
    )


@router.get(
    "/matches/{slug}/stream",
    response_model=StandardResponse[StreamResponse]
)
async def get_match_stream(slug: str, ch: str = Query(..., min_length=1)):
    raw = await get_cached_match_channels(slug)
    channel = next((c for c in raw if c["id"] == ch), None)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    stream = await get_cached_stream(slug, ch, channel["source_url"])
    if not stream or not stream.get("stream_url"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stream unavailable")
    return StandardResponse(
        success=True,
        data=StreamResponse(
            name=channel["name"],
            stream_url=f"{_PROXY_BASE}{urllib.parse.quote(stream['stream_url'], safe='')}",
            stream_type=stream.get("stream_type", "hls"),
            drm_kid=stream.get("drm_kid"),
            drm_key=stream.get("drm_key"),
        ),
    )


_PROXY_FORWARD_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": settings.v2_home_url.rstrip("/"),
    "Referer": f"{settings.v2_home_url.rstrip('/')}/",
}


@router.get("/proxy")
async def proxy_stream(url: str = Query(..., min_length=10)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, headers=_PROXY_FORWARD_HEADERS, follow_redirects=True)
            content = resp.content
            content_type = resp.headers.get("content-type", "application/octet-stream")
        except Exception as e:
            logger.error("proxy_fetch_failed", url=url, error=str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch stream")

    return Response(
        content=content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=30"},
    )
