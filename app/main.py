from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import base64
import json
import httpx
import structlog
from fastapi import FastAPI, HTTPException, Query, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings, BDT
from app.routes import v2 as v2_routes
from app.routes import v4 as v4_routes
from app.models import (
    Match,
    MatchListResponse,
    ChannelInfo,
    ChannelInfoPublic,
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
from app.dependencies.rate_limit import APIRateLimiter
from app.dependencies.auth import verify_signed_frontend_request

logger = structlog.get_logger(__name__)

_start_time: float = 0.0
_scraper: KhelaDekhoScraper | None = None

# Dynamic rate limits
rate_limit_std = APIRateLimiter(requests=100, window=60)
rate_limit_stream = APIRateLimiter(requests=30, window=60)

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
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=500)

app.include_router(v2_routes.router)
app.include_router(v4_routes.router)

@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):
    response = await call_next(request)
    rate_limit_headers = getattr(request.state, "rate_limit_headers", None)
    if rate_limit_headers:
        response.headers.update(rate_limit_headers)
    return response

# Configure serving of production React frontend if built
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(rate_limit_std)])
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


_MATCH_SORT_KEY = lambda m: (m.start_time or datetime.max.replace(tzinfo=BDT))


def _compute_pagination_meta(limit: int, offset: int, total: int) -> dict:
    return {
        "page": (offset // limit) + 1,
        "per_page": limit,
        "total": total,
        "total_pages": max(1, -(-total // limit)),
    }


def _count_by_field(items: list, field: str, default: str = "Unknown") -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = getattr(item, field, None) or default
        result[value] = result.get(value, 0) + 1
    return result


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

    matches.sort(key=_MATCH_SORT_KEY)

    total = len(matches)
    page = matches[offset : offset + limit]

    return StandardResponse(
        success=True,
        data=MatchListResponse(
            matches=page,
            total=total,
            cached_at=scrape.fetched_at,
        ),
        meta=_compute_pagination_meta(limit, offset, total),
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
    live.sort(key=_MATCH_SORT_KEY)
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
    public_channels = [
        ChannelInfoPublic(**ch.model_dump(exclude={"play_token", "play_exp"}))
        for ch in page
    ]

    return StandardResponse(
        success=True,
        data=ChannelListResponse(
            channels=public_channels,
            total=total,
            cached_at=scrape.fetched_at,
        ),
        meta=_compute_pagination_meta(limit, offset, total),
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
    public_live = [
        ChannelInfoPublic(**ch.model_dump(exclude={"play_token", "play_exp"}))
        for ch in live
    ]
    return StandardResponse(
        success=True,
        data=ChannelListResponse(
            channels=public_live,
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
    groups = _count_by_field(scrape.matches, "group")
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
    stages = _count_by_field(scrape.matches, "stage")
    return StandardResponse(
        success=True,
        data={"stages": [{"name": k, "match_count": v} for k, v in sorted(stages.items())]}
    )


def _decode_payload(payload: Any, access_token: str | None) -> dict:
    try:
        # Support legacy string format
        if isinstance(payload, str):
            reversed_payload = payload[::-1]
            decoded_bytes = base64.b64decode(reversed_payload)
            return json.loads(decoded_bytes.decode("utf-8"))
            
        # Support legacy legacy/data wrapped format
        if isinstance(payload, dict) and payload.get("legacy") and payload.get("data"):
            data_str = payload["data"]
            reversed_payload = data_str[::-1]
            decoded_bytes = base64.b64decode(reversed_payload)
            return json.loads(decoded_bytes.decode("utf-8"))
            
        # Support AES-GCM encrypted payload dictionary (v2)
        if isinstance(payload, dict) and int(payload.get("v", 0)) == 2:
            import hashlib
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # Key derivation: SHA-256(token + "|mlbd-web-stream-v2")
            token_str = str(access_token or "")
            key = hashlib.sha256((token_str + "|mlbd-web-stream-v2").encode("utf-8")).digest()
            
            def b64url_decode(s: str) -> bytes:
                padded = s + '=' * (4 - len(s) % 4)
                return base64.urlsafe_b64decode(padded)
                
            iv = b64url_decode(payload["iv"])
            ct = b64url_decode(payload["ct"])
            tag = b64url_decode(payload["tag"])
            
            aesgcm = AESGCM(key)
            plain_bytes = aesgcm.decrypt(iv, ct + tag, None)
            return json.loads(plain_bytes.decode("utf-8"))
            
        raise ValueError("Unsupported payload format or version")
    except Exception as e:
        logger.error("payload_decoding_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decode stream payload"
        )


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
    base_url = settings.v1_home_url.rstrip("/")
    headers["Origin"] = base_url
    headers["Referer"] = f"{base_url}/"

    data = {"key": channel.key, "access": channel.play_token}
    play_url = f"{base_url}/api/channel"
    
    for attempt in range(3):
        try:
            res = await client.post(play_url, headers=headers, data=data, timeout=10.0)
            res.raise_for_status()
            resp_json = res.json()
            break
        except Exception as e:
            if attempt == 2:
                logger.error("stream_api_request_failed", key=channel.key, error=str(e), attempts=attempt + 1)
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch stream details from source")
            await asyncio.sleep(1.0 * (attempt + 1))

    if not resp_json.get("success") or not resp_json.get("payload"):
        logger.error("stream_api_error", key=channel.key, response=resp_json)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=resp_json.get("message") or "Source failed to provide stream data",
        )

    decoded = _decode_payload(resp_json["payload"], channel.play_token)
    
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

    # Cache stream info for 15 seconds (shorter to reduce stale token errors)
    await cache.set("stream", channel_key, response_data, ttl=15)
    
    return StandardResponse(success=True, data=response_data)
