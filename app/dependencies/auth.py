import hmac

import structlog
from fastapi import HTTPException, Request, status

from app.config import settings

logger = structlog.get_logger(__name__)


async def verify_xkey(request: Request) -> None:
    """Single shared API-key auth. Mirrors the Cloudflare Worker `xkey` check.

    When ``XKEY`` is unset the check is skipped (useful for local dev). Proxy
    routes are exempt because media players cannot attach custom headers.
    """
    expected = settings.xkey
    if not expected:
        return

    if request.url.path.endswith("/proxy"):
        return

    provided = request.headers.get("xkey")
    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning("auth_failed_invalid_xkey", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing xkey.",
        )
