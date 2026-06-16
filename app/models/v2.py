from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.config import BDT


class SportzfyTeamInfo(BaseModel):
    name: str
    logo: Optional[str] = None


class SportzfyEvent(BaseModel):
    id: str
    parent: str
    enc_parent: str
    sport: str
    league: str
    round: str = ""
    team_a: SportzfyTeamInfo
    team_b: SportzfyTeamInfo
    starts_at: Optional[datetime] = None
    is_live: bool = False
    status: str = "upcoming"
    league_icon: Optional[str] = None
    priority: int = 0
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class SportzfyEventListResponse(BaseModel):
    events: list[SportzfyEvent]
    total: int
    cached_at: datetime


class SportzfyStatsResponse(BaseModel):
    total_events: int
    live_events: int
    upcoming_events: int
    sports_count: int
    leagues_count: int
    cached_at: datetime


class SportzfyHealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"
    uptime_seconds: float = 0
    source: str = "sportzfytvlive.xyz"


class SportzfyStream(BaseModel):
    id: str
    label: str
    stream_type: str
    stream_url: str
    drm_kid: Optional[str] = None
    drm_key: Optional[str] = None
    sort_order: int = 0


class SportzfyPlaybackResponse(BaseModel):
    ok: bool
    parent: str
    streams: list[SportzfyStream] = Field(default_factory=list)


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
