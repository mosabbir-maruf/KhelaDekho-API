from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Generic, TypeVar, Any

from pydantic import BaseModel, Field


BDT = timezone(timedelta(hours=6))


class TeamInfo(BaseModel):
    name: str
    flag_url: Optional[str] = None


class VoteSummary(BaseModel):
    total: int
    team1_pct: float
    draw_pct: float
    team2_pct: float
    winner: Optional[str] = None


class Match(BaseModel):
    match_id: str
    group: str
    stage: str = "Group Stage"
    team1: TeamInfo
    team2: TeamInfo
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: str = "upcoming"
    vote: Optional[VoteSummary] = None
    countdown_label: Optional[str] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class ChannelInfo(BaseModel):
    key: str
    name: str
    image_url: Optional[str] = None
    category: str = "Sports"
    quality: str = "HD"
    status: str = "live"
    sort_order: int = 99
    total_views: int = 0
    live_viewers: int = 0
    resolution: str = "Auto"
    source_types: List[str] = Field(default_factory=list)
    play_token: Optional[str] = None
    play_exp: Optional[int] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class PlatformStats(BaseModel):
    live_viewers: int = 0
    all_views: int = 0
    active_channels: int = 0
    total_channels: int = 0
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class ScrapeResult(BaseModel):
    matches: List[Match] = Field(default_factory=list)
    channels: List[ChannelInfo] = Field(default_factory=list)
    platform_stats: Optional[PlatformStats] = None
    errors: List[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class MatchListResponse(BaseModel):
    matches: List[Match]
    total: int
    cached_at: datetime


class ChannelListResponse(BaseModel):
    channels: List[ChannelInfo]
    total: int
    cached_at: datetime


class PlatformStatsResponse(BaseModel):
    stats: PlatformStats
    cached_at: datetime


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    uptime_seconds: float = 0
    last_scrape: Optional[datetime] = None


class StreamSource(BaseModel):
    index: int
    url: str
    type: str
    is_primary: bool


class ClearKeyData(BaseModel):
    kid: str
    key: str
    keys: dict[str, str]


class StreamResponse(BaseModel):
    key: str
    name: str
    url: str
    type: str
    drm: Optional[str] = None
    clearkey: Optional[ClearKeyData] = None
    sources: List[StreamSource] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None

