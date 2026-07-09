from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
    resolve_stream,
    resolve_tv_channel_stream,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v5")

_HOME = settings.v5_home_url.rstrip("/") if settings.v5_home_url else ""
_PROXY_BASE = "/api/v5/proxy?url="

# Stateless, signed proxy tokens. The token is a self-contained, HMAC-signed
# payload (upstream URL + expiry) so it validates on any worker/process with no
# shared in-memory state. This replaces the old in-memory dict + lock + TTL
# "touch" approach, which broke live streams: manifest reloads (every few
# seconds) frequently hit a different process/isolate where the token was
# missing -> 400 -> buffering. A reload minted a fresh token, so playback
# resumed until that process was recycled ("buffers after a while").
_TOKEN_TTL = 86400  # 24h — covers full live-viewing sessions


def _proxy_secret() -> bytes:
    return (settings.proxy_secret or "dev-insecure-proxy-secret-change-me").encode()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _create_proxy_token(upstream_url: str) -> str:
    exp = int(time.time()) + _TOKEN_TTL
    payload = json.dumps({"u": upstream_url, "exp": exp}, separators=(",", ":")).encode()
    body = _b64url_encode(payload)
    sig = _b64url_encode(hmac.new(_proxy_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _resolve_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.rsplit(".", 1)
        expected = _b64url_encode(hmac.new(_proxy_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(_b64url_decode(body))
        if not isinstance(payload.get("u"), str) or int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload["u"]
    except Exception:
        return None


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
async def get_match_stream(slug: str, ch: str = Query(..., min_length=1), sport: str = Query("football"), fresh: bool = Query(False)):
    raw = await get_cached_match_channels(slug, sport)
    channel = next((c for c in raw if c["id"] == ch), None)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    stream = await resolve_stream(channel["source_url"]) if fresh else await get_cached_stream(slug, ch, channel["source_url"])
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
    # Live manifests revalidate every few seconds. A single upstream blip during
    # revalidation must NOT become a hard 502 (which makes hls.js buffer). Serve
    # the last-good manifest while revalidating, and serve stale on any upstream
    # 5xx, so transient provider/CDN hiccups are absorbed transparently.
    _swr = 86400 if is_segment else 30
    return Response(
        content=content,
        status_code=resp.status_code,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": f"public, max-age={'86400' if is_segment else '5'}, stale-while-revalidate={_swr}, stale-if-error=86400",
        },
    )
