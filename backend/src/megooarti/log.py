"""Logs on standard output, as JSON or as lines to read, from structlog and the stdlib."""

import logging
import os
import re
import sys
from typing import Literal

import structlog

# `npm logout` puts the token it revokes in the address. When the request fails, that
# token is still good.
_TOKEN_IN_ADDRESS = re.compile(r"(/-/user/token/)[^/?#\s\"]+")


def redact(address: str) -> str:
    """An address as it may be logged: without the token `npm logout` puts in it."""
    return _TOKEN_IN_ADDRESS.sub(r"\1[redacted]", address)


class _RedactAddresses(logging.Filter):
    """Applied to the line the server writes for every request."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact(value) if isinstance(value, str) else value for value in record.args
            )
        return True


_redact_addresses = _RedactAddresses()

# The container's health check asks this every few seconds.
_READINESS = "/api/v1/status/ready"


class _QuietReadiness(logging.Filter):
    """Leaves out the request line of a readiness check that passed."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            _client, _method, address, _version, status = args
            if isinstance(address, str) and address.partition("?")[0] == _READINESS:
                return not (isinstance(status, int) and status < 400)
        return True


_quiet_readiness = _QuietReadiness()


def _renderer(log_format: Literal["json", "console"]):
    if log_format == "console":
        # Colours on Windows need colorama, which is not installed.
        colors = sys.platform != "win32" and not os.environ.get("NO_COLOR")
        return structlog.dev.ConsoleRenderer(colors=colors)
    return structlog.processors.JSONRenderer()


def configure_logging(
    level: str = "INFO", log_format: Literal["json", "console"] = "console"
) -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                # The console renderer lays out the traceback itself.
                *([structlog.processors.format_exc_info] if log_format == "json" else []),
                _renderer(log_format),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # The HTTP client logs the full URL of every outbound request at INFO. Proxy
    # repositories make many, and a URL is not something to copy into the log.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    for access_filter in (_redact_addresses, _quiet_readiness):
        if access_filter not in access.filters:
            access.addFilter(access_filter)
