"""V1 API — Goal Score Provider.

Exposes live scores, fixtures, results and match/player/team detail scraped
from the configured score provider (base URL: ``settings.v1_home_url``).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models import StandardResponse
from app.models.goal_scores import (
    GoalMatchDetailResponse,
    GoalPlayerDetailResponse,
    GoalScoresResponse,
    GoalTeamDetailResponse,
)
from app.services.v1 import (
    get_cached_goal_match_detail,
    get_cached_goal_player_detail,
    get_cached_goal_scores,
    get_cached_goal_team_detail,
)

router = APIRouter(prefix="/api/v1")

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def _filter_data(
    data: GoalScoresResponse, competition: str | None, status_filter: str | None
) -> GoalScoresResponse:
    data = data.model_copy(deep=True)
    if competition:
        q = competition.lower()
        data.competitions = [c for c in data.competitions if q in c.name.lower()]
        data.total_matches = sum(len(c.matches) for c in data.competitions)

    if status_filter:
        status_map = {"live": "LIVE", "result": "RESULT", "fixture": "FIXTURE"}
        mapped = status_map.get(status_filter)
        if not mapped:
            return data
        for comp in data.competitions:
            comp.matches = [m for m in comp.matches if m.status == mapped]
        data.total_matches = sum(len(c.matches) for c in data.competitions)
        data.competitions = [c for c in data.competitions if c.matches]

    return data


@router.get(
    "/scores",
    response_model=StandardResponse[GoalScoresResponse]
)
async def list_scores(
    date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    competition: Optional[str] = Query(None, min_length=2, max_length=100),
    status: Optional[str] = Query(None, pattern="^(live|result|fixture)$"),
):
    """Return scores for a date. Use ``status`` to filter to live / result /
    fixture, and ``competition`` to filter by competition name."""
    data = await get_cached_goal_scores(date=date)
    data = _filter_data(data, competition, status)
    return StandardResponse(success=True, data=data)


@router.get(
    "/competitions"
)
async def list_competitions(date: Optional[str] = Query(None, pattern=_DATE_PATTERN)):
    data = await get_cached_goal_scores(date=date)
    comps = [
        {
            "id": c.id,
            "name": c.name,
            "area": c.area,
            "image_url": c.image_url,
            "match_count": len(c.matches),
        }
        for c in data.competitions
    ]
    return StandardResponse(
        success=True,
        data={
            "competitions": comps,
            "total": len(comps),
            "cached_at": data.cached_at.isoformat(),
        },
    )


@router.get(
    "/matches/{match_id}",
    response_model=StandardResponse[GoalMatchDetailResponse]
)
async def get_match_detail(
    match_id: str,
    slug: str = Query("", min_length=1),
):
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="slug query parameter is required",
        )
    detail = await get_cached_goal_match_detail(slug, match_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return StandardResponse(success=True, data=GoalMatchDetailResponse(match=detail))


@router.get(
    "/player/{player_id}",
    response_model=StandardResponse[GoalPlayerDetailResponse]
)
async def get_player_detail(
    player_id: str,
    player_name: Optional[str] = Query(None, min_length=1, max_length=200),
):
    detail = await get_cached_goal_player_detail(player_id, player_name=player_name)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return StandardResponse(success=True, data=GoalPlayerDetailResponse(player=detail))


@router.get(
    "/team/{team_id}",
    response_model=StandardResponse[GoalTeamDetailResponse]
)
async def get_team_detail(
    team_id: str,
    team_name: Optional[str] = Query(None, min_length=1, max_length=200),
):
    detail = await get_cached_goal_team_detail(team_id, team_name=team_name)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return StandardResponse(success=True, data=GoalTeamDetailResponse(team=detail))
