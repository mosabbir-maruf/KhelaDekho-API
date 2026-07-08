from __future__ import annotations

import threading
import time
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
    TVChannelListResponse,
    TVStreamResponse,
)
from app.services.channels import public_channels
from app.services.v5 import (
    get_cached_match_channels,
    get_cached_matches,
    get_cached_stream,
    get_cached_tv_channels,
    resolve_tv_channel_stream,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v5")

_HOME = settings.v5_home_url.rstrip("/") if settings.v5_home_url else ""
_PROXY_BASE = "/api/v5/proxy?url="

# Opaque token -> upstream URL mapping, so upstream provider URLs and auth
# tokens are never exposed to the client. Tokens expire 5 minutes after the
# last access so long-running streams don't break.
_TOKEN_TTL = 300
_proxy_tokens: dict[int, tuple[str, float]] = {}
_token_lock = threading.Lock()
_token_id = 0


def _create_proxy_token(upstream_url: str) -> int:
    global _token_id
    with _token_lock:
        _token_id += 1
        tid = _token_id
        _proxy_tokens[tid] = (upstream_url, time.time())
    return tid


def _resolve_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        tid = int(token)
    except (ValueError, TypeError):
        return None
    with _token_lock:
        entry = _proxy_tokens.get(tid)
        if not entry:
            return None
        # Extend TTL on each access (touch)
        _proxy_tokens[tid] = (entry[0], time.time())
        return entry[0]


# ---- Match endpoints ----

@router.get(
    "/matches",
    response_model=StandardResponse[KickbdMatchListResponse]
)
async def list_matches(live: bool = Query(False), sport: str = Query("football")):
    matches = await get_cached_matches(sport)
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
async def list_match_channels(slug: str, sport: str = Query("football")):
    raw = await get_cached_match_channels(slug, sport)
    channels = public_channels(raw)
    return StandardResponse(
        success=True,
        data=MatchChannelListResponse(slug=slug, channels=channels, total=len(channels)),
    )


@router.get(
    "/matches/{slug}/stream",
    response_model=StandardResponse[StreamResponse]
)
async def get_match_stream(slug: str, ch: str = Query(..., min_length=1), sport: str = Query("football")):
    raw = await get_cached_match_channels(slug, sport)
    channel = next((c for c in raw if c["id"] == ch), None)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    stream = await get_cached_stream(slug, ch, channel["source_url"])
    if not stream or not stream.get("stream_url"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stream unavailable")

    token = _create_proxy_token(stream["stream_url"])
    return StandardResponse(
        success=True,
        data=StreamResponse(
            name=channel["name"],
            stream_url=f"/api/v5/proxy?t={token}",
            stream_type=stream.get("stream_type", "hls"),
            drm_kid=stream.get("drm_kid"),
            drm_key=stream.get("drm_key"),
        ),
    )


# ---- TV channel endpoints ----

@router.get(
    "/tv/channels",
    response_model=StandardResponse[TVChannelListResponse]
)
async def list_tv_channels():
    channels = await get_cached_tv_channels()
    return StandardResponse(
        success=True,
        data=TVChannelListResponse(channels=channels, total=len(channels)),
    )


@router.get(
    "/tv/channel/{channel_id}/stream",
    response_model=StandardResponse[TVStreamResponse],
)
async def get_tv_channel_stream(channel_id: str):
    stream = await resolve_tv_channel_stream(channel_id)
    if not stream or not stream.get("stream_url"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stream unavailable")
    token = _create_proxy_token(stream["stream_url"])
    return StandardResponse(
        success=True,
        data=TVStreamResponse(id=channel_id, stream_url=f"/api/v5/proxy?t={token}", stream_type=stream.get("stream_type", "hls")),
    )


# ---- Proxy ----

_PROXY_FORWARD_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": _HOME,
    "Referer": f"{_HOME}/",
}


@router.get("/proxy")
async def proxy_stream(t: str | None = Query(None), url: str | None = Query(None)):
    upstream = _resolve_token(t) or url
    if not upstream or len(upstream) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid proxy request")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(upstream, headers=_PROXY_FORWARD_HEADERS, follow_redirects=True)
            content = resp.content
            content_type = resp.headers.get("content-type", "application/octet-stream")

            # HLS manifest rewriting
            if upstream.endswith(".m3u8") or "index.m3u8" in upstream or "playlist" in upstream:
                parsed = urllib.parse.urlparse(upstream)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                base_dir = parsed.path.rsplit("/", 1)[0]
                body = content.decode("utf-8", errors="ignore")
                lines = []
                for line in body.splitlines():
                    trimmed = line.strip()
                    if trimmed and not trimmed.startswith("#") and not trimmed.startswith("http"):
                        full = f"{origin}{trimmed}" if trimmed.startswith("/") else f"{origin}{base_dir}/{trimmed}"
                        lines.append(f"{_PROXY_BASE}{urllib.parse.quote(full, safe='')}")
                    else:
                        lines.append(line)
                content = "\n".join(lines).encode("utf-8")

        except Exception as e:
            logger.error("v5_proxy_fetch_failed", upstream=upstream, error=str(e))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch stream")

    is_segment = any(upstream.endswith(ext) for ext in (".ts", ".mp4", ".m4s")) or "/seg_" in upstream or "/segment" in upstream or "/init" in upstream
    if is_segment and not (200 <= resp.status_code < 300):
        return Response(
            content=None,
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )
    return Response(
        content=content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": f"public, max-age={'86400' if is_segment else '5'}",
        },
    )
