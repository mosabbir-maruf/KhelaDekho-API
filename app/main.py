from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator

import base64
import json
import httpx
import structlog
from fastapi import FastAPI, HTTPException, Query, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.models import (
    Match,
    MatchListResponse,
    ChannelInfo,
    ChannelListResponse,
    PlatformStatsResponse,
    HealthResponse,
    ScrapeResult,
    StreamResponse,
    StandardResponse,
)
from app.services.cache import cache
from app.services.scraper import get_scraper, KhelaDekhoScraper
from app.utils.http import build_headers, get_shared_client
from app.middleware.errors import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.dependencies.rate_limit import RateLimiter
from app.dependencies.auth import verify_signed_frontend_request

logger = structlog.get_logger(__name__)
BDT = timezone(timedelta(hours=6))

_start_time: float = 0.0
_scraper: KhelaDekhoScraper | None = None

# Dynamic rate limits
rate_limit_std = RateLimiter(requests=100, window=60)
rate_limit_stream = RateLimiter(requests=30, window=60)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _start_time, _scraper
    _start_time = time.monotonic()
    _scraper = await get_scraper()
    logger.info("app_started")
    yield
    if _scraper:
        await _scraper.close()
    from app.utils.http import close_shared_client
    await close_shared_client()
    logger.info("app_stopped")


app = FastAPI(
    title="KhelaDekho Aggregator API",
    description="API wrapper for publicly accessible match schedules and channel metadata from livekhela.tv. No stream URLs — only publicly embedded data.",
    version="1.0.0",
    lifespan=lifespan,
)

# Exception handlers
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure serving of production React frontend if built
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")


@app.get("/", response_class=HTMLResponse)
async def serve_player():
    if os.path.exists(frontend_dist):
        prod_index = os.path.join(frontend_dist, "index.html")
        if os.path.exists(prod_index):
            with open(prod_index, "r", encoding="utf-8") as f:
                return f.read()
                
    template_path = os.path.join(os.path.dirname(__file__), "templates", "player.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player template not found")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


async def _get_cached_scrape() -> ScrapeResult:
    return await cache.get_or_set(
        prefix="scrape",
        identifier="full",
        factory=lambda: _scraper.scrape_all(),
        ttl=settings.match_cache_ttl,
    )


def _make_health_response() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptime_seconds=time.monotonic() - _start_time,
        last_scrape=None,
    )


@app.get(
    "/api/v1/health",
    response_model=StandardResponse[HealthResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def health_check():
    return StandardResponse(success=True, data=_make_health_response())


@app.get(
    "/api/v1/matches",
    response_model=StandardResponse[MatchListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def list_matches(
    status: str | None = Query(None, pattern="^(live|upcoming|finished)$"),
    group: str | None = Query(None, min_length=2, max_length=50),
    stage: str | None = Query(None, min_length=2, max_length=50),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    scrape = await _get_cached_scrape()
    matches = scrape.matches

    if status:
        matches = [m for m in matches if m.status == status]
    if group:
        g_lower = group.lower()
        matches = [m for m in matches if g_lower in m.group.lower()]
    if stage:
        s_lower = stage.lower()
        matches = [m for m in matches if s_lower in m.stage.lower()]

    matches.sort(key=lambda m: (m.start_time or datetime.max.replace(tzinfo=BDT)))

    total = len(matches)
    page = matches[offset : offset + limit]

    return StandardResponse(
        success=True,
        data=MatchListResponse(
            matches=page,
            total=total,
            cached_at=scrape.fetched_at,
        )
    )


@app.get(
    "/api/v1/matches/{match_id}",
    response_model=StandardResponse[Match],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def get_match(match_id: str):
    scrape = await _get_cached_scrape()
    for match in scrape.matches:
        if match.match_id == match_id:
            return StandardResponse(success=True, data=match)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")


@app.get(
    "/api/v1/matches/live",
    response_model=StandardResponse[MatchListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def list_live_matches():
    scrape = await _get_cached_scrape()
    live = [m for m in scrape.matches if m.status == "live"]
    live.sort(key=lambda m: (m.start_time or datetime.max.replace(tzinfo=BDT)))
    return StandardResponse(
        success=True,
        data=MatchListResponse(
            matches=live,
            total=len(live),
            cached_at=scrape.fetched_at,
        )
    )


@app.get(
    "/api/v1/channels",
    response_model=StandardResponse[ChannelListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def list_channels(
    status: str | None = Query(None, pattern="^(live|down|hidden)$"),
    category: str | None = Query(None, min_length=2, max_length=50),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    scrape = await _get_cached_scrape()
    channels = scrape.channels

    if status:
        channels = [c for c in channels if c.status == status]
    if category:
        c_lower = category.lower()
        channels = [c for c in channels if c_lower in c.category.lower()]

    channels.sort(key=lambda c: c.sort_order)

    total = len(channels)
    page = channels[offset : offset + limit]

    return StandardResponse(
        success=True,
        data=ChannelListResponse(
            channels=page,
            total=total,
            cached_at=scrape.fetched_at,
        )
    )


@app.get(
    "/api/v1/channels/live",
    response_model=StandardResponse[ChannelListResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def list_live_channels():
    scrape = await _get_cached_scrape()
    live = [c for c in scrape.channels if c.status == "live"]
    live.sort(key=lambda c: (-c.live_viewers, c.sort_order))
    return StandardResponse(
        success=True,
        data=ChannelListResponse(
            channels=live,
            total=len(live),
            cached_at=scrape.fetched_at,
        )
    )


@app.get(
    "/api/v1/stats",
    response_model=StandardResponse[PlatformStatsResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_std)]
)
async def get_platform_stats():
    scrape = await _get_cached_scrape()
    stats = scrape.platform_stats
    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stats not available")
    return StandardResponse(
        success=True,
        data=PlatformStatsResponse(
            stats=stats,
            cached_at=scrape.fetched_at,
        )
    )


@app.get(
    "/api/v1/groups",
    dependencies=[Depends(rate_limit_std)]
)
async def list_groups():
    scrape = await _get_cached_scrape()
    groups: dict[str, int] = {}
    for m in scrape.matches:
        g = m.group or "Unknown"
        groups[g] = groups.get(g, 0) + 1
    
    return StandardResponse(
        success=True,
        data={"groups": [{"name": k, "match_count": v} for k, v in sorted(groups.items())]}
    )


@app.get(
    "/api/v1/stages",
    dependencies=[Depends(rate_limit_std)]
)
async def list_stages():
    scrape = await _get_cached_scrape()
    stages: dict[str, int] = {}
    for m in scrape.matches:
        s = m.stage or "Unknown"
        stages[s] = stages.get(s, 0) + 1
        
    return StandardResponse(
        success=True,
        data={"stages": [{"name": k, "match_count": v} for k, v in sorted(stages.items())]}
    )


def _decode_payload(payload: str) -> dict:
    try:
        # Reverse string
        reversed_payload = payload[::-1]
        # Base64 decode
        decoded_bytes = base64.b64decode(reversed_payload)
        # Parse JSON
        return json.loads(decoded_bytes.decode("utf-8"))
    except Exception as e:
        logger.error("payload_decoding_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to decode stream payload")


@app.get(
    "/api/v1/channels/{channel_key}/stream",
    response_model=StandardResponse[StreamResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_stream), Depends(verify_signed_frontend_request)]
)
async def get_channel_stream(
    channel_key: str,
    client: httpx.AsyncClient = Depends(get_shared_client)
):
    scrape = await _get_cached_scrape()
    channel = None
    for ch in scrape.channels:
        if ch.key == channel_key:
            channel = ch
            break

    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    if not channel.play_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Protected stream token missing for this channel",
        )

    # Use cache to avoid hammering target API for hot streams
    cached_stream = await cache.get("stream", channel_key)
    if cached_stream:
        return StandardResponse(success=True, data=cached_stream)

    # Call target API to get stream payload
    headers = build_headers()
    headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
    headers["Origin"] = "https://livekhela.tv"
    headers["Referer"] = "https://livekhela.tv/"

    data = {"key": channel.key, "access": channel.play_token}
    play_url = "https://livekhela.tv/api/channel"
    
    try:
        res = await client.post(play_url, headers=headers, data=data, timeout=5.0)
        res.raise_for_status()
        resp_json = res.json()
    except Exception as e:
        logger.error("stream_api_request_failed", key=channel.key, error=str(e))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch stream details from source")

    if not resp_json.get("success") or not resp_json.get("payload"):
        logger.error("stream_api_error", key=channel.key, response=resp_json)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=resp_json.get("message") or "Source failed to provide stream data",
        )

    decoded = _decode_payload(resp_json["payload"])
    
    expires_at = None
    if decoded.get("exp"):
        expires_at = datetime.fromtimestamp(decoded["exp"], tz=BDT)

    response_data = StreamResponse(
        key=channel.key,
        name=channel.name,
        url=decoded.get("url", ""),
        type=decoded.get("type", "dash"),
        drm=decoded.get("drm"),
        clearkey=decoded.get("clearkey"),
        sources=decoded.get("sources", []),
        expires_at=expires_at,
    )

    # Cache stream info for 30 seconds
    await cache.set("stream", channel_key, response_data, ttl=30)
    
    return StandardResponse(success=True, data=response_data)
