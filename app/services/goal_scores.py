from __future__ import annotations

import json
import re
from datetime import datetime

import httpx
import structlog

from app.config import settings
from app.models.goal_scores import (
    GoalCommentaryItem,
    GoalCompetition,
    GoalH2HStats,
    GoalLineupPlayer,
    GoalLineups,
    GoalMatch,
    GoalMatchDetail,
    GoalMatchEvent,
    GoalMatchStats,
    GoalPeriod,
    GoalPlayerDetail,
    GoalPlayerInfo,
    GoalPlayerSeasonStats,
    GoalRound,
    GoalScoresResponse,
    GoalStatItem,
    GoalTeamDetail,
    GoalTeamInfo,
    GoalTeamLineup,
    GoalTopPlayer,
)
from app.services.cache import cache

logger = structlog.get_logger(__name__)

# Base URL comes from env (V1_HOME_URL), never hardcoded. All paths are relative
# to ``settings.v1_home_url``.
_PROVIDER_BASE = settings.v1_home_url.rstrip("/")
_GOAL_LIVE_SCORES_URL = f"{_PROVIDER_BASE}/en/live-scores"
_GOAL_FIXTURES_URL = f"{_PROVIDER_BASE}/en/fixtures/{{date}}"
_GOAL_RESULTS_URL = f"{_PROVIDER_BASE}/en/results/{{date}}"
_GOAL_MATCH_URL = f"{_PROVIDER_BASE}/en-in/match/{{slug}}/{{match_id}}"
_GOAL_PLAYER_URL = f"{_PROVIDER_BASE}/en/player/{{player_id}}"
_GOAL_PLAYER_SLUG_URL = f"{_PROVIDER_BASE}/en/player/{{slug}}/{{player_id}}"
_GOAL_TEAM_URL = f"{_PROVIDER_BASE}/en/team/{{team_id}}"
_GOAL_TEAM_SLUG_URL = f"{_PROVIDER_BASE}/en/team/{{slug}}/{{team_id}}"

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.2 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>', re.DOTALL)

_CACHE_TTL_SCORES = 15
_CACHE_TTL_MATCH = 30


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_team(raw: dict | None) -> GoalTeamInfo:
    if not raw:
        return GoalTeamInfo(id="", name="TBD")
    return GoalTeamInfo(
        id=raw.get("id") or "",
        name=raw.get("name") or raw.get("long") or "TBD",
        code=raw.get("code") or "",
        short=raw.get("short") or "",
        image_url=(raw.get("image") or {}).get("url"),
    )


def _parse_period(raw: dict | None) -> GoalPeriod | None:
    if not raw:
        return None
    return GoalPeriod(
        type=raw.get("type", ""),
        minute=raw.get("minute", 0),
        extra=raw.get("extra", 0),
    )


def _parse_player(raw: dict | None) -> GoalPlayerInfo | None:
    if not raw:
        return None
    return GoalPlayerInfo(
        id=raw.get("id") or "",
        name=raw.get("name") or "",
        image_url=(raw.get("image") or {}).get("url"),
    )


def _parse_match(raw: dict) -> GoalMatch:
    team_a = _parse_team(raw.get("teamA", {}))
    team_b = _parse_team(raw.get("teamB", {}))

    score = raw.get("score")
    score_team_a = score.get("teamA") if score else None
    score_team_b = score.get("teamB") if score else None

    agg = raw.get("agg")
    penalty = raw.get("penalty")
    red_cards = raw.get("redCards") or {}
    venue_raw = raw.get("venue")
    link_raw = raw.get("link") or {}

    return GoalMatch(
        id=raw.get("id", ""),
        start_date=_parse_iso(raw.get("startDate", "")) or datetime.now(),
        status=raw.get("status", "FIXTURE"),
        score_team_a=score_team_a,
        score_team_b=score_team_b,
        agg_team_a=agg.get("teamA") if agg else None,
        agg_team_b=agg.get("teamB") if agg else None,
        penalty_team_a=penalty.get("teamA") if penalty else None,
        penalty_team_b=penalty.get("teamB") if penalty else None,
        team_a=team_a,
        team_b=team_b,
        round=_parse_round(raw.get("round")),
        period=_parse_period(raw.get("period")),
        red_cards_team_a=red_cards.get("teamA", 0),
        red_cards_team_b=red_cards.get("teamB", 0),
        venue=venue_raw.get("name") if venue_raw else None,
        slug=link_raw.get("slug", ""),
        last_updated_at=_parse_iso(raw.get("lastUpdatedAt", "")),
    )


def _parse_round(raw: dict | None) -> GoalRound | None:
    if not raw:
        return None
    return GoalRound(
        name=raw.get("name", ""),
        display=raw.get("display", True),
    )


def _extract_next_data(html: str) -> dict | None:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


async def _fetch_html(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_SCRAPE_HEADERS)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.error("goal_fetch_failed", url=url, error=str(e))
        return None


# ---- Scores (list) ----

def _parse_scores_from_next_data(next_data: dict) -> GoalScoresResponse:
    competitions: list[GoalCompetition] = []
    try:
        live_scores = next_data["props"]["pageProps"]["content"]["liveScores"]
    except (KeyError, TypeError):
        logger.warning("goal_live_scores_not_found_in_next_data")
        return GoalScoresResponse()

    total_matches = 0
    for raw_comp in live_scores:
        comp_raw = raw_comp.get("competition") or {}
        matches_raw = raw_comp.get("matches") or []
        comp = GoalCompetition(
            id=comp_raw.get("id", ""),
            name=comp_raw.get("name", ""),
            area=(comp_raw.get("area") or {}).get("name", ""),
            image_url=(comp_raw.get("image") or {}).get("url"),
        )
        for raw_match in matches_raw:
            comp.matches.append(_parse_match(raw_match))
        total_matches += len(comp.matches)
        competitions.append(comp)

    return GoalScoresResponse(
        competitions=competitions,
        total_matches=total_matches,
        cached_at=datetime.now(),
    )


_BDT_OFFSET = 6  # Bangladesh is UTC+6


def _match_date_in_tz(match_date: datetime, target_date: str) -> bool:
    """Check if a match falls on the target date in Bangladesh timezone (UTC+6)."""
    from datetime import timedelta
    bdt_date = (match_date + timedelta(hours=_BDT_OFFSET)).strftime("%Y-%m-%d")
    return bdt_date == target_date


async def _fetch_scores_for_date(date: str) -> GoalScoresResponse:
    for url_template in [_GOAL_LIVE_SCORES_URL, _GOAL_FIXTURES_URL, _GOAL_RESULTS_URL]:
        url = url_template.format(date=date) if "{date}" in url_template else url_template
        html = await _fetch_html(url)
        if not html:
            continue
        nd = _extract_next_data(html)
        if not nd:
            continue
        result = _parse_scores_from_next_data(nd)
        for comp in result.competitions:
            comp.matches = [m for m in comp.matches if _match_date_in_tz(m.start_date, date)]
        result.competitions = [c for c in result.competitions if c.matches]
        result.total_matches = sum(len(c.matches) for c in result.competitions)
        if result.total_matches > 0:
            return result
    return GoalScoresResponse()


async def fetch_goal_scores(date: str | None = None) -> GoalScoresResponse:
    if date:
        result = await _fetch_scores_for_date(date)
    else:
        html = await _fetch_html(_GOAL_LIVE_SCORES_URL)
        if not html:
            return GoalScoresResponse()
        nd = _extract_next_data(html)
        if not nd:
            return GoalScoresResponse()
        result = _parse_scores_from_next_data(nd)

    logger.info("goal_scores_fetched", competitions=len(result.competitions), total_matches=result.total_matches)
    return result


async def get_cached_goal_scores(date: str | None = None) -> GoalScoresResponse:
    ident = date or "today"
    return await cache.get_or_set(
        prefix="goal",
        identifier=f"scores_{ident}",
        factory=lambda: fetch_goal_scores(date),
        ttl=_CACHE_TTL_SCORES,
    )


# ---- Match Detail ----

def _parse_match_detail_from_next_data(next_data: dict) -> GoalMatchDetail | None:
    try:
        content = next_data["props"]["pageProps"]["content"]
    except (KeyError, TypeError):
        return None

    raw = content.get("match")
    if not raw:
        return None

    team_a = _parse_team(raw.get("teamA", {}))
    team_b = _parse_team(raw.get("teamB", {}))

    score = raw.get("score")
    ht = raw.get("halfTime")
    ft = raw.get("fullTime")
    et = raw.get("extraTime")

    venue_raw = raw.get("venue")
    comp_raw = raw.get("competition") or {}

    team_a_colors_raw = raw.get("teamA", {}).get("colors", [])
    team_b_colors_raw = raw.get("teamB", {}).get("colors", [])

    detail = GoalMatchDetail(
        id=raw.get("id", ""),
        status=raw.get("status", ""),
        competition_name=comp_raw.get("name", ""),
        competition_area=(comp_raw.get("area") or {}).get("name", ""),
        competition_image_url=(comp_raw.get("image") or {}).get("url"),
        start_date=_parse_iso(raw.get("startDate", "")) or datetime.now(),
        venue=venue_raw.get("name") if venue_raw else None,
        venue_lat=venue_raw.get("latitude") if venue_raw else None,
        venue_lng=venue_raw.get("longitude") if venue_raw else None,
        score_team_a=score.get("teamA") if score else None,
        score_team_b=score.get("teamB") if score else None,
        half_time_team_a=ht.get("teamA") if ht else None,
        half_time_team_b=ht.get("teamB") if ht else None,
        full_time_team_a=ft.get("teamA") if ft else None,
        full_time_team_b=ft.get("teamB") if ft else None,
        extra_time_team_a=et.get("teamA") if et else None,
        extra_time_team_b=et.get("teamB") if et else None,
        agg_team_a=(raw.get("agg") or {}).get("teamA") if raw.get("agg") else None,
        agg_team_b=(raw.get("agg") or {}).get("teamB") if raw.get("agg") else None,
        penalty_team_a=(raw.get("penalty") or {}).get("teamA") if raw.get("penalty") else None,
        penalty_team_b=(raw.get("penalty") or {}).get("teamB") if raw.get("penalty") else None,
        team_a=team_a,
        team_b=team_b,
        team_a_colors=[c.get("value") for c in team_a_colors_raw if c.get("value")] or None,
        team_b_colors=[c.get("value") for c in team_b_colors_raw if c.get("value")] or None,
        round=_parse_round(raw.get("round")),
        period=_parse_period(raw.get("period")),
        last_updated_at=_parse_iso(raw.get("lastUpdatedAt", "")),
    )

    # Events
    for e in raw.get("events") or []:
        typename = e.get("__typename", "")
        etype = e.get("type", "")
        player = _parse_player(e.get("player"))
        scorer = _parse_player(e.get("scorer"))
        assist = _parse_player(e.get("assist"))
        in_player = _parse_player(e.get("in"))
        out_player = _parse_player(e.get("out"))

        event = GoalMatchEvent(
            type=etype,
            side=e.get("side"),
            period=_parse_period(e.get("period")),
            player=player,
            scorer=scorer,
            assist=assist,
            in_player=in_player,
            out_player=out_player,
            outcome=e.get("outcome"),
            decision=e.get("decision"),
        )
        detail.events.append(event)

    # Scorers
    scorers_raw = raw.get("scorers") or {}
    for s in scorers_raw.get("teamA", []):
        p = _parse_player(s.get("player"))
        for ev in s.get("events", []):
            detail.scorers_team_a.append(GoalMatchEvent(
                type=ev.get("type", "GOAL"),
                period=_parse_period(ev.get("period")),
                scorer=p,
            ))
    for s in scorers_raw.get("teamB", []):
        p = _parse_player(s.get("player"))
        for ev in s.get("events", []):
            detail.scorers_team_b.append(GoalMatchEvent(
                type=ev.get("type", "GOAL"),
                period=_parse_period(ev.get("period")),
                scorer=p,
            ))

    # Red cards
    red = raw.get("redCards") or {}
    detail.red_cards_team_a = red.get("teamA", 0)
    detail.red_cards_team_b = red.get("teamB", 0)

    # Stats
    raw_stats = raw.get("stats")
    if raw_stats:
        stats = GoalMatchStats()
        category_map = [
            ("summary", "summary"),
            ("attacking", "attacking"),
            ("passing", "passing"),
            ("duels", "duels"),
            ("defence", "defence"),
            ("discipline", "discipline"),
        ]
        for raw_key, model_key in category_map:
            items = raw_stats.get(raw_key, [])
            parsed = []
            for item in items:
                parsed.append(GoalStatItem(
                    type=item.get("type", ""),
                    team_a=float(item.get("teamA", 0)),
                    team_b=float(item.get("teamB", 0)),
                ))
            setattr(stats, model_key, parsed)
        detail.stats = stats

    # Lineups (from match object, NOT tabsInfo which is lazy-loaded)
    detail.lineups = _parse_lineups_from_match(raw)

    # Commentary (filter out lazy-loaded GraphQL placeholders)
    for c in (content.get("tabsInfo") or {}).get("commentary") or []:
        if len(c) <= 1 and not c.get("text") and not c.get("player"):
            continue
        detail.commentary.append(GoalCommentaryItem(
            type=c.get("type", ""),
            period=_parse_period(c.get("period")),
            text=c.get("text", ""),
            player=_parse_player(c.get("player")),
            side=c.get("side"),
        ))

    # Fallback: generate commentary from match events if real commentary unavailable
    if not detail.commentary:
        sorted_events = sorted(detail.events, key=lambda e: (e.period.minute if e.period else 999, e.period.extra if e.period else 0))
        side_label = {None: "", "TEAM_A": f" ({detail.team_a.name})", "TEAM_B": f" ({detail.team_b.name})"}
        for e in sorted_events:
            if e.type == "PERIOD_FIRST_HALF":
                detail.commentary.append(GoalCommentaryItem(type="PERIOD", period=e.period, text="First Half begins"))
            elif e.type == "PERIOD_SECOND_HALF":
                detail.commentary.append(GoalCommentaryItem(type="PERIOD", period=e.period, text="Second Half begins"))
            elif e.type == "PERIOD_HALF_TIME":
                detail.commentary.append(GoalCommentaryItem(type="PERIOD", period=e.period, text="Half Time"))
            elif e.type == "PERIOD_MATCH_END":
                detail.commentary.append(GoalCommentaryItem(type="PERIOD", period=e.period, text="Match ended"))
            elif "GOAL" in e.type:
                scorer = e.scorer or e.player
                name = scorer.name if scorer else "Unknown"
                detail.commentary.append(GoalCommentaryItem(
                    type=e.type, period=e.period, text=f"Goal scored by {name}{side_label.get(e.side, '')}",
                    player=scorer, side=e.side,
                ))
            elif "CARD_YELLOW" in e.type:
                name = e.player.name if e.player else "Unknown"
                detail.commentary.append(GoalCommentaryItem(
                    type=e.type, period=e.period, text=f"Yellow Card - {name}{side_label.get(e.side, '')}",
                    player=e.player, side=e.side,
                ))
            elif "CARD_RED" in e.type:
                name = e.player.name if e.player else "Unknown"
                detail.commentary.append(GoalCommentaryItem(
                    type=e.type, period=e.period, text=f"Red Card - {name}{side_label.get(e.side, '')}",
                    player=e.player, side=e.side,
                ))
            elif "SUBSTITUTION" in e.type:
                in_name = e.in_player.name if e.in_player else "Unknown"
                out_name = e.out_player.name if e.out_player else "Unknown"
                detail.commentary.append(GoalCommentaryItem(
                    type=e.type, period=e.period, text=f"Substitution - {in_name} replaces {out_name}{side_label.get(e.side, '')}",
                    player=e.in_player, side=e.side,
                ))
            elif "VAR" in e.type and e.decision:
                decision = e.decision or ""
                detail.commentary.append(GoalCommentaryItem(
                    type=e.type, period=e.period, text=f"VAR - {decision}{side_label.get(e.side, '')}",
                    side=e.side,
                ))

    # Top players
    top_players_raw = (content.get("tabsInfo") or {}).get("topPlayers")
    if isinstance(top_players_raw, dict):
        for side_key in ("teamA", "teamB"):
            players_list = top_players_raw.get(side_key, [])
            for p in players_list:
                pl = _parse_player(p.get("player"))
                if pl:
                    detail.top_players.append(GoalTopPlayer(
                        player=pl,
                        score=p.get("score", 0),
                        team_side="TEAM_A" if side_key == "teamA" else "TEAM_B",
                    ))

    # Fallback: generate top players from lineup scores
    if not detail.top_players and detail.lineups:
        for team_key, team_side in [("team_a", "TEAM_A"), ("team_b", "TEAM_B")]:
            t = getattr(detail.lineups, team_key)
            if not t:
                continue
            all_players = t.starting_xi + t.substitutes
            for lp in all_players:
                if lp.player and lp.score is not None:
                    detail.top_players.append(GoalTopPlayer(
                        player=GoalPlayerInfo(id=lp.player.id, name=lp.player.name, image_url=lp.player.image_url),
                        score=lp.score,
                        team_side=team_side,
                    ))

    # H2H
    h2h_raw = content.get("h2h")
    if h2h_raw:
        stats = h2h_raw.get("stats") or {}
        detail.h2h = GoalH2HStats(
            team_a_goals=stats.get("teamAGoals", 0),
            team_a_wins=stats.get("teamAWins", 0),
            team_b_goals=stats.get("teamBGoals", 0),
            team_b_wins=stats.get("teamBWins", 0),
            draws=stats.get("draws", 0),
            games_over_two_and_half=stats.get("gamesOverTwoAndHalf", 0),
            games_both_teams_scored=stats.get("gamesBothTeamsScored", 0),
        )
        for hm in h2h_raw.get("matches") or []:
            detail.h2h_matches.append(_parse_match(hm))

    return detail


def _parse_lineup_player(raw: dict) -> GoalLineupPlayer:
    person = raw.get("person") or {}
    pl = _parse_player(person)
    pitch = raw.get("pitchPosition") or {}
    formation_str = f"x:{pitch.get('x')},y:{pitch.get('y')}" if pitch else None
    return GoalLineupPlayer(
        player=pl,
        shirt_number=raw.get("shirtNumber"),
        score=raw.get("score"),
        is_substitute=False,
        formation_position=formation_str,
    )


def _parse_lineups_from_match(raw_match: dict) -> GoalLineups | None:
    raw_lineups = raw_match.get("lineups")
    if not raw_lineups:
        return None
    lineups = GoalLineups()
    for side_key, team_key in [("teamA", "team_a"), ("teamB", "team_b")]:
        team_data = raw_lineups.get(side_key)
        if not team_data:
            continue
        tl = GoalTeamLineup(formation=team_data.get("formation"))
        for entry in team_data.get("lineup") or []:
            lp = _parse_lineup_player(entry)
            tl.starting_xi.append(lp)
        for entry in team_data.get("substitutes") or []:
            lp = _parse_lineup_player(entry)
            lp.is_substitute = True
            tl.substitutes.append(lp)
        setattr(lineups, team_key, tl)
    return lineups


async def fetch_goal_match_detail(slug: str, match_id: str) -> GoalMatchDetail | None:
    url = _GOAL_MATCH_URL.format(slug=slug, match_id=match_id)
    html = await _fetch_html(url)
    if not html:
        return None
    next_data = _extract_next_data(html)
    if not next_data:
        return None
    detail = _parse_match_detail_from_next_data(next_data)
    if detail:
        logger.info("goal_match_fetched", match_id=match_id, status=detail.status)
    return detail


async def get_cached_goal_match_detail(slug: str, match_id: str) -> GoalMatchDetail | None:
    return await cache.get_or_set(
        prefix="goal_match",
        identifier=match_id,
        factory=lambda: fetch_goal_match_detail(slug, match_id),
        ttl=_CACHE_TTL_MATCH,
    )


# ---- Player Detail ----

_CACHE_TTL_PLAYER = 300


def _to_slug(name: str) -> str:
    import re as _re
    s = name.lower().strip()
    s = _re.sub(r"[^a-z0-9\s-]", "", s)
    s = _re.sub(r"\s+", "-", s)
    s = _re.sub(r"-+", "-", s)
    return s.strip("-")


def _parse_player_detail_from_next_data(next_data: dict) -> GoalPlayerDetail | None:
    try:
        props = next_data["props"]["pageProps"]
        page = props.get("page", {})
        content = page.get("content") or props.get("content", {})
    except (KeyError, TypeError):
        return None

    raw_player = content.get("player")
    if not raw_player:
        raw_player = content
        if not raw_player.get("firstName"):
            return None

    player_id = raw_player.get("id", "")
    player = GoalPlayerDetail(
        id=player_id,
        name=raw_player.get("name", ""),
        first_name=raw_player.get("firstName", ""),
        last_name=raw_player.get("lastName", ""),
        shirt_number=raw_player.get("shirtNumber"),
        position=raw_player.get("position"),
        age=raw_player.get("age"),
        date_of_birth=raw_player.get("dateOfBirth"),
        nationality_name=(raw_player.get("nationality") or {}).get("name"),
        nationality_image_url=((raw_player.get("nationality") or {}).get("image") or {}).get("url"),
        image_url=(raw_player.get("image") or {}).get("url"),
        current_team_name=(raw_player.get("team") or {}).get("name"),
        current_team_id=(raw_player.get("team") or {}).get("id"),
        current_team_image_url=((raw_player.get("team") or {}).get("image") or {}).get("url"),
    )

    for s in raw_player.get("stats") or []:
        comp_raw = s.get("competition") or {}
        season_raw = s.get("season") or {}
        raw_stats = s.get("stats") or {}
        team_raw = s.get("team") or {}

        season = GoalPlayerSeasonStats(
            competition_name=comp_raw.get("name", ""),
            competition_image_url=(comp_raw.get("image") or {}).get("url"),
            season_name=season_raw.get("name", ""),
            team_image_url=(team_raw.get("image") or {}).get("url"),
            appearances=raw_stats.get("appearances", 0) or 0,
            starting_eleven=raw_stats.get("startingEleven", 0) or 0,
            minutes_played=raw_stats.get("minutesPlayed", 0) or 0,
            goals=raw_stats.get("goals", 0) or 0,
            minutes_per_goal=raw_stats.get("minutesPerGoal"),
            assists=raw_stats.get("assists", 0) or 0,
            own_goals=raw_stats.get("ownGoals", 0) or 0,
            penalty_goals=raw_stats.get("penaltyGoals", 0) or 0,
            penalties_missed=raw_stats.get("penaltiesMissed", 0) or 0,
            shots_on_target=raw_stats.get("shotsOnTarget", 0) or 0,
            shots_off_target=raw_stats.get("shotsOffTarget", 0) or 0,
            blocked_shots=raw_stats.get("blockedShots", 0) or 0,
            goals_outside_box=raw_stats.get("goalsOutsideBox", 0) or 0,
            hit_woodwork=raw_stats.get("hitWoodwork", 0) or 0,
            freekick_goals=raw_stats.get("freekickGoals", 0) or 0,
            offsides=raw_stats.get("offsides", 0) or 0,
            corners=raw_stats.get("corners", 0) or 0,
            crosses=raw_stats.get("crosses", 0) or 0,
            successful_crosses=raw_stats.get("successfulCrosses", 0) or 0,
            tackles=raw_stats.get("tackles", 0) or 0,
            clearances=raw_stats.get("clearances", 0) or 0,
            yellow_cards=raw_stats.get("yellowCards", 0) or 0,
            red_cards=raw_stats.get("redCards", 0) or 0,
            fouls_committed=raw_stats.get("foulsCommited", raw_stats.get("foulsCommitted", 0)) or 0,
            fouls_suffered=raw_stats.get("foulsSuffered", 0) or 0,
            goals_conceded=raw_stats.get("goalsConceded", 0) or 0,
            clean_sheets=raw_stats.get("cleanSheets", 0) or 0,
            saves=raw_stats.get("saves", 0) or 0,
            penalty_saves=raw_stats.get("penaltySaves", 0) or 0,
        )
        player.stats.append(season)

    logger.info("goal_player_fetched", player_id=player_id, name=player.name)
    return player


async def fetch_goal_player_detail(player_id: str, player_name: str | None = None) -> GoalPlayerDetail | None:
    url = _GOAL_PLAYER_URL.format(player_id=player_id)
    html = await _fetch_html(url)
    if not html and player_name:
        slug = _to_slug(player_name)
        url = _GOAL_PLAYER_SLUG_URL.format(slug=slug, player_id=player_id)
        html = await _fetch_html(url)
    if not html:
        return None
    next_data = _extract_next_data(html)
    if not next_data:
        return None
    return _parse_player_detail_from_next_data(next_data)


async def get_cached_goal_player_detail(player_id: str, player_name: str | None = None) -> GoalPlayerDetail | None:
    return await cache.get_or_set(
        prefix="goal_player",
        identifier=player_id,
        factory=lambda: fetch_goal_player_detail(player_id, player_name),
        ttl=_CACHE_TTL_PLAYER,
    )


# ---- Team Detail ----

_CACHE_TTL_TEAM = 300


def _parse_team_detail_from_next_data(next_data: dict) -> GoalTeamDetail | None:
    try:
        props = next_data["props"]["pageProps"]
        page = props.get("page", {})
        content = page.get("content") or props.get("content", {})
    except (KeyError, TypeError):
        return None

    raw_team = content.get("team")
    if not raw_team:
        return None

    team_id = raw_team.get("id", "")
    team = GoalTeamDetail(
        id=team_id,
        name=raw_team.get("name", ""),
        long_name=raw_team.get("longName", ""),
        short_name=raw_team.get("shortName", ""),
        image_url=(raw_team.get("image") or {}).get("url"),
    )

    for rm in content.get("summaryMatches") or []:
        match_raw = rm.get("match") or rm
        parsed = _parse_match(match_raw)
        team.recent_matches.append(parsed)

    logger.info("goal_team_fetched", team_id=team_id, name=team.name, matches=len(team.recent_matches))
    return team


async def fetch_goal_team_detail(team_id: str, team_name: str | None = None) -> GoalTeamDetail | None:
    url = _GOAL_TEAM_URL.format(team_id=team_id)
    html = await _fetch_html(url)
    if not html and team_name:
        slug = _to_slug(team_name)
        url = _GOAL_TEAM_SLUG_URL.format(slug=slug, team_id=team_id)
        html = await _fetch_html(url)
    if not html:
        return None
    next_data = _extract_next_data(html)
    if not next_data:
        return None
    return _parse_team_detail_from_next_data(next_data)


async def get_cached_goal_team_detail(team_id: str, team_name: str | None = None) -> GoalTeamDetail | None:
    return await cache.get_or_set(
        prefix="goal_team",
        identifier=team_id,
        factory=lambda: fetch_goal_team_detail(team_id, team_name),
        ttl=_CACHE_TTL_TEAM,
    )
