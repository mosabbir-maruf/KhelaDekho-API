from __future__ import annotations

import time
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# Configure structured logging before anything emits logs.
import app.logging_config  # noqa: F401
from app.config import settings
from app.dependencies.auth import verify_xkey
from app.middleware.errors import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.models import HealthResponse, StandardResponse
from app.routes import v1 as v1_routes
from app.routes import v2 as v2_routes
from app.routes import v4 as v4_routes
from app.routes import v5 as v5_routes

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


# All API routers require the shared xkey (proxy routes are exempt inside the
# dependency because media players cannot attach custom headers).
_auth = [Depends(verify_xkey)]
app.include_router(v1_routes.router, dependencies=_auth)
app.include_router(v2_routes.router, dependencies=_auth)
app.include_router(v4_routes.router, dependencies=_auth)
app.include_router(v5_routes.router, dependencies=_auth)

# Serve 24/7 poster images from the Worker's asset directory
_PUBLIC_DIR = Path(__file__).resolve().parent.parent / "worker" / "public"
_247_ASSETS_DIR = _PUBLIC_DIR / "V5-24:7-Assets"
if _247_ASSETS_DIR.is_dir():
    app.mount("/V5-24:7-Assets", StaticFiles(directory=str(_247_ASSETS_DIR)), name="247_assets")


@app.get(
    "/api/v1/health",
    response_model=StandardResponse[HealthResponse],
    status_code=status.HTTP_200_OK,
)
async def health_check():
    return StandardResponse(
        success=True,
        data=HealthResponse(uptime_seconds=time.monotonic() - _START_TIME),
    )
