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

_HTTP_CLIENT = httpx.AsyncClient(timeout=15.0, headers=_SCRAPE_HEADERS, follow_redirects=True)

_BLOCKED_24_7_TITLES = {"24/7 South Park", "24/7 COWS"}


async def _fetch_json(url: str) -> dict | list | None:
    try:
        resp = await _HTTP_CLIENT.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("v5_fetch_json_failed", url=url, error=str(e))
        return None


def _channel_key(name: str) -> str:
    raw = name.lower()
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", raw))


async def fetch_raw_matches(sport: str = "football") -> list[dict]:
    data = await _fetch_json(f"{_API_BASE}/matches/{urllib.parse.quote(sport, safe='')}")
    return data if isinstance(data, list) else []


async def get_cached_raw_matches(sport: str = "football") -> list[dict]:
    return await cache.get_or_set(
        prefix=f"v5_raw_matches_{sport}", identifier=sport,
        factory=lambda: fetch_raw_matches(sport), ttl=60,
    )


async def fetch_matches(sport: str = "football") -> list[KickbdMatch]:
    data = await get_cached_raw_matches(sport)
    out: list[KickbdMatch] = []
    seen_slugs = set()

    for m in data:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        if m.get("title") in _BLOCKED_24_7_TITLES:
            continue
        slug = _channel_key(m.get("title") or str(m.get("id")))
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        is_live = m.get("status") == "live"
        t = m.get("teams") or {}
        t1 = t.get("home") or {}
        t2 = t.get("away") or {}

        name = (m.get("title") or "").strip()
        poster = m.get("poster") or m.get("ppvPoster")

        out.append(KickbdMatch(
            id=slug,
            slug=slug,
            name=name,
            sport=(m.get("category") or sport).strip(),
            status=m.get("status") or "",
            is_live=is_live,
            start_date=m.get("date") if m.get("date") else None,
            end_date=None,
            poster=poster,
            team_a=TeamInfo(name=(t1.get("name") or "").strip(), logo=t1.get("badge")) if t1.get("name") else None,
            team_b=TeamInfo(name=(t2.get("name") or "").strip(), logo=t2.get("badge")) if t2.get("name") else None,
        ))
    return out


async def get_cached_matches(sport: str = "football") -> list[KickbdMatch]:
    return await cache.get_or_set(
        prefix=f"v5_matches_{sport}", identifier=sport,
        factory=lambda: fetch_matches(sport), ttl=60,
    )


async def fetch_match_channels(slug: str, sport: str = "football") -> list[dict]:
    data = await get_cached_raw_matches(sport)

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
    sources = raw_match.get("sources") or []

    for ch in tv_channels:
        if isinstance(ch, dict) and ch.get("id"):
            channels.append({
                "id": f"dlhd-{ch['id']}",
                "name": ch.get("name") or "TV Channel",
                "server": "TV",
                "source_url": f"{_API_BASE}/tv/resolve/dlhd-{ch['id']}",
            })

    seen_ids = {str(s.get("id", "")).lower() for s in substreams if isinstance(s, dict)}
    for src in sources:
        if isinstance(src, dict) and src.get("id") and str(src["id"]).lower() not in seen_ids:
            channels.append({
                "id": f"src-{_channel_key(src['id'])}",
                "name": src.get("name") or src.get("source") or "Server",
                "server": "Primary",
                "source_url": f"{_API_BASE}/extract-url/{src['id']}",
            })

    for sub in substreams:
        if isinstance(sub, dict) and sub.get("id"):
            channels.append({
                "id": f"sub-{_channel_key(sub['id'])}",
                "name": sub.get("name") or "Substream",
                "server": (sub.get("locale") or "intl").upper(),
                "source_url": f"{_API_BASE}/extract-url/{sub['id']}",
            })

    if not channels and raw_match.get("embedUrl"):
        channels.append({
            "id": f"embed-{slug}",
            "name": raw_match.get("title") or "Embed Stream",
            "server": "Primary",
            "source_url": raw_match["embedUrl"],
        })

    return channels


async def get_cached_match_channels(slug: str, sport: str = "football") -> list[dict]:
    return await cache.get_or_set(
        prefix="v5_mc", identifier=f"{sport}_{slug}", factory=lambda: fetch_match_channels(slug, sport), ttl=120
    )


async def resolve_stream(source_url: str) -> dict | None:
    if "/tv/resolve/" in source_url or "/extract-url/" in source_url:
        data = await _fetch_json(source_url)
        if isinstance(data, dict) and data.get("success"):
            # TV channel (/tv/resolve/): response has "stream"
            if data.get("stream"):
                resolved_url = data["stream"]
                if resolved_url.startswith("/"):
                    resolved_url = _HOME + resolved_url
                return {"stream_url": resolved_url, "stream_type": "hls"}
            # Substream (/extract-url/): response has "hlsUrl"
            if data.get("hlsUrl"):
                return {"stream_url": data["hlsUrl"], "stream_type": "hls"}
    return {
        "stream_url": source_url,
        "stream_type": "hls" if ".m3u8" in source_url else "dash",
    }


async def get_cached_stream(slug: str, ch_id: str, source_url: str) -> dict | None:
    return await cache.get_or_set(
        prefix="v5_st", identifier=f"{slug}:{ch_id}",
        factory=lambda: resolve_stream(source_url), ttl=45,
    )


# --- V5 TV Channels (DLHD 24/7) ---

def detect_channel_category(name: str) -> str:
    n = f" {name.lower()} "
    if re.search(r"sport|espn|sky\s?sport|fox\s?sport|bein|dazn|nba|nfl|nhl|mlb|"
                 r"tnt\s?sport|premier|football|cricket|tennis|golf|wwe|ufc|racing|"
                 r"motogp|formula|\bf1\b|supersport|willow|optus", n):
        return "Sports"
    if re.search(r"news|cnn|bbc\s?news|fox\s?news|sky\s?news|al\s?jazeera|msnbc|cnbc|gb\s?news", n):
        return "News"
    if re.search(r"kids|cartoon|disney|nick|baby|boomerang|pbs\s?kids", n):
        return "Kids"
    if re.search(r"movie|cinema|hbo|\bamc\b|film|starz|showtime|cinemax|paramount", n):
        return "Entertainment"
    if re.search(r"music|mtv|vh1|radio|hits|rhythm|beat|concert|band|billboard", n):
        return "Music"
    return "General"


async def fetch_tv_channels() -> list[dict]:
    data = await _fetch_json(f"{_HOME}/data/dlhd-channels.json?v=7")
    if not isinstance(data, dict):
        return []
    raw = data.get("channels") or []
    out = []
    for ch in raw:
        if isinstance(ch, dict) and ch.get("id") and ch.get("name"):
            out.append({
                "id": f"dlhd-{ch['id']}",
                "name": ch["name"].strip(),
                "image": ch.get("image") or "",
                "country": ch.get("country") or "intl",
                "category": detect_channel_category(ch["name"]),
            })
    return out


async def get_cached_tv_channels() -> list[dict]:
    return await cache.get_or_set(
        prefix="v5_tv", identifier="channels", factory=fetch_tv_channels, ttl=120,
    )


async def resolve_tv_channel_stream(channel_id: str) -> dict | None:
    dlhd_id = channel_id.replace("dlhd-", "")
    resolve_url = f"{_API_BASE}/tv/resolve/dlhd-{dlhd_id}"
    return await resolve_stream(resolve_url)
