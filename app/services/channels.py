"""V2 (kickbd) — match-centric scraping.

The upstream is a Next.js app; match/channel data lives in the server-rendered
RSC payload. Flow: homepage -> matches[]; /matches/iframe/{slug} -> channels{};
each channel's /source/ page carries an encrypted `var _p` that decrypts to the
playable stream URL + ClearKey DRM.
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

_HOME = settings.v2_home_url.rstrip("/")
_DECRYPT_KEY = "999999859198"

_SCRAPE_HEADERS = {
    "User-Agent": settings.user_agent,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


async def _fetch_text(url: str, client: httpx.AsyncClient) -> str | None:
    try:
        resp = await client.get(
            url,
            headers={**_SCRAPE_HEADERS, "Referer": f"{_HOME}/", "Origin": _HOME},
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("v2_fetch_failed", url=url, error=str(e))
        return None


def _unescape_flight(s: str) -> str:
    return s.replace('\\"', '"').replace('\\\\', '\\')


def _extract_json_after(text: str, key: str, open_ch: str, close_ch: str):
    """Return the balanced JSON value that follows `"key":<open>` in text."""
    marker = f'"{key}":{open_ch}'
    idx = text.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker) - 1
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def _channel_key(name: str, server: str) -> str:
    raw = f"{name}__{server}".lower()
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", raw))


def _decrypt_source(payload_urlenc: str) -> str:
    decoded = urllib.parse.unquote(payload_urlenc)
    return "".join(
        chr((ord(ch) + 5) ^ int(_DECRYPT_KEY[i % len(_DECRYPT_KEY)]))
        for i, ch in enumerate(decoded)
    )


def _parse_source_js(html: str) -> dict | None:
    m = re.search(r'var _p\s*=\s*"([^"]+)"', html)
    if not m:
        return None
    decrypted = _decrypt_source(m.group(1))
    url_match = re.search(r"window\.player\.load\('([^']+)'\)", decrypted)
    if not url_match:
        return None
    url = url_match.group(1)
    result = {"stream_url": url, "stream_type": "dash" if ".mpd" in url else "hls"}
    kid = re.search(r"k_id='([^']+)'", decrypted)
    kv = re.search(r"k_v='([^']+)'", decrypted)
    if kid:
        result["drm_kid"] = kid.group(1)
    if kv:
        result["drm_key"] = kv.group(1)
    return result


# --- Matches ---

async def fetch_matches() -> list[KickbdMatch]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        html = await _fetch_text(_HOME, client)
    if not html:
        return []
    raw = _extract_json_after(_unescape_flight(html), "matches", "[", "]") or []
    now = datetime.now(tz=timezone.utc)
    out: list[KickbdMatch] = []
    for m in raw:
        if not isinstance(m, dict) or not m.get("slug"):
            continue
        is_live = str(m.get("match_status", "")).lower() == "live"
        if not is_live:
            try:
                start = datetime.fromisoformat(m["match_start_date"])
                end = datetime.fromisoformat(m["match_end_date"])
                is_live = start <= now < end
            except Exception:
                is_live = False
        t1 = m.get("team1") or None
        t2 = m.get("team2") or None
        out.append(KickbdMatch(
            id=m["slug"],
            slug=m["slug"],
            name=(m.get("match_name") or "").strip(),
            sport=(m.get("sport_name") or "").strip(),
            status=m.get("match_status") or "",
            is_live=is_live,
            start_date=m.get("match_start_date"),
            end_date=m.get("match_end_date"),
            poster=m.get("slider_image"),
            team_a=TeamInfo(name=(t1.get("name") or "").strip(), logo=t1.get("logo")) if t1 else None,
            team_b=TeamInfo(name=(t2.get("name") or "").strip(), logo=t2.get("logo")) if t2 else None,
        ))
    return out


async def get_cached_matches() -> list[KickbdMatch]:
    return await cache.get_or_set(prefix="kickbd", identifier="matches", factory=fetch_matches, ttl=60)


# --- Match channels ---

async def fetch_match_channels(slug: str) -> list[dict]:
    """Returns raw channel dicts: {id, name, server, source_url}."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        html = await _fetch_text(f"{_HOME}/matches/iframe/{urllib.parse.quote(slug)}", client)
    if not html:
        return []
    mapping = _extract_json_after(_unescape_flight(html), "channels", "{", "}") or {}
    channels: list[dict] = []
    for raw_name, servers in mapping.items():
        if not isinstance(servers, dict):
            continue
        # Strip a leading "KickBD" provider prefix (e.g. "KickBD Edge" -> "Edge").
        name = re.sub(r"^kickbd\s+", "", raw_name, flags=re.IGNORECASE).strip() or raw_name.strip()
        for server, info in servers.items():
            if isinstance(info, dict) and info.get("url"):
                channels.append({
                    "id": _channel_key(name, server),
                    "name": name,
                    "server": server,
                    "source_url": info["url"],
                })
    return channels


async def get_cached_match_channels(slug: str) -> list[dict]:
    return await cache.get_or_set(
        prefix="kickbd_mc", identifier=slug, factory=lambda: fetch_match_channels(slug), ttl=120
    )


def public_channels(raw: list[dict]) -> list[MatchChannel]:
    return [MatchChannel(id=c["id"], name=c["name"], server=c["server"]) for c in raw]


# --- Stream resolution ---

async def resolve_stream(source_url: str) -> dict | None:
    async with httpx.AsyncClient(timeout=12.0) as client:
        html = await _fetch_text(source_url, client)
    if not html:
        return None
    if "/source/" in source_url:
        return _parse_source_js(html)
    # Generic player page: find an embedded HLS/DASH URL + optional DRM.
    m = (re.search(r"const streamUrl\s*=\s*['\"]([^'\"]+)['\"]", html)
         or re.search(r"(?:source|file)\s*:\s*['\"]([^'\"]+\.(?:m3u8|mpd)[^'\"]*)['\"]", html)
         or re.search(r"https?://[^\"'<>\s]+\.(?:m3u8|mpd)[^\"'<>\s]*", html))
    if not m:
        return None
    url = m.group(1) if m.lastindex else m.group(0)
    result = {"stream_url": url, "stream_type": "dash" if ".mpd" in url else "hls"}
    kid = re.search(r"k_id['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
    kv = re.search(r"k_v['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
    if kid:
        result["drm_kid"] = kid.group(1)
    if kv:
        result["drm_key"] = kv.group(1)
    return result


async def get_cached_stream(slug: str, ch_id: str, source_url: str) -> dict | None:
    return await cache.get_or_set(
        prefix="kickbd_st", identifier=f"{slug}:{ch_id}",
        factory=lambda: resolve_stream(source_url), ttl=45,
    )
