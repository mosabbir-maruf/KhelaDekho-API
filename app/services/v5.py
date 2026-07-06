"""V5 Match-centric Scraping and Stream Resolution.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timezone

import httpx
import structlog

from app.config import settings
from app.models.v2 import KickbdMatch, MatchChannel, TeamInfo
from app.services.cache import cache

logger = structlog.get_logger(__name__)

if not settings.v5_home_url:
    raise ValueError("KHELADEKHO_V5_HOME_URL setting is required")

_HOME = settings.v5_home_url.rstrip("/")
_API_BASE = f"{_HOME}/papi"

_SCRAPE_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{_HOME}/",
    "Origin": _HOME,
}


async def _fetch_json(url: str) -> dict | list | None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_SCRAPE_HEADERS, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("v5_fetch_json_failed", url=url, error=str(e))
        return None


def _channel_key(name: str) -> str:
    raw = name.lower()
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", raw))


async def fetch_matches() -> list[KickbdMatch]:
    data = await _fetch_json(f"{_API_BASE}/matches/football")
    if not isinstance(data, list):
        return []

    out: list[KickbdMatch] = []
    seen_slugs = set()

    for m in data:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        slug = _channel_key(m.get("title") or str(m["id"]))
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        is_live = m.get("status") == "live"
        t = m.get("teams") or {}
        t1 = t.get("home") or {}
        t2 = t.get("away") or {}

        out.append(KickbdMatch(
            id=slug,
            slug=slug,
            name=(m.get("title") or "").strip(),
            sport=(m.get("category") or "football").strip(),
            status=m.get("status") or "",
            is_live=is_live,
            start_date=m.get("date") if m.get("date") else None,
            end_date=None,
            poster=m.get("poster") or m.get("ppvPoster"),
            team_a=TeamInfo(name=(t1.get("name") or "").strip(), logo=t1.get("badge")) if t1.get("name") else None,
            team_b=TeamInfo(name=(t2.get("name") or "").strip(), logo=t2.get("badge")) if t2.get("name") else None,
        ))
    return out


async def get_cached_matches() -> list[KickbdMatch]:
    return await cache.get_or_set(prefix="v5_service", identifier="matches", factory=fetch_matches, ttl=60)


async def fetch_match_channels(slug: str) -> list[dict]:
    matches = await get_cached_matches()
    match_item = next((m for m in matches if m.slug == slug), None)
    if not match_item:
        return []

    data = await _fetch_json(f"{_API_BASE}/matches/football")
    if not isinstance(data, list):
        return []

    raw_match = None
    for m in data:
        if isinstance(m, dict) and _channel_key(m.get("title") or str(m.get("id"))) == slug:
            raw_match = m
            break

    if not raw_match:
        return []

    channels = []
    tv_channels = raw_match.get("tvChannels") or []
    substreams = raw_match.get("substreams") or []

    for ch in tv_channels:
        if isinstance(ch, dict) and ch.get("id"):
            channels.append({
                "id": f"dlhd-{ch['id']}",
                "name": ch.get("name") or "TV Channel",
                "server": "TV",
                "source_url": f"{_API_BASE}/tv/resolve/dlhd-{ch['id']}",
            })

    for sub in substreams:
        if isinstance(sub, dict) and sub.get("id"):
            channels.append({
                "id": f"sub-{_channel_key(sub['id'])}",
                "name": sub.get("name") or "Substream",
                "server": (sub.get("locale") or "intl").upper(),
                "source_url": f"{_API_BASE}/tv/resolve/{sub['id']}",
            })

    if not channels and raw_match.get("embedUrl"):
        channels.append({
            "id": f"embed-{slug}",
            "name": raw_match.get("title") or "Embed Stream",
            "server": "Primary",
            "source_url": raw_match["embedUrl"],
        })

    return channels


async def get_cached_match_channels(slug: str) -> list[dict]:
    return await cache.get_or_set(
        prefix="v5_mc", identifier=slug, factory=lambda: fetch_match_channels(slug), ttl=120
    )


def public_channels(raw: list[dict]) -> list[MatchChannel]:
    return [MatchChannel(id=c["id"], name=c["name"], server=c["server"]) for c in raw]


async def resolve_stream(source_url: str) -> dict | None:
    if "/tv/resolve/" in source_url:
        data = await _fetch_json(source_url)
        if isinstance(data, dict) and data.get("success") and data.get("stream"):
            resolved_url = data["stream"]
            if resolved_url.startswith("/"):
                resolved_url = _HOME + resolved_url
            return {
                "stream_url": resolved_url,
                "stream_type": "hls",
            }
    return {
        "stream_url": source_url,
        "stream_type": "hls" if ".m3u8" in source_url else "dash",
    }


async def get_cached_stream(slug: str, ch_id: str, source_url: str) -> dict | None:
    return await cache.get_or_set(
        prefix="v5_st", identifier=f"{slug}:{ch_id}",
        factory=lambda: resolve_stream(source_url), ttl=45,
    )
