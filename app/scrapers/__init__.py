from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import structlog
from bs4 import BeautifulSoup, Tag

from app.config import BDT
from app.models import Match, TeamInfo, VoteSummary, ChannelInfo, PlatformStats
from app.utils import safe_int, safe_float, clean_text, parse_k_number

logger = structlog.get_logger(__name__)


def parse_matches_from_html(html_or_soup: str | BeautifulSoup) -> list[Match]:
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    matches: list[Match] = []
    seen_ids: set[str] = set()

    match_cards = soup.select(
        ".match-card[data-match-id], "
        ".match-card[data-match-status], "
        "div[data-match-id]"
    )

    for card in match_cards:
        match_id = card.get("data-match-id", "")
        if not match_id:
            team_rows = card.select(".team-row")
            if len(team_rows) >= 2:
                t1 = _extract_team(team_rows[0])
                t2 = _extract_team(team_rows[1])
                start_ts = card.get("data-start-ts", card.get("data-start", "0"))
                t1_slug = re.sub(r'[^a-z0-9]+', '-', t1.name.lower()).strip('-')
                t2_slug = re.sub(r'[^a-z0-9]+', '-', t2.name.lower()).strip('-')
                match_id = f"{t1_slug}-vs-{t2_slug}-{start_ts}"
            else:
                continue

        if not match_id or match_id in seen_ids:
            continue
        seen_ids.add(match_id)

        match = _parse_match_card(card, match_id)
        if match:
            matches.append(match)

    return matches


def _parse_match_card(card: Tag, match_id: str) -> Match | None:
    try:
        group_text = ""
        group_label = card.select_one(".match-group")
        if group_label:
            group_text = clean_text(group_label.get_text())

        team_rows = card.select(".team-row")
        if len(team_rows) < 2:
            badge_section = card.select_one(".mcard-badge")
            if badge_section:
                parent = card
                team_rows = parent.select(".team-row")
        if len(team_rows) < 2:
            return None

        team1 = _extract_team(team_rows[0])
        team2 = _extract_team(team_rows[1])

        stage = _extract_stage(card)
        status = card.get("data-match-status", card.get("data-status", "upcoming"))
        if not status or status == "none":
            status = _infer_status_from_card(card)

        start_ts = safe_int(card.get("data-start-ts", card.get("data-start", "0")))
        end_ts = safe_int(card.get("data-end-ts", card.get("data-end", "0")))

        start_time = None
        end_time = None
        if start_ts:
            start_time = datetime.fromtimestamp(start_ts, tz=BDT)
        if end_ts:
            end_time = datetime.fromtimestamp(end_ts, tz=BDT)

        countdown_label = None
        countdown_el = card.select_one("[data-match-countdown]")
        if countdown_el:
            countdown_label = clean_text(countdown_el.get_text())

        vote = _extract_vote_data(card)

        return Match(
            match_id=match_id,
            group=group_text,
            stage=stage,
            team1=team1,
            team2=team2,
            start_time=start_time,
            end_time=end_time,
            status=status,
            vote=vote,
            countdown_label=countdown_label,
        )
    except Exception as e:
        logger.warning("match_parse_error", match_id=match_id, error=str(e))
        return None


def _extract_team(row: Tag) -> TeamInfo:
    name = ""
    flag_url = None

    name_el = row.select_one(".team-name, .mcard-team b, .mcard-team")
    if name_el:
        name = clean_text(name_el.get_text(strip=True))

    flag_img = row.select_one("img.flag, img.mcard-flag-img, .flag img, img[src*='flagcdn']")
    if flag_img:
        flag_url = flag_img.get("src") or flag_img.get("data-src")

    return TeamInfo(name=name, flag_url=flag_url)


def _extract_stage(card: Tag) -> str:
    stage_el = card.select_one("[data-stage], .group-tag")
    if stage_el:
        text = clean_text(stage_el.get_text())
        if any(kw in text.lower() for kw in ("group", "round", "semi", "final", "quarter")):
            return text

    group_el = card.select_one(".match-group")
    if group_el:
        text = clean_text(group_el.get_text())
        if "group" in text.lower():
            return text

    return "Group Stage"


def _infer_status_from_card(card: Tag) -> str:
    if card.select_one("[data-mode='live'], .live-dot.green"):
        return "live"
    if card.select_one("[data-mode='next']"):
        return "upcoming"
    if card.get("data-match-status") == "finished":
        return "finished"
    classes = card.get("class", [])
    if "live-row" in classes:
        return "live"
    if "is-finished" in classes:
        return "finished"
    return "upcoming"


def _extract_vote_data(card: Tag) -> VoteSummary | None:
    vote_card = card.select_one("[data-vote-card]")
    if not vote_card:
        return None

    try:
        total_text = ""
        total_el = vote_card.select_one("[data-vote-total]")
        if total_el:
            total_text = clean_text(total_el.get_text())

        total = parse_k_number(total_text)

        team1_pct = 0.0
        draw_pct = 0.0
        team2_pct = 0.0
        winner: str | None = None

        rows = vote_card.select("[data-vote-row]")
        for row in rows:
            opt = row.get("data-vote-row", "")
            pct_el = row.select_one(".fan-result-pct")
            pct = safe_float(pct_el.get_text() if pct_el else "0")

            if opt == "team1":
                team1_pct = pct
            elif opt == "draw":
                draw_pct = pct
            elif opt == "team2":
                team2_pct = pct

            if "is-top" in (row.get("class") or []):
                winner = opt

        if not winner:
            winner = _infer_winner(team1_pct, draw_pct, team2_pct)

        if total == 0 and team1_pct == 0 and team2_pct == 0:
            return None

        return VoteSummary(
            total=total,
            team1_pct=team1_pct,
            draw_pct=draw_pct,
            team2_pct=team2_pct,
            winner=winner,
        )
    except Exception as e:
        logger.warning("vote_parse_error", error=str(e))
        return None


def _infer_winner(t1: float, d: float, t2: float) -> str | None:
    if t1 > t2 and t1 > d:
        return "team1"
    if t2 > t1 and t2 > d:
        return "team2"
    if d > t1 and d > t2:
        return "draw"
    return None


def parse_channels_from_html(html_or_soup: str | BeautifulSoup, raw_html: str | None = None) -> tuple[list[ChannelInfo], PlatformStats]:
    soup = html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup, "lxml")
    raw = raw_html or (html_or_soup if isinstance(html_or_soup, str) else str(html_or_soup))
    channels: list[ChannelInfo] = []
    seen_keys: set[str] = set()

    js_channels = _extract_channels_from_js(raw)
    if js_channels:
        channels = js_channels
        for ch in channels:
            seen_keys.add(ch.key)

    platform_stats = _extract_platform_stats(soup)

    return channels, platform_stats


def _extract_channels_from_js(html: str) -> list[ChannelInfo]:
    pattern = r"CHANNELS\s*=\s*(\[.+?\])\s*;"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return []

    try:
        raw_json = match.group(1)
        raw_data = json.loads(raw_json)
    except json.JSONDecodeError:
        return []

    channels: list[ChannelInfo] = []
    for item in raw_data:
        ch = ChannelInfo(
            key=item.get("key", ""),
            name=item.get("name", ""),
            image_url=item.get("image") or None,
            category=item.get("category", "Sports"),
            quality=item.get("quality", "HD"),
            status=item.get("status", "live"),
            sort_order=item.get("sort", 99),
            total_views=item.get("views", 0),
            live_viewers=item.get("live", 0),
            resolution=item.get("resolution", "Auto"),
            source_types=item.get("source_types", []),
            play_token=item.get("play_token"),
            play_exp=item.get("play_exp"),
        )
        if ch.key:
            channels.append(ch)

    return channels


def _extract_platform_stats(soup: BeautifulSoup) -> PlatformStats:
    live_viewers = 0
    all_views = 0
    active_channels = 0
    total_channels = 0

    live_el = soup.select_one(
        "[data-stats-live], #currentLiveCount, .watch-metric.live strong"
    )
    if live_el:
        live_viewers = safe_int(live_el.get_text())

    views_el = soup.select_one(
        "[data-stats-views], #currentViewCount, .watch-metric strong"
    )
    if views_el:
        text = clean_text(views_el.get_text())
        all_views = parse_k_number(text)

    switch_count = soup.select_one(".switch-count")
    if switch_count:
        count_text = clean_text(switch_count.get_text())
        total_channels = safe_int(count_text.split()[0]) if count_text else 0

    return PlatformStats(
        live_viewers=live_viewers,
        all_views=all_views,
        active_channels=active_channels or total_channels,
        total_channels=total_channels,
    )
