import hmac
import hashlib
import time
import structlog
from fastapi import Request, HTTPException, status
from app.config import settings

logger = structlog.get_logger(__name__)

async def verify_signed_frontend_request(request: Request):
    token = request.headers.get("X-Signature-Token")
    timestamp = request.headers.get("X-Signature-Timestamp")
    
    if not token or not timestamp:
        logger.warning("auth_failed_missing_credentials", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Secure session credentials missing"
        )
        
    try:
        ts_val = int(timestamp)
    except ValueError:
        logger.warning("auth_failed_invalid_timestamp_format", path=request.url.path, timestamp=timestamp)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature timestamp format"
        )
        
    if abs(int(time.time()) - ts_val) > settings.signature_window_seconds:
        logger.warning("auth_failed_expired_signature", path=request.url.path, ts_val=ts_val, current=int(time.time()))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session signature expired"
        )
        
    # Re-calculate hash using backend internal key
    expected_message = f"{timestamp}:{request.url.path}".encode()
    signature = hmac.new(
        settings.secret_key.encode(),
        expected_message,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, token):
        logger.warning("auth_failed_invalid_signature", path=request.url.path, token=token, expected=signature)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature validation failed"
        )
