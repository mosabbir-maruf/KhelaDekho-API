from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import settings, BDT
from app.dependencies.rate_limit import APIRateLimiter
from app.models import StandardResponse
from app.models.v4 import (
    ProxybdixChannel,
    ProxybdixChannelListResponse,
    ProxybdixHealthResponse,
    ProxybdixStatsResponse,
    ProxybdixStreamResponse,
)
from app.services.v4 import (
    get_cached_channel,
    get_cached_channels,
    get_cached_user_count,
)

router = APIRouter(prefix="/api/v4")
rate_limit = APIRateLimiter(requests=100, window=60)

_start_time: float = time.monotonic()


@router.get(
    "/health",
    response_model=StandardResponse[ProxybdixHealthResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def health_check():
    return StandardResponse(
        success=True,
        data=ProxybdixHealthResponse(
            uptime_seconds=time.monotonic() - _start_time,
            source=settings.v4_home_url,
        ),
    )


@router.get(
    "/channels",
    response_model=StandardResponse[ProxybdixChannelListResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_channels(
    q: Optional[str] = Query(None, min_length=1, max_length=50),
    alive_only: bool = Query(False, alias="alive"),
):
    channels = await get_cached_channels()
    if alive_only:
        channels = [c for c in channels if c.stream_url]
    if q:
        query = q.lower()
        channels = [c for c in channels if query in c.name.lower()]
    cached_at = datetime.now(BDT)
    return StandardResponse(
        success=True,
        data=ProxybdixChannelListResponse(
            channels=channels,
            total=len(channels),
            cached_at=cached_at,
        ),
    )


@router.get(
    "/channels/{channel_id}",
    response_model=StandardResponse[ProxybdixChannel],
    dependencies=[Depends(rate_limit)],
)
async def get_channel(channel_id: str):
    channel = await get_cached_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return StandardResponse(success=True, data=channel)


@router.get(
    "/channels/{channel_id}/stream",
    response_model=StandardResponse[ProxybdixStreamResponse],
    dependencies=[Depends(rate_limit)],
)
async def get_channel_stream(channel_id: str):
    channel = await get_cached_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    if not channel.stream_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stream URL not available for this channel",
        )
    return StandardResponse(
        success=True,
        data=ProxybdixStreamResponse(
            id=channel.id,
            name=channel.name,
            url=channel.stream_url,
            type=channel.stream_type,
            drm_kid=channel.drm_kid,
            drm_key=channel.drm_key,
        ),
    )


_PROXY_FORWARD_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": settings.v4_home_url.rstrip("/"),
    "Referer": f"{settings.v4_home_url.rstrip('/')}/",
}


@router.get("/proxy")
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
        except Exception:
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


@router.get(
    "/stats",
    response_model=StandardResponse[ProxybdixStatsResponse],
    dependencies=[Depends(rate_limit)],
)
async def get_stats():
    channels = await get_cached_channels()
    users = await get_cached_user_count()
    return StandardResponse(
        success=True,
        data=ProxybdixStatsResponse(
            online_users=users,
            channel_count=len(channels),
            cached_at=datetime.now(BDT),
        ),
    )
