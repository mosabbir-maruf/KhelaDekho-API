from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
    SportzfyEvent,
    SportzfyEventListResponse,
    SportzfyHealthResponse,
    SportzfyPlaybackResponse,
    SportzfyStatsResponse,
)
from app.services.channels import (
    get_cached_channel,
    get_cached_channels,
    get_cached_highlight,
    get_cached_highlights,
)
from app.services.kickbd_matches import get_cached_kickbd_matches
from app.services.sportzfy import get_cached_events, get_cached_playback

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v2")
rate_limit = APIRateLimiter(requests=100, window=60)

_start_time: float = time.monotonic()


def _paginate(items: list, limit: int, offset: int) -> tuple[list, int, dict]:
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "page": (offset // limit) + 1 if limit else 1,
        "per_page": limit,
        "total": total,
        "total_pages": max(1, -(-total // limit)) if limit else 1,
    }
    return page, total, meta


def _count_by(items: list[SportzfyEvent], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = getattr(item, key, "Unknown") or "Unknown"
        result[value] = result.get(value, 0) + 1
    return result


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


@router.get(
    "/health",
    response_model=StandardResponse[SportzfyHealthResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def health_check():
    return StandardResponse(
        success=True,
        data=SportzfyHealthResponse(
            uptime_seconds=time.monotonic() - _start_time,
        ),
    )


@router.get(
    "/events",
    response_model=StandardResponse[SportzfyEventListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def list_events(
    sport: Optional[str] = Query(None, min_length=2, max_length=50),
    league: Optional[str] = Query(None, min_length=2, max_length=100),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(live|upcoming|finished)$"),
    q: Optional[str] = Query(None, min_length=1, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    events = await get_cached_events()
    now = _now_utc()

    if sport:
        s = sport.lower()
        events = [e for e in events if e.sport.lower() == s]
    if league:
        l = league.lower()
        events = [e for e in events if l in e.league.lower()]
    if status_filter:
        events = [e for e in events if e.status == status_filter]
    if q:
        query = q.lower()
        events = [
            e
            for e in events
            if query in e.team_a.name.lower()
            or query in e.team_b.name.lower()
            or query in e.league.lower()
            or query in e.sport.lower()
        ]

    events.sort(key=lambda e: (e.priority, e.starts_at or datetime.max.replace(tzinfo=timezone.utc)))

    page, total, meta = _paginate(events, limit, offset)
    cached_at = datetime.now(BDT)

    return StandardResponse(
        success=True,
        data=SportzfyEventListResponse(events=page, total=total, cached_at=cached_at),
        meta=meta,
    )


@router.get(
    "/events/live",
    response_model=StandardResponse[SportzfyEventListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def list_live_events():
    events = await get_cached_events()
    live = [e for e in events if e.status == "live"]
    live.sort(key=lambda e: (e.priority, e.starts_at or datetime.max.replace(tzinfo=timezone.utc)))
    cached_at = datetime.now(BDT)
    return StandardResponse(
        success=True,
        data=SportzfyEventListResponse(events=live, total=len(live), cached_at=cached_at),
    )


@router.get(
    "/events/upcoming",
    response_model=StandardResponse[SportzfyEventListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def list_upcoming_events():
    events = await get_cached_events()
    upcoming = [e for e in events if e.status == "upcoming"]
    upcoming.sort(key=lambda e: (e.priority, e.starts_at or datetime.max.replace(tzinfo=timezone.utc)))
    cached_at = datetime.now(BDT)
    return StandardResponse(
        success=True,
        data=SportzfyEventListResponse(events=upcoming, total=len(upcoming), cached_at=cached_at),
    )


@router.get(
    "/events/{event_id}",
    response_model=StandardResponse[SportzfyEvent],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def get_event(event_id: str):
    events = await get_cached_events()
    for event in events:
        if event.id == event_id or event.enc_parent == event_id or event.parent == event_id:
            return StandardResponse(success=True, data=event)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


@router.get(
    "/events/{event_id}/playback",
    response_model=StandardResponse[SportzfyPlaybackResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def get_event_playback(event_id: str):
    events = await get_cached_events()
    event = next(
        (e for e in events if e.id == event_id or e.enc_parent == event_id or e.parent == event_id),
        None,
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if not event.parent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Event has no playback identifier")

    playback = await get_cached_playback(event.parent)
    if not playback.ok or not playback.streams:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No streams available for this event")

    return StandardResponse(success=True, data=playback)


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
    "Origin": settings.sportzfy_target_url.rstrip("/"),
    "Referer": f"{settings.sportzfy_target_url.rstrip('/')}/",
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


@router.get(
    "/sports",
    dependencies=[Depends(rate_limit)],
)
async def list_sports():
    events = await get_cached_events()
    counts = _count_by(events, "sport")
    return StandardResponse(
        success=True,
        data={
            "sports": [
                {"name": k, "event_count": v}
                for k, v in sorted(counts.items(), key=lambda x: -x[1])
            ]
        },
    )


@router.get(
    "/leagues",
    dependencies=[Depends(rate_limit)],
)
async def list_leagues():
    events = await get_cached_events()
    counts = _count_by(events, "league")
    return StandardResponse(
        success=True,
        data={
            "leagues": [
                {"name": k, "event_count": v}
                for k, v in sorted(counts.items(), key=lambda x: -x[1])
            ]
        },
    )


@router.get(
    "/stats",
    response_model=StandardResponse[SportzfyStatsResponse],
    dependencies=[Depends(rate_limit)],
)
async def get_stats():
    events = await get_cached_events()
    live = sum(1 for e in events if e.status == "live")
    upcoming = sum(1 for e in events if e.status == "upcoming")
    sports = len(set(e.sport for e in events))
    leagues = len(set(e.league for e in events))
    return StandardResponse(
        success=True,
        data=SportzfyStatsResponse(
            total_events=len(events),
            live_events=live,
            upcoming_events=upcoming,
            sports_count=sports,
            leagues_count=leagues,
            cached_at=datetime.now(BDT),
        ),
    )
