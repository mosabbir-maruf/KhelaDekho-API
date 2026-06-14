import time
import structlog
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from app.services.cache import cache

logger = structlog.get_logger(__name__)

class APIRateLimiter:
    def __init__(self, requests: int = 60, window: int = 60):
        self.requests = requests
        self.window = window

    async def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}:{request.url.path}"
        
        await cache._connect_redis()
        
        remaining = self.requests
        reset_at = int(time.time()) + self.window

        if not cache._redis:
            remaining = await self._count_in_memory(client_ip, request.url.path)
            if remaining < 0:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Request rate limit exceeded. Please back off.",
                )
            await self._record_in_memory(client_ip, request.url.path)
        else:
            current_time = int(time.time())
            try:
                pipe = cache._redis.pipeline()
                pipe.zremrangebyscore(key, 0, current_time - self.window)
                pipe.zcard(key)
                pipe.zadd(key, {f"{current_time}_{time.time()}": current_time})
                pipe.expire(key, self.window)
                
                results = await pipe.execute()
                request_count = results[1]
                remaining = max(0, self.requests - request_count - 1)
                
                if request_count >= self.requests:
                    logger.warning("rate_limit_exceeded", ip=client_ip, path=request.url.path)
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Request rate limit exceeded. Please back off.",
                        headers={
                            "X-RateLimit-Limit": str(self.requests),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(reset_at),
                            "Retry-After": str(self.window),
                        },
                    )
            except Exception as e:
                logger.warning("redis_rate_limit_failed_falling_back", error=str(e))
                remaining = await self._count_in_memory(client_ip, request.url.path)
                if remaining < 0:
                    remaining = 0
                await self._record_in_memory(client_ip, request.url.path)

        # If request is allowed, attach rate limit headers to the request state
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
