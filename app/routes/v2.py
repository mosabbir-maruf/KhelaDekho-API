from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
import structlog

from app.config import BDT, settings
from app.dependencies.rate_limit import APIRateLimiter
from app.models import StandardResponse
from app.models.v2 import (
    Channel,
    ChannelListResponse,
    Highlight,
    HighlightListResponse,
    KickbdMatch,
    KickbdMatchListResponse,
)
from app.services.channels import (
    get_cached_channel,
    get_cached_channels,
    get_cached_highlight,
    get_cached_highlights,
)
from app.services.kickbd_matches import get_cached_kickbd_matches

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v2")
rate_limit = APIRateLimiter(requests=100, window=60)


@router.get(
    "/channels",
    response_model=StandardResponse[ChannelListResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_channels(
    q: Optional[str] = Query(None, min_length=1, max_length=50),
    alive_only: bool = Query(False, alias="alive"),
):
    channels = await get_cached_channels()
    if alive_only:
        channels = [c for c in channels if c.is_alive]
    if q:
        query = q.lower()
        channels = [c for c in channels if query in c.name.lower()]

    proxy_base = "/api/v2/proxy?url="
    for ch in channels:
        if ch.stream_url:
            ch.stream_url = f"{proxy_base}{urllib.parse.quote(ch.stream_url, safe='')}"

    cached_at = datetime.now(BDT)
    return StandardResponse(
        success=True,
        data=ChannelListResponse(
            channels=channels,
            total=len(channels),
            cached_at=cached_at,
        ),
    )


@router.get(
    "/channels/{channel_id}",
    response_model=StandardResponse[Channel],
    dependencies=[Depends(rate_limit)],
)
async def get_channel(channel_id: int):
    channel = await get_cached_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    proxy_base = "/api/v2/proxy?url="
    if channel.stream_url:
        channel.stream_url = f"{proxy_base}{urllib.parse.quote(channel.stream_url, safe='')}"

    return StandardResponse(success=True, data=channel)


@router.get(
    "/highlights",
    response_model=StandardResponse[HighlightListResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_highlights():
    highlights = await get_cached_highlights()
    cached_at = datetime.now(BDT)
    return StandardResponse(
        success=True,
        data=HighlightListResponse(
            highlights=highlights,
            total=len(highlights),
            cached_at=cached_at,
        ),
    )


@router.get(
    "/highlights/{slug}",
    response_model=StandardResponse[Highlight],
    dependencies=[Depends(rate_limit)],
)
async def get_highlight(slug: str):
    highlight = await get_cached_highlight(slug)
    if not highlight:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Highlight not found")
    return StandardResponse(success=True, data=highlight)


@router.get(
    "/matches/live",
    response_model=StandardResponse[KickbdMatchListResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_live_matches():
    matches = await get_cached_kickbd_matches()
    live = [m for m in matches if m.is_live]
    live.sort(key=lambda m: m.starts_at or datetime.max.replace(tzinfo=timezone.utc))
    cached_at = datetime.now(BDT)
    return StandardResponse(
        success=True,
        data=KickbdMatchListResponse(matches=live, total=len(live), cached_at=cached_at),
    )


_PROXY_FORWARD_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": settings.v2_home_url.rstrip("/"),
    "Referer": f"{settings.v2_home_url.rstrip('/')}/",
    "X-Requested-With": "lsp",
}


@router.get(
    "/proxy",
    dependencies=[Depends(rate_limit)],
)
async def proxy_stream(url: str = Query(..., min_length=10)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                url,
                headers=_PROXY_FORWARD_HEADERS,
                follow_redirects=True,
            )
            content = resp.content
            content_type = resp.headers.get("content-type", "application/octet-stream")
        except Exception as e:
            logger.error("proxy_fetch_failed", url=url, error=str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch stream")

    return Response(
        content=content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=30",
        },
    )


