from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.config import BDT


class ProxybdixChannel(BaseModel):
    id: str
    name: str
    logo: Optional[str] = None
    stream_url: Optional[str] = None
    stream_type: str = "dash"
    drm_kid: Optional[str] = None
    drm_key: Optional[str] = None
    is_alive: bool = False
    cached_at: datetime = Field(default_factory=lambda: datetime.now(BDT))


class ProxybdixChannelListResponse(BaseModel):
    channels: list[ProxybdixChannel]
    total: int
    cached_at: datetime


class ProxybdixStreamResponse(BaseModel):
    id: str
    name: str
    url: str
    type: str
    drm_kid: Optional[str] = None
    drm_key: Optional[str] = None


class ProxybdixStatsResponse(BaseModel):
    online_users: int
    channel_count: int
    cached_at: datetime


class ProxybdixHealthResponse(BaseModel):
    status: str = "ok"
    version: str = "4.0.0"
    uptime_seconds: float = 0
    source: str = "tv.proxybdix.com"
