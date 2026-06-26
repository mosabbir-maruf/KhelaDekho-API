from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import httpx
import structlog

from urllib.parse import urlparse

from app.config import settings
from app.models.v2 import Channel, Highlight
from app.services.cache import cache

logger = structlog.get_logger(__name__)

_HOMEPAGE_URL = settings.v2_home_url
_HOME_NETLOC = urlparse(_HOMEPAGE_URL).netloc
_CDN_NETLOC = f"cdn.{_HOME_NETLOC}"

_SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_DECRYPT_KEY = "999999859198"

_WATCH_RE = re.compile(
    rf'href=["\']{re.escape(_HOMEPAGE_URL)}/watch/(\d+)["\'][^>]*>.*?'
    rf'<img[^>]*src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']+)["\']',
    re.DOTALL,
)
_HIGHLIGHT_RE = re.compile(
    rf'href=["\']{re.escape(_HOMEPAGE_URL)}/highlights/([^"\']+)["\'][^>]*>',
)


def _decrypt_source(payload_urlenc: str) -> str:
    decoded = urllib.parse.unquote(payload_urlenc)
    r = ""
    for i, ch in enumerate(decoded):
        r += chr((ord(ch) + 5) ^ int(_DECRYPT_KEY[i % len(_DECRYPT_KEY)]))
    return r


def _detect_stream_type(url: str) -> str:
    if ".mpd" in url:
        return "dash"
    return "hls"


def _parse_source_js(html: str) -> dict | None:
    match = re.search(r'var _p\s*=\s*"([^"]+)"', html)
    if not match:
        return None
    decrypted = _decrypt_source(match.group(1))
    url_match = re.search(r"window\.player\.load\('([^']+)'\)", decrypted)
    kid_match = re.search(r"k_id='([^']+)'", decrypted)
    kv_match = re.search(r"k_v='([^']+)'", decrypted)
    if not url_match:
        return None
    result = {
        "stream_url": url_match.group(1),
        "stream_type": _detect_stream_type(url_match.group(1)),
    }
    if kid_match:
        result["drm_kid"] = kid_match.group(1)
    if kv_match:
        result["drm_key"] = kv_match.group(1)
    return result


async def _fetch_text(url: str, client: httpx.AsyncClient | None = None) -> str | None:
    close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(url, headers=_SCRAPE_HEADERS, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("tv_fetch_failed", url=url, error=str(e))
        return None
    finally:
        if close_client:
            await client.aclose()


async def _extract_channel_list() -> list[dict]:
    html = await _fetch_text(_HOMEPAGE_URL)
    if not html:
        return []
    channels: list[dict] = []
    for match in _WATCH_RE.finditer(html):
        cid = int(match.group(1))
        logo = match.group(2)
        name = re.sub(r'^KickBD\s+', '', match.group(3).strip(), flags=re.IGNORECASE)
        channels.append({"id": cid, "name": name, "logo": logo})
    seen = set()
    unique = []
    for ch in channels:
        if ch["id"] not in seen:
            seen.add(ch["id"])
            unique.append(ch)
    return unique


async def _extract_iframe_url(channel_id: int, client: httpx.AsyncClient) -> str | None:
    html = await _fetch_text(f"{_HOMEPAGE_URL}/watch/{channel_id}", client)
    if not html:
        return None
    match = re.search(r'<iframe[^>]*src=["\']([^"\']+)["\'][^>]*>', html)
    return match.group(1) if match else None


async def _extract_stream_from_source(url: str, client: httpx.AsyncClient) -> dict | None:
    html = await _fetch_text(url, client)
    if not html:
        return None
    return _parse_source_js(html)


async def _extract_stream_from_yagaverse(url: str, client: httpx.AsyncClient) -> dict | None:
    html = await _fetch_text(url, client)
    if not html:
        return None
    match = re.search(r"const streamUrl\s*=\s*'([^']+)'", html)
    if match:
        return {"stream_url": match.group(1), "stream_type": "hls"}
    return None


async def _extract_stream_from_player(url: str, client: httpx.AsyncClient) -> dict | None:
    html = await _fetch_text(url, client)
    if not html:
        return None
    for pattern in [r'https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*', r'https?://[^"\'<>\s]+\.mpd[^"\'<>\s]*']:
        match = re.search(pattern, html)
        if match:
            stream_url = match.group()
            result = {
                "stream_url": stream_url,
                "stream_type": _detect_stream_type(stream_url),
            }
            kid = re.search(r"k_id['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
            kv = re.search(r"k_v['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
            if kid:
                result["drm_kid"] = kid.group(1)
            if kv:
                result["drm_key"] = kv.group(1)
            return result
    return None


async def _extract_stream_from_soccerball(url: str, client: httpx.AsyncClient) -> dict | None:
    html = await _fetch_text(url, client)
    if not html:
        return None
    match = re.search(r'https?://[^"\'<>\s]+s\d+\.php[^"\'<>\s]*', html)
    if match:
        proxy_url = match.group()
        proxy_html = await _fetch_text(proxy_url, client)
        if proxy_html:
            m3u8s = re.findall(r'https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*', proxy_html)
            if m3u8s:
                return {"stream_url": m3u8s[0], "stream_type": "hls"}
    m3u8s = re.findall(r'https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*', html)
    for m in m3u8s:
        if "rumble" in m or "chunklist" in m:
            return {"stream_url": m, "stream_type": "hls"}
    if m3u8s:
        return {"stream_url": m3u8s[0], "stream_type": "hls"}
    return None


async def _extract_stream_url(iframe_url: str, client: httpx.AsyncClient) -> dict | None:
    if not iframe_url:
        return None
    if f"{_HOME_NETLOC}/source/" in iframe_url:
        return await _extract_stream_from_source(iframe_url, client)
    elif "kick.yagaverse.net" in iframe_url:
        return await _extract_stream_from_yagaverse(iframe_url, client)
    elif f"{_HOME_NETLOC}/player/" in iframe_url:
        return await _extract_stream_from_player(iframe_url, client)
    elif "soccerball.st" in iframe_url:
        return await _extract_stream_from_soccerball(iframe_url, client)
    else:
        return await _extract_stream_from_player(iframe_url, client)


async def _verify_stream(
    stream_url: str,
    client: httpx.AsyncClient,
    drm_kid: str | None = None,
    stream_type: str = "hls",
) -> bool:
    is_drm_dash = bool(drm_kid) and stream_type == "dash"
    try:
        req = await client.get(
            stream_url,
            headers={
                **_SCRAPE_HEADERS,
                "Referer": f"{_HOMEPAGE_URL}/",
                "Origin": _HOMEPAGE_URL,
            },
            timeout=5.0,
            follow_redirects=True,
        )
        if is_drm_dash:
            return req.is_success or req.status_code == 403
        return req.is_success
    except Exception:
        return False


async def fetch_all_channels() -> list[Channel]:
    channels_raw = await _extract_channel_list()
    if not channels_raw:
        return []

    async with httpx.AsyncClient(timeout=10.0) as client:
        iframe_results = await asyncio.gather(
            *[_extract_iframe_url(ch["id"], client) for ch in channels_raw],
            return_exceptions=True,
        )
        channels_with_iframe = []
        for ch, iframe in zip(channels_raw, iframe_results):
            if isinstance(iframe, str):
                ch["iframe_url"] = iframe
                channels_with_iframe.append(ch)
            else:
                channels_with_iframe.append(ch)

        stream_results = await asyncio.gather(
            *[_extract_stream_url(ch.get("iframe_url", ""), client) for ch in channels_with_iframe],
            return_exceptions=True,
        )

    async with httpx.AsyncClient(timeout=5.0) as verify_client:
        verify_tasks = []
        for ch, stream_data in zip(channels_with_iframe, stream_results):
            if isinstance(stream_data, dict) and stream_data.get("stream_url"):
                verify_tasks.append(
                    _verify_stream(
                        stream_data["stream_url"],
                        verify_client,
                        stream_data.get("drm_kid"),
                        stream_data.get("stream_type", "hls"),
                    )
                )
            else:
                verify_tasks.append(asyncio.sleep(0, result=False))

        verify_results = await asyncio.gather(*verify_tasks, return_exceptions=True)

    channels: list[Channel] = []
    for i, ch in enumerate(channels_raw):
        stream_data = stream_results[i] if i < len(stream_results) else None
        is_alive = verify_results[i] if i < len(verify_results) else False

        if isinstance(stream_data, dict):
            alive = is_alive and bool(stream_data.get("stream_url"))
            channels.append(
                Channel(
                    id=ch["id"],
                    name=ch["name"],
                    logo=ch.get("logo"),
                    stream_type=stream_data.get("stream_type", "hls"),
                    stream_url=stream_data.get("stream_url") if alive else None,
                    drm_kid=stream_data.get("drm_kid") if alive else None,
                    drm_key=stream_data.get("drm_key") if alive else None,
                    is_alive=alive,
                )
            )
        else:
            channels.append(
                Channel(
                    id=ch["id"],
                    name=ch["name"],
                    logo=ch.get("logo"),
                    is_alive=False,
                )
            )

    logger.info("tv_channels_fetched", count=len(channels), alive=sum(1 for c in channels if c.is_alive))
    return channels


async def get_cached_channels() -> list[Channel]:
    return await cache.get_or_set(
        prefix="tv",
        identifier="channels",
        factory=fetch_all_channels,
        ttl=120,
    )


CACHE_SEM = asyncio.Lock()


async def get_cached_channel(channel_id: int) -> Channel | None:
    all_channels = await get_cached_channels()
    for ch in all_channels:
        if ch.id == channel_id:
            return ch
    return None


# --- Highlights ---

async def _extract_highlight_list() -> list[dict]:
    html = await _fetch_text(_HOMEPAGE_URL)
    if not html:
        return []
    highlights: list[dict] = []
    for match in _HIGHLIGHT_RE.finditer(html):
        slug = match.group(1)
        highlights.append({"slug": slug})
    seen = set()
    unique = []
    for h in highlights:
        if h["slug"] not in seen:
            seen.add(h["slug"])
            unique.append(h)
    return unique


async def _extract_highlight_detail(slug: str, client: httpx.AsyncClient) -> dict | None:
    html = await _fetch_text(f"{_HOMEPAGE_URL}/highlights/{slug}", client)
    if not html:
        return None
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html)
    title = re.sub(r'\s*\|\|\s*.*', '', title_match.group(1)).strip() if title_match else slug

    iframe_match = re.search(r'<iframe[^>]*src=["\']([^"\']+)["\'][^>]*>', html)
    if not iframe_match:
        return {"slug": slug, "title": title, "stream_url": None, "sources": [], "is_alive": False}

    stream_url = iframe_match.group(1)
    sources = []
    final_url = None

    if f"{_CDN_NETLOC}/stream.php" in stream_url:
        inner_html = await _fetch_text(stream_url, client)
        if inner_html:
            payload_match = re.search(r'securePayload\s*=\s*"([^"]+)"', inner_html)
            if payload_match:
                try:
                    import base64
                    decoded_url = base64.b64decode(payload_match.group(1)).decode()
                    player_html = await _fetch_text(decoded_url, client)
                    if player_html:
                        sources_raw = re.findall(
                            r'\{[^}]*"file"\s*:\s*"([^"]+)"[^}]*\}', player_html
                        )
                        labels = re.findall(r'"label"\s*:\s*"([^"]+)"', player_html)
                        for i, src in enumerate(sources_raw):
                            label = labels[i] if i < len(labels) else f"Stream {i}"
                            sources.append({"label": label, "url": src})
                        if sources_raw:
                            final_url = sources_raw[0]
                except Exception:
                    pass

    return {
        "slug": slug,
        "title": title,
        "stream_url": final_url or (stream_url if not stream_url.startswith(f"https://{_CDN_NETLOC}/stream.php") else None),
        "sources": sources,
        "is_alive": bool(final_url),
    }


async def fetch_all_highlights() -> list[Highlight]:
    raw = await _extract_highlight_list()
    if not raw:
        return []

    async with httpx.AsyncClient(timeout=10.0) as client:
        details = await asyncio.gather(
            *[_extract_highlight_detail(h["slug"], client) for h in raw],
            return_exceptions=True,
        )

    highlights: list[Highlight] = []
    for d in details:
        if isinstance(d, dict):
            highlights.append(
                Highlight(
                    slug=d.get("slug", ""),
                    title=d.get("title", ""),
                    thumbnail=None,
                    stream_url=d.get("stream_url"),
                    sources=d.get("sources", []),
                    is_alive=d.get("is_alive", False),
                )
            )

    logger.info("tv_highlights_fetched", count=len(highlights))
    return highlights


async def get_cached_highlights() -> list[Highlight]:
    return await cache.get_or_set(
        prefix="tv",
        identifier="highlights",
        factory=fetch_all_highlights,
        ttl=120,
    )


async def get_cached_highlight(slug: str) -> Highlight | None:
    all_highlights = await get_cached_highlights()
    for h in all_highlights:
        if h.slug == slug:
            return h
    return None
