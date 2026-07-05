import time
import structlog
from fastapi import Request, HTTPException, status
from app.services.cache import cache

logger = structlog.get_logger(__name__)

class APIRateLimiter:
    def __init__(self, requests: int = 60, window: int = 60):
        self.requests = requests
        self.window = window

    async def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        remaining = self.requests
        reset_at = int(time.time()) + self.window

        remaining = await self._count_in_memory(client_ip, request.url.path)
        if remaining < 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Request rate limit exceeded. Please back off.",
            )
        await self._record_in_memory(client_ip, request.url.path)

        request.state.rate_limit_headers = {
            "X-RateLimit-Limit": str(self.requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_at),
        }

    async def _count_in_memory(self, client_ip: str, path: str) -> int:
        now = int(time.time())
        local_key = f"rate_limit:{client_ip}:{path}"
        timestamps = cache._local_cache.get(local_key) or []
        timestamps = [t for t in timestamps if t > now - self.window]
        return self.requests - len(timestamps) - 1

    async def _record_in_memory(self, client_ip: str, path: str):
        now = int(time.time())
        local_key = f"rate_limit:{client_ip}:{path}"
        timestamps = cache._local_cache.get(local_key) or []
        timestamps = [t for t in timestamps if t > now - self.window]
        timestamps.append(now)
        cache._local_cache[local_key] = timestamps
