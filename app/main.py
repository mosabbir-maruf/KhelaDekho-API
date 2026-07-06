from __future__ import annotations

import time

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

# Configure structured logging before anything emits logs.
import app.logging_config  # noqa: F401
from app.config import settings
from app.dependencies.auth import verify_xkey
from app.dependencies.rate_limit import APIRateLimiter
from app.middleware.errors import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.models import HealthResponse, StandardResponse
from app.routes import v1 as v1_routes
from app.routes import v2 as v2_routes
from app.routes import v4 as v4_routes

logger = structlog.get_logger(__name__)

_START_TIME = time.monotonic()

app = FastAPI(
    title="KhelaDekho API",
    description=(
        "Aggregator API. V1 serves live football scores from the configured "
        "score provider; V2 and V4 expose publicly embedded channel metadata."
    ),
    version="1.0.0",
)

# Exception handlers
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):
    response = await call_next(request)
    rate_limit_headers = getattr(request.state, "rate_limit_headers", None)
    if rate_limit_headers:
        response.headers.update(rate_limit_headers)
    return response


# All API routers require the shared xkey (proxy routes are exempt inside the
# dependency because media players cannot attach custom headers).
_auth = [Depends(verify_xkey)]
app.include_router(v1_routes.router, dependencies=_auth)
app.include_router(v2_routes.router, dependencies=_auth)
app.include_router(v4_routes.router, dependencies=_auth)

_rate_limit_std = APIRateLimiter(requests=100, window=60)


@app.get(
    "/api/v1/health",
    response_model=StandardResponse[HealthResponse],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_rate_limit_std)],
)
async def health_check():
    return StandardResponse(
        success=True,
        data=HealthResponse(uptime_seconds=time.monotonic() - _START_TIME),
    )
