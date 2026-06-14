from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def safe_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return default


def safe_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value.strip().replace("%", ""))
    except (ValueError, AttributeError):
        return default


def parse_k_number(value: str | None) -> int:
    if not value:
        return 0
    value = value.strip().upper().replace(",", "")
    try:
        if value.endswith("B"):
            return int(float(value[:-1]) * 1_000_000_000)
        if value.endswith("M"):
            return int(float(value[:-1]) * 1_000_000)
        if value.endswith("K"):
            return int(float(value[:-1]) * 1_000)
        return int(float(value))
    except (ValueError, AttributeError):
        return 0


def extract_json_from_script(html: str, var_name: str) -> str | None:
    import re
    pattern = rf"const\s+{re.escape(var_name)}\s*=\s*(\[.+?\])\s*;"
    match = re.search(pattern, html, re.DOTALL)
    if match:
        return match.group(1)
    return None


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split())


def parse_bdt_timestamp(start_ts: int) -> str | None:
    from datetime import datetime
    if not start_ts:
        return None
    from app.config import BDT
    return datetime.fromtimestamp(start_ts, tz=BDT).isoformat()
