from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.rate_limit import APIRateLimiter
from app.models import StandardResponse
from app.models.goal_scores import GoalMatchDetailResponse, GoalPlayerDetailResponse, GoalScoresResponse, GoalTeamDetailResponse
from app.services.goal_scores import (
    get_cached_goal_match_detail,
    get_cached_goal_player_detail,
    get_cached_goal_scores,
    get_cached_goal_team_detail,
)

router = APIRouter(prefix="/api/goal")
rate_limit = APIRateLimiter(requests=60, window=60)


def _filter_data(data: GoalScoresResponse, competition: str | None, status_filter: str | None) -> GoalScoresResponse:
    data = data.model_copy(deep=True)
    if competition:
        q = competition.lower()
        data.competitions = [c for c in data.competitions if q in c.name.lower()]
        data.total_matches = sum(len(c.matches) for c in data.competitions)

    if status_filter:
        status_map = {"live": "LIVE", "result": "RESULT", "fixture": "FIXTURE"}
        mapped = status_map[status_filter]
        for comp in data.competitions:
            comp.matches = [m for m in comp.matches if m.status == mapped]
        data.total_matches = sum(len(c.matches) for c in data.competitions)
        data.competitions = [c for c in data.competitions if c.matches]

    return data


@router.get(
    "/scores",
    response_model=StandardResponse[GoalScoresResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_scores(
    date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    competition: Optional[str] = Query(None, min_length=2, max_length=100),
    status: Optional[str] = Query(None, pattern="^(live|result|fixture)$"),
):
    data = await get_cached_goal_scores(date=date)
    data = _filter_data(data, competition, status)
    return StandardResponse(success=True, data=data)


@router.get(
    "/scores/live",
    response_model=StandardResponse[GoalScoresResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_live_scores(date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    data = await get_cached_goal_scores(date=date)
    return _filter_and_return(data, "LIVE")


@router.get(
    "/scores/fixtures",
    response_model=StandardResponse[GoalScoresResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_fixtures(date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    data = await get_cached_goal_scores(date=date)
    return _filter_and_return(data, "FIXTURE")


@router.get(
    "/scores/results",
    response_model=StandardResponse[GoalScoresResponse],
    dependencies=[Depends(rate_limit)],
)
async def list_results(date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    data = await get_cached_goal_scores(date=date)
    return _filter_and_return(data, "RESULT")


def _filter_and_return(data: GoalScoresResponse, status_val: str) -> StandardResponse[GoalScoresResponse]:
    data = data.model_copy(deep=True)
    for comp in data.competitions:
        comp.matches = [m for m in comp.matches if m.status == status_val]
    data.competitions = [c for c in data.competitions if c.matches]
    data.total_matches = sum(len(c.matches) for c in data.competitions)
    return StandardResponse(success=True, data=data)


@router.get(
    "/competitions",
    dependencies=[Depends(rate_limit)],
)
async def list_competitions(date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    data = await get_cached_goal_scores(date=date)
    comps = [
        {"id": c.id, "name": c.name, "area": c.area, "image_url": c.image_url, "match_count": len(c.matches)}
        for c in data.competitions
    ]
    return StandardResponse(
        success=True,
        data={"competitions": comps, "total": len(comps), "cached_at": data.cached_at.isoformat()},
    )


@router.get(
    "/matches/{match_id}",
    response_model=StandardResponse[GoalMatchDetailResponse],
    dependencies=[Depends(rate_limit)],
)
async def get_match_detail(
    match_id: str,
    slug: str = Query("", min_length=1),
):
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="slug query parameter is required")
    detail = await get_cached_goal_match_detail(slug, match_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    return StandardResponse(
        success=True,
        data=GoalMatchDetailResponse(match=detail),
    )


@router.get(
    "/player/{player_id}",
    response_model=StandardResponse[GoalPlayerDetailResponse],
    dependencies=[Depends(rate_limit)],
)
async def get_player_detail(
    player_id: str,
    player_name: Optional[str] = Query(None, min_length=1, max_length=200),
):
    detail = await get_cached_goal_player_detail(player_id, player_name=player_name)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return StandardResponse(
        success=True,
        data=GoalPlayerDetailResponse(player=detail),
    )


@router.get(
    "/team/{team_id}",
    response_model=StandardResponse[GoalTeamDetailResponse],
    dependencies=[Depends(rate_limit)],
)
async def get_team_detail(
    team_id: str,
    team_name: Optional[str] = Query(None, min_length=1, max_length=200),
):
    detail = await get_cached_goal_team_detail(team_id, team_name=team_name)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return StandardResponse(
        success=True,
        data=GoalTeamDetailResponse(team=detail),
    )
