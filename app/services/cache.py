from __future__ import annotations

import asyncio
from typing import Any

import structlog
from cachetools import TTLCache

logger = structlog.get_logger(__name__)


class CacheService:
    def __init__(self):
        self._local_cache: TTLCache = TTLCache(maxsize=5000, ttl=120)
        self._lock = asyncio.Lock()

    def _cache_key(self, prefix: str, identifier: str) -> str:
        return f"kheladekho:{prefix}:{identifier}"

    async def get(self, prefix: str, identifier: str) -> Any | None:
        key = self._cache_key(prefix, identifier)
        return self._local_cache.get(key)

    async def set(self, prefix: str, identifier: str, value: Any, ttl: int = 120):
        key = self._cache_key(prefix, identifier)
        self._local_cache[key] = value

    async def get_or_set(
        self,
        prefix: str,
        identifier: str,
        factory,
        ttl: int = 120,
    ) -> Any:
        cached = await self.get(prefix, identifier)
        if cached is not None:
            return cached

        # Cache stampede protection using async lock
        async with self._lock:
            # Double-check if another concurrent request already populated the cache
            cached = await self.get(prefix, identifier)
            if cached is not None:
                return cached

            value = await factory()
            await self.set(prefix, identifier, value, ttl)
            return value

    async def invalidate(self, prefix: str, identifier: str | None = None):
        if identifier:
            key = self._cache_key(prefix, identifier)
            self._local_cache.pop(key, None)
        else:
            self._local_cache.clear()


cache = CacheService()

