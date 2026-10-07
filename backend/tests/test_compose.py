"""Checks of the Compose file that need no Docker daemon."""

from pathlib import Path

import yaml

from megooarti.config import Settings

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def services() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


def test_database_is_published_on_the_loopback_interface_only():
    ports = services()["db"]["ports"]
    assert ports
    assert all(port.startswith("127.0.0.1:") for port in ports)


def test_container_stop_period_outlasts_the_application_shutdown_grace():
    app_default = Settings.model_fields["shutdown_grace_seconds"].default
    stop_period = services()["backend"]["stop_grace_period"]
    assert stop_period.endswith("s")
    assert int(stop_period.removesuffix("s")) > app_default
