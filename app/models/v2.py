from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.config import BDT


class TeamInfo(BaseModel):
    name: str
    logo: Optional[str] = None


class KickbdMatch(BaseModel):
    id: str
    slug: str
    name: str
    sport: str = ""
    status: str = ""
    is_live: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    poster: Optional[str] = None
    team_a: Optional[TeamInfo] = None
    team_b: Optional[TeamInfo] = None


class KickbdMatchListResponse(BaseModel):
    matches: list[KickbdMatch]
    total: int
    cached_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class MatchChannel(BaseModel):
    id: str
    name: str
    server: str


class MatchChannelListResponse(BaseModel):
    slug: str
    channels: list[MatchChannel]
    total: int
    cached_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class StreamResponse(BaseModel):
    name: str
    stream_url: str
    stream_type: str = "hls"
    drm_kid: Optional[str] = None
    drm_key: Optional[str] = None
