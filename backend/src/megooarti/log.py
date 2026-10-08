"""JSON logging on standard output for structlog and the standard library."""

import logging
import re
import sys

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


def configure_logging(level: str = "INFO") -> None:
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
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
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
    if _redact_addresses not in access.filters:
        access.addFilter(_redact_addresses)
