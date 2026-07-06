import logging

import structlog

from app.config import settings

# Verbose, human-readable logs in development; compact JSON and a higher
# threshold in production so runtime internals aren't exposed.
_shared_processors = [
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]

if settings.debug:
    _renderer = structlog.dev.ConsoleRenderer()
    _min_level = logging.DEBUG
else:
    _renderer = structlog.processors.JSONRenderer()
    _min_level = getattr(logging, settings.log_level.upper(), logging.INFO)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        *_shared_processors,
        _renderer,
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.make_filtering_bound_logger(_min_level),
    cache_logger_on_first_use=True,
)
