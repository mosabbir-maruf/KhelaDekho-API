from __future__ import annotations

import asyncio
import hashlib
import base64
import json
from datetime import datetime, timezone

import httpx
import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings, BDT
from app.models.v2 import SportzfyEvent, SportzfyTeamInfo, SportzfyPlaybackResponse, SportzfyStream
from app.services.cache import cache
from app.utils.http import get_shared_client, build_headers

logger = structlog.get_logger(__name__)

_FIVE_MIN_MS = 5 * 60
_EIGHTEEN_HOURS_MS = 18 * 60 * 60


def _compute_status(starts_at: datetime | None, now: datetime) -> str:
    if not starts_at:
        return "upcoming"
    ts = int(starts_at.timestamp())
    now_ts = int(now.timestamp())
    if ts <= now_ts + _FIVE_MIN_MS and ts > now_ts - 3600:
        return "live"
    if ts > now_ts + _FIVE_MIN_MS and ts <= now_ts + _EIGHTEEN_HOURS_MS:
        return "upcoming"
    if ts < now_ts - 3600:
        return "finished"
    return "upcoming"


async def get_cached_events() -> list[SportzfyEvent]:
    return await cache.get_or_set(
        prefix="sportzfy",
        identifier="events",
        factory=fetch_events,
        ttl=settings.match_cache_ttl,
    )


async def fetch_events() -> list[SportzfyEvent]:
    base_url = settings.sportzfy_target_url.rstrip("/")
    url = f"{base_url}/api/upstream/events"

    client = await get_shared_client()
    headers = build_headers()
    headers["Accept"] = "application/json"

    try:
        resp = await client.get(url, headers=headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("sportzfy_fetch_failed", error=str(e))
        return []

    raw_events = data.get("events", []) if isinstance(data, dict) else []
    now = datetime.now(tz=timezone.utc)
    events: list[SportzfyEvent] = []

    for item in raw_events:
        if not isinstance(item, dict):
            continue
        event_id = item.get("id", "")
        if not event_id:
            continue

        starts_at = None
        if item.get("starts_at"):
            try:
                starts_at = datetime.fromisoformat(item["starts_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        status = _compute_status(starts_at, now)
        is_live = status == "live" or bool(item.get("is_live", 0))

        event = SportzfyEvent(
            id=event_id,
            parent=item.get("parent", event_id),
            enc_parent=item.get("enc_parent", item.get("parent", event_id)),
            sport=item.get("sport", "Sports"),
            league=item.get("league", ""),
            round=item.get("round", ""),
            team_a=SportzfyTeamInfo(
                name=item.get("team_a_name", "Team A"),
                logo=item.get("team_a_logo"),
            ),
            team_b=SportzfyTeamInfo(
                name=item.get("team_b_name", "Team B"),
                logo=item.get("team_b_logo"),
            ),
            starts_at=starts_at,
            is_live=is_live,
            status=status,
            league_icon=item.get("league_icon"),
            priority=int(item.get("priority", 0)),
        )
        events.append(event)

    logger.info("sportzfy_events_fetched", count=len(events))
    return events


def _decrypt_playback(enc: str, bucket: int) -> dict:
    key_material = f"{settings.sportzfy_playback_key}|lsp-v1|{bucket}".encode()
    key = hashlib.sha256(key_material).digest()
    enc_bytes = base64.b64decode(enc)
    iv = enc_bytes[:12]
    ct = enc_bytes[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ct, None)
    return json.loads(plaintext.decode("utf-8"))


_VERIFY_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Referer": f"{settings.sportzfy_target_url.rstrip('/')}/",
}


async def _verify_stream(
    s: dict,
    index: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> SportzfyStream | None:
    stream_url = s.get("stream_url", "")
    if not stream_url:
        return None

    drm_kid = s.get("drm_kid")
    drm_key = s.get("drm_key")
    has_drm = bool(drm_kid and drm_key)
    is_drm_dash = has_drm and s.get("stream_type") == "dash"

    alive = False
    async with sem:
        try:
            req = await client.get(
                stream_url,
                headers=_VERIFY_HEADERS,
                timeout=5.0,
                follow_redirects=True,
            )
            status = req.status_code
            if is_drm_dash:
                alive = req.is_success or status == 403
            else:
                alive = req.is_success
        except (httpx.TimeoutException, httpx.RequestError):
            alive = False

    if not alive:
        logger.warning("sportzfy_stream_dead", url=stream_url, label=s.get("label"))
        return None

    return SportzfyStream(
        id=s.get("id", ""),
        label=s.get("label", f"Server {index + 1}"),
        stream_type=s.get("stream_type", "hls"),
        stream_url=stream_url,
        drm_kid=drm_kid,
        drm_key=drm_key,
        sort_order=int(s.get("sort_order", index)),
    )


async def fetch_playback(parent: str) -> SportzfyPlaybackResponse:
    base_url = settings.sportzfy_target_url.rstrip("/")
    url = f"{base_url}/api/upstream/playback/{parent}"

    client = await get_shared_client()
    fetch_headers = {
        "Accept": "application/json",
        "X-Requested-With": "lsp",
    }

    try:
        resp = await client.get(url, headers=fetch_headers, timeout=15.0)
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        logger.error("sportzfy_playback_fetch_failed", parent=parent, error=str(e))
        return SportzfyPlaybackResponse(ok=False, parent=parent, streams=[])

    if isinstance(body, dict) and body.get("enc"):
        try:
            body = _decrypt_playback(body["enc"], body.get("bucket", 0))
        except Exception as e:
            logger.error("sportzfy_playback_decrypt_failed", parent=parent, error=str(e))
            return SportzfyPlaybackResponse(ok=False, parent=parent, streams=[])

    ok = body.get("ok", False) if isinstance(body, dict) else False
    raw_streams = body.get("streams", []) if isinstance(body, dict) else []

    verify_client = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    sem = asyncio.Semaphore(5)

    try:
        results = await asyncio.gather(
            *[_verify_stream(s, i, verify_client, sem) for i, s in enumerate(raw_streams)],
            return_exceptions=True,
        )
    finally:
        await verify_client.aclose()

    streams = [r for r in results if isinstance(r, SportzfyStream)]
    streams.sort(key=lambda s: s.sort_order)

    return SportzfyPlaybackResponse(ok=ok and len(streams) > 0, parent=parent, streams=streams)


async def get_cached_playback(parent: str) -> SportzfyPlaybackResponse:
    return await cache.get_or_set(
        prefix="sportzfy_playback",
        identifier=parent,
        factory=lambda: fetch_playback(parent),
        ttl=15,
    )
