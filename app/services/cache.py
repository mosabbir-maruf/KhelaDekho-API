from __future__ import annotations

import asyncio
import hashlib
import json
import pickle
from typing import Any

import structlog
from cachetools import TTLCache

from app.config import settings

logger = structlog.get_logger(__name__)

try:
    import redis.asyncio as aioredis
    _redis: aioredis.Redis | None = None
    REDIS_AVAILABLE = True
except ImportError:
    _redis = None
    REDIS_AVAILABLE = False


class CacheService:
    def __init__(self):
        self._local_cache: TTLCache = TTLCache(maxsize=5000, ttl=120)
        self._redis: aioredis.Redis | None = None
        self._redis_connected = False
        self._lock = asyncio.Lock()

    async def _connect_redis(self):
        if not REDIS_AVAILABLE or self._redis_connected:
            return
        async with self._lock:
            if self._redis_connected:
                return
            try:
                self._redis = aioredis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )
                await self._redis.ping()
                self._redis_connected = True
                logger.info("redis_connected", url=settings.redis_url)
            except Exception as e:
                logger.warning("redis_unavailable", error=str(e))
                self._redis = None
                self._redis_connected = True

    def _cache_key(self, prefix: str, identifier: str) -> str:
        return f"kheladekho:{prefix}:{identifier}"

    async def get(self, prefix: str, identifier: str) -> Any | None:
        key = self._cache_key(prefix, identifier)

        cached = self._local_cache.get(key)
        if cached is not None:
            return cached

        await self._connect_redis()
        if self._redis:
            try:
                raw = await self._redis.get(key)
                if raw:
                    value = pickle.loads(raw)
                    self._local_cache[key] = value
                    return value
            except Exception as e:
                logger.warning("redis_get_error", key=key, error=str(e))

        return None

    async def set(self, prefix: str, identifier: str, value: Any, ttl: int = 120):
        key = self._cache_key(prefix, identifier)
        self._local_cache[key] = value

        await self._connect_redis()
        if self._redis:
            try:
                await self._redis.setex(key, ttl, pickle.dumps(value))
            except Exception as e:
                logger.warning("redis_set_error", key=key, error=str(e))

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
        await self._connect_redis()
        if identifier:
            key = self._cache_key(prefix, identifier)
            self._local_cache.pop(key, None)
            if self._redis:
                try:
                    await self._redis.delete(key)
                except Exception:
                    pass
        else:
            self._local_cache.clear()


cache = CacheService()
