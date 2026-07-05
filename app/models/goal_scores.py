from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GoalTeamInfo(BaseModel):
    id: str
    name: str
    code: str = ""
    short: str = ""
    image_url: Optional[str] = None


class GoalPeriod(BaseModel):
    type: str
    minute: int = 0
    extra: int = 0


class GoalRound(BaseModel):
    name: str
    display: bool = True


class GoalPlayerInfo(BaseModel):
    id: str
    name: str
    image_url: Optional[str] = None


class GoalMatchEvent(BaseModel):
    type: str
    side: Optional[str] = None
    period: Optional[GoalPeriod] = None
    player: Optional[GoalPlayerInfo] = None
    scorer: Optional[GoalPlayerInfo] = None
    assist: Optional[GoalPlayerInfo] = None
    in_player: Optional[GoalPlayerInfo] = None
    out_player: Optional[GoalPlayerInfo] = None
    outcome: Optional[str] = None
    decision: Optional[str] = None


class GoalLineupPlayer(BaseModel):
    player: Optional[GoalPlayerInfo] = None
    position: Optional[str] = None
    shirt_number: Optional[int] = None
    score: Optional[float] = None
    is_substitute: bool = False
    formation_position: Optional[str] = None


class GoalTeamLineup(BaseModel):
    formation: Optional[str] = None
    starting_xi: list[GoalLineupPlayer] = Field(default_factory=list)
    substitutes: list[GoalLineupPlayer] = Field(default_factory=list)


class GoalLineups(BaseModel):
    team_a: Optional[GoalTeamLineup] = None
    team_b: Optional[GoalTeamLineup] = None


class GoalCommentaryItem(BaseModel):
    type: str
    period: Optional[GoalPeriod] = None
    text: str = ""
    player: Optional[GoalPlayerInfo] = None
    side: Optional[str] = None


class GoalTopPlayer(BaseModel):
    player: GoalPlayerInfo
    score: float = 0
    team_side: str = "TEAM_A"


class GoalH2HStats(BaseModel):
    team_a_goals: int = 0
    team_a_wins: int = 0
    team_b_goals: int = 0
    team_b_wins: int = 0
    draws: int = 0
    games_over_two_and_half: int = 0
    games_both_teams_scored: int = 0


class GoalStatItem(BaseModel):
    type: str
    team_a: float = 0
    team_b: float = 0


class GoalMatchStats(BaseModel):
    summary: list[GoalStatItem] = Field(default_factory=list)
    attacking: list[GoalStatItem] = Field(default_factory=list)
    passing: list[GoalStatItem] = Field(default_factory=list)
    duels: list[GoalStatItem] = Field(default_factory=list)
    defence: list[GoalStatItem] = Field(default_factory=list)
    discipline: list[GoalStatItem] = Field(default_factory=list)


class GoalMatchDetail(BaseModel):
    id: str
    status: str
    competition_name: str = ""
    competition_area: str = ""
    competition_image_url: Optional[str] = None
    start_date: datetime
    venue: Optional[str] = None
    venue_lat: Optional[float] = None
    venue_lng: Optional[float] = None
    score_team_a: Optional[int] = None
    score_team_b: Optional[int] = None
    half_time_team_a: Optional[int] = None
    half_time_team_b: Optional[int] = None
    full_time_team_a: Optional[int] = None
    full_time_team_b: Optional[int] = None
    extra_time_team_a: Optional[int] = None
    extra_time_team_b: Optional[int] = None
    agg_team_a: Optional[int] = None
    agg_team_b: Optional[int] = None
    penalty_team_a: Optional[int] = None
    penalty_team_b: Optional[int] = None
    team_a: GoalTeamInfo
    team_b: GoalTeamInfo
    team_a_colors: Optional[list[str]] = None
    team_b_colors: Optional[list[str]] = None
    round: Optional[GoalRound] = None
    period: Optional[GoalPeriod] = None
    events: list[GoalMatchEvent] = Field(default_factory=list)
    stats: Optional[GoalMatchStats] = None
    lineups: Optional[GoalLineups] = None
    commentary: list[GoalCommentaryItem] = Field(default_factory=list)
    top_players: list[GoalTopPlayer] = Field(default_factory=list)
    h2h: Optional[GoalH2HStats] = None
    h2h_matches: list[GoalMatch] = Field(default_factory=list)
    scorers_team_a: list[GoalMatchEvent] = Field(default_factory=list)
    scorers_team_b: list[GoalMatchEvent] = Field(default_factory=list)
    red_cards_team_a: int = 0
    red_cards_team_b: int = 0
    last_updated_at: Optional[datetime] = None


class GoalMatchDetailResponse(BaseModel):
    match: GoalMatchDetail
    cached_at: datetime = Field(default_factory=lambda: datetime.now())


class GoalPlayerSeasonStats(BaseModel):
    competition_name: str = ""
    competition_image_url: Optional[str] = None
    season_name: str = ""
    team_image_url: Optional[str] = None
    appearances: int = 0
    starting_eleven: int = 0
    minutes_played: int = 0
    goals: int = 0
    minutes_per_goal: Optional[int] = None
    assists: int = 0
    own_goals: int = 0
    penalty_goals: int = 0
    penalties_missed: int = 0
    shots_on_target: int = 0
    shots_off_target: int = 0
    blocked_shots: int = 0
    goals_outside_box: int = 0
    hit_woodwork: int = 0
    freekick_goals: int = 0
    offsides: int = 0
    corners: int = 0
    crosses: int = 0
    successful_crosses: int = 0
    tackles: int = 0
    clearances: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    fouls_committed: int = 0
    fouls_suffered: int = 0
    goals_conceded: int = 0
    clean_sheets: int = 0
    saves: int = 0
    penalty_saves: int = 0


class GoalPlayerDetail(BaseModel):
    id: str
    name: str
    first_name: str = ""
    last_name: str = ""
    shirt_number: Optional[int] = None
    position: Optional[str] = None
    age: Optional[int] = None
    date_of_birth: Optional[str] = None
    nationality_name: Optional[str] = None
    nationality_image_url: Optional[str] = None
    image_url: Optional[str] = None
    current_team_name: Optional[str] = None
    current_team_id: Optional[str] = None
    current_team_image_url: Optional[str] = None
    stats: list[GoalPlayerSeasonStats] = Field(default_factory=list)


class GoalPlayerDetailResponse(BaseModel):
    player: GoalPlayerDetail
    cached_at: datetime = Field(default_factory=lambda: datetime.now())


class GoalTeamDetail(BaseModel):
    id: str
    name: str
    long_name: str = ""
    short_name: str = ""
    image_url: Optional[str] = None
    recent_matches: list[GoalMatch] = Field(default_factory=list)


class GoalTeamDetailResponse(BaseModel):
    team: GoalTeamDetail
    cached_at: datetime = Field(default_factory=lambda: datetime.now())


class GoalMatch(BaseModel):
    id: str
    start_date: datetime
    status: str
    score_team_a: Optional[int] = None
    score_team_b: Optional[int] = None
    agg_team_a: Optional[int] = None
    agg_team_b: Optional[int] = None
    penalty_team_a: Optional[int] = None
    penalty_team_b: Optional[int] = None
    team_a: GoalTeamInfo
    team_b: GoalTeamInfo
    round: Optional[GoalRound] = None
    period: Optional[GoalPeriod] = None
    red_cards_team_a: int = 0
    red_cards_team_b: int = 0
    venue: Optional[str] = None
    slug: str = ""
    last_updated_at: Optional[datetime] = None


class GoalCompetition(BaseModel):
    id: str
    name: str
    area: str = ""
    image_url: Optional[str] = None
    matches: list[GoalMatch] = Field(default_factory=list)


class GoalScoresResponse(BaseModel):
    competitions: list[GoalCompetition] = Field(default_factory=list)
    total_matches: int = 0
    cached_at: datetime = Field(default_factory=lambda: datetime.now())
