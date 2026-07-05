from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.config import BDT


class Channel(BaseModel):
    id: int
    name: str
    logo: Optional[str] = None
    stream_type: str = "hls"
    stream_url: Optional[str] = None
    drm_kid: Optional[str] = None
    drm_key: Optional[str] = None
    is_alive: bool = False
    cached_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class ChannelListResponse(BaseModel):
    channels: list[Channel]
    total: int
    cached_at: datetime


class Highlight(BaseModel):
    slug: str
    title: str
    thumbnail: Optional[str] = None
    stream_url: Optional[str] = None
    sources: list[dict] = Field(default_factory=list)
    is_alive: bool = False
    cached_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class HighlightListResponse(BaseModel):
    highlights: list[Highlight]
    total: int
    cached_at: datetime


class KickbdTeamInfo(BaseModel):
    name: str
    logo: Optional[str] = None


class KickbdMatch(BaseModel):
    id: str
    league: str
    sport_emoji: str = ""
    team_a: KickbdTeamInfo
    team_b: KickbdTeamInfo
    starts_at: Optional[datetime] = None
    match_url: str
    is_live: bool = False
    cached_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class KickbdMatchListResponse(BaseModel):
    matches: list[KickbdMatch]
    total: int
    cached_at: datetime


class MatchStream(BaseModel):
    name: str = "Stream 1"
    stream_type: str = "hls"
    stream_url: Optional[str] = None
    drm_kid: Optional[str] = None
    drm_key: Optional[str] = None
    is_alive: bool = False
