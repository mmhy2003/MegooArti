"""Checks of the Compose file that need no Docker daemon."""

import re
from pathlib import Path

import pytest
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


GATEWAY = (COMPOSE_FILE.parent / "gateway" / "nginx.conf").read_text(encoding="utf-8")


def test_only_the_gateway_is_published_to_the_network():
    published = {
        name: service["ports"] for name, service in services().items() if "ports" in service
    }

    assert set(published) == {"db", "gateway"}
    assert published["gateway"] == ["${MEGOOARTI_HTTP_PORT:-8000}:80"]


def test_the_gateway_waits_for_what_it_stands_in_front_of():
    waited_for = services()["gateway"]["depends_on"]

    assert waited_for == {
        "backend": {"condition": "service_healthy"},
        "frontend": {"condition": "service_healthy"},
    }


def test_the_frontend_is_given_no_secret_and_no_way_to_the_data():
    frontend = services()["frontend"]

    # It renders the shell. The browser, not this container, calls the backend.
    assert set(frontend) == {"build", "healthcheck"}


def test_the_backend_takes_the_gateways_word_for_who_is_calling():
    environment = services()["backend"]["environment"]

    assert environment["MEGOOARTI_FORWARDED_ALLOW_IPS"] == "*"
    assert "ports" not in services()["backend"]  # which is why it can


def test_the_gateway_sends_the_api_the_repositories_and_the_registry_to_the_backend():
    routes = dict(re.findall(r"location (\S+) \{\s*proxy_pass (\$\w+);\s*\}", GATEWAY))

    assert routes == {
        "/api/": "$backend",
        "/repository/": "$backend",
        "/v2/": "$backend",
        "/": "$frontend",
    }


def test_the_gateway_passes_a_path_on_exactly_as_it_was_sent():
    # With anything after the upstream's address nginx decodes the path and writes it
    # again: an npm scope's encoded slash would become a real one.
    assert re.findall(r"proxy_pass ([^;]+);", GATEWAY) == ["$backend"] * 3 + ["$frontend"]
    assert "rewrite" not in GATEWAY


@pytest.mark.parametrize(
    "directive",
    [
        "client_max_body_size 0;",
        "proxy_request_buffering off;",
        "proxy_buffering off;",
        "proxy_http_version 1.1;",
        "proxy_set_header Host $http_host;",
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_read_timeout 600s;",
    ],
)
def test_the_gateway_does_what_artifacts_and_package_clients_need(directive):
    assert directive in GATEWAY
