import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.models import StandardResponse

logger = structlog.get_logger(__name__)

async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    try:
        logger.exception("unhandled_internal_error", path=request.url.path, error=str(exc))
    except Exception:
        pass
    
    error_content = StandardResponse(
        success=False,
        error={
            "code": "INTERNAL_SERVER_ERROR",
            "message": "A critical system error occurred. Please try again later."
        }
    ).model_dump()
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_content
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    try:
        logger.warning("http_exception", path=request.url.path, status_code=exc.status_code, detail=exc.detail)
    except Exception:
        pass
    
    error_content = StandardResponse(
        success=False,
        error={
            "code": f"HTTP_{exc.status_code}",
            "message": exc.detail
        }
    ).model_dump()
    
    headers = getattr(exc, "headers", None) or {}
    return JSONResponse(
        status_code=exc.status_code,
        content=error_content,
        headers=headers
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("validation_exception", path=request.url.path, errors=exc.errors())
    
    # Format details safely for JSON output
    formatted_errors = []
    for error in exc.errors():
        formatted_errors.append({
            "loc": [str(loc) for loc in error.get("loc", [])],
            "msg": error.get("msg", ""),
            "type": error.get("type", "")
        })
        
    error_content = StandardResponse(
        success=False,
        error={
            "code": "VALIDATION_ERROR",
            "message": "Input validation failed.",
            "details": formatted_errors
        }
    ).model_dump()
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_content
    )
