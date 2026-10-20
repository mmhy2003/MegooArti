"""`python -m megooarti`: serve the application with settings from the environment."""

import sys

import uvicorn

from megooarti.config import ConfigurationError, get_settings
from megooarti.log import configure_logging


def main() -> None:
    try:
        settings = get_settings()
    except ConfigurationError as error:
        sys.exit(f"megooarti: {error}")

    configure_logging(settings.log_level)
    uvicorn.run(
        "megooarti.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        # Who a request comes from is the application's to say (megooarti.proxies): it
        # believes proxies an administrator trusts, past the gateway, as uvicorn cannot.
        proxy_headers=False,
        timeout_graceful_shutdown=settings.shutdown_grace_seconds,
        log_config=None,  # keep the JSON logging configured above
    )


if __name__ == "__main__":
    main()
