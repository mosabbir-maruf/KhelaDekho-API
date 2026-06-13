import time
import structlog
from fastapi import Request, HTTPException, status
from app.services.cache import cache

logger = structlog.get_logger(__name__)

class RateLimiter:
    def __init__(self, requests: int = 60, window: int = 60):
        self.requests = requests
        self.window = window

    async def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}:{request.url.path}"
        
        await cache._connect_redis()
        
        if not cache._redis:
            await self._fallback_in_memory(client_ip, request.url.path)
            return

        current_time = int(time.time())
        try:
            pipe = cache._redis.pipeline()
            # Remove elements older than window
            pipe.zremrangebyscore(key, 0, current_time - self.window)
            # Count elements remaining
            pipe.zcard(key)
            # Add current timestamp
            pipe.zadd(key, {f"{current_time}_{time.time()}": current_time})
            # Expire key
            pipe.expire(key, self.window)
            
            results = await pipe.execute()
            request_count = results[1]
            
            if request_count >= self.requests:
                logger.warning("rate_limit_exceeded", ip=client_ip, path=request.url.path)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Request rate limit exceeded. Please back off."
                )
        except Exception as e:
            logger.warning("redis_rate_limit_failed_falling_back", error=str(e))
            await self._fallback_in_memory(client_ip, request.url.path)

    async def _fallback_in_memory(self, client_ip: str, path: str):
        now = int(time.time())
        local_key = f"rate_limit:{client_ip}:{path}"
        
        timestamps = cache._local_cache.get(local_key) or []
        timestamps = [t for t in timestamps if t > now - self.window]
        
        if len(timestamps) >= self.requests:
            logger.warning("rate_limit_exceeded_local", ip=client_ip, path=path)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Request rate limit exceeded. Please back off."
            )
            
        timestamps.append(now)
        cache._local_cache[local_key] = timestamps
