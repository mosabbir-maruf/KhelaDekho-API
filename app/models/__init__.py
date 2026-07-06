from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    uptime_seconds: float = 0.0


T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None
