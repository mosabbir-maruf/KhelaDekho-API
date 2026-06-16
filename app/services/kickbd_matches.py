from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
import structlog

from app.models.v2 import KickbdMatch, KickbdTeamInfo
from app.services.cache import cache

logger = structlog.get_logger(__name__)

_SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_HOMEPAGE_URL = "https://kickbd.com"
_LIVE_WINDOW_HOURS = 6

_ATTR_RE = re.compile(r'data-link="([^"]+)"')

_FIXTURE_TIME_RE = re.compile(r'data-utc-time="([^"]+)"')

_SPORT_BADGE_RE = re.compile(
    r'<div\s+class="sport-name-badge">\s*'
    r'<span>([^<]*)</span>\s*'
    r'<span\s+class="title-text">\s*([^<]*?)\s*</span>',
    re.DOTALL,
)

_TEAM_ROW_RE = re.compile(
    r'<div\s+class="fixture-team-row">\s*'
    r'<div\s+class="fixture-logo-box">\s*'
    r'<img\s+src="([^"]+)"\s+alt="([^"]+)"',
    re.DOTALL,
)


def _parse_datetime(utc_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(utc_str)
    except (ValueError, TypeError):
        return None


def _extract_matches_from_html(html: str) -> list[KickbdMatch]:
    matches: list[KickbdMatch] = []
    now = datetime.now(tz=timezone.utc)

    blocks = re.split(r'(?=<div\s+class="event-card")', html)

    for block in blocks[1:]:
        link_match = _ATTR_RE.search(block)
        if not link_match:
            continue
        match_url = link_match.group(1)

        match_slug = match_url.rstrip("/").split("/")[-1]

        time_match = _FIXTURE_TIME_RE.search(block)
        if not time_match:
            continue
        starts_at = _parse_datetime(time_match.group(1))
        if not starts_at:
            continue

        badge_match = _SPORT_BADGE_RE.search(block)
        if badge_match:
            sport_emoji = badge_match.group(1).strip()
            league = badge_match.group(2).strip()
        else:
            sport_emoji = ""
            league = ""

        team_rows = _TEAM_ROW_RE.findall(block)
        if len(team_rows) < 2:
            continue

        team_a = KickbdTeamInfo(name=team_rows[0][1].strip(), logo=team_rows[0][0] or None)
        team_b = KickbdTeamInfo(name=team_rows[1][1].strip(), logo=team_rows[1][0] or None)

        expire_time = starts_at.timestamp() + _LIVE_WINDOW_HOURS * 3600
        is_live = starts_at.timestamp() <= now.timestamp() < expire_time

        matches.append(
            KickbdMatch(
                id=match_slug,
                league=league,
                sport_emoji=sport_emoji,
                team_a=team_a,
                team_b=team_b,
                starts_at=starts_at,
                match_url=match_url,
                is_live=is_live,
            )
        )

    return matches


async def fetch_kickbd_matches() -> list[KickbdMatch]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_HOMEPAGE_URL, headers=_SCRAPE_HEADERS, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        logger.warning("kickbd_matches_fetch_failed", error=str(e))
        return []

    matches = _extract_matches_from_html(html)
    logger.info("kickbd_matches_fetched", count=len(matches), live=sum(1 for m in matches if m.is_live))
    return matches


async def get_cached_kickbd_matches() -> list[KickbdMatch]:
    return await cache.get_or_set(
        prefix="kickbd",
        identifier="matches",
        factory=fetch_kickbd_matches,
        ttl=120,
    )
