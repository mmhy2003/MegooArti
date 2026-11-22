"""Checks of the Compose file that need no Docker daemon."""

import re
from pathlib import Path

import pytest
import yaml

from megooarti import __version__
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


GATEWAY = (COMPOSE_FILE.parent / "gateway" / "Caddyfile").read_text(encoding="utf-8")
# The same text without its comments, which may name what the code must not hold.
CODE = re.sub(r"#.*", "", GATEWAY)


def test_only_the_gateway_is_published_to_the_network():
    published = {
        name: service["ports"] for name, service in services().items() if "ports" in service
    }

    assert set(published) == {"db", "gateway"}
    assert published["gateway"] == ["${MEGOOARTI_HTTP_PORT:-80}:80"]


def test_the_gateway_is_caddy_with_its_file_and_nothing_kept():
    gateway = services()["gateway"]

    assert gateway["image"] == "caddy:2"
    assert gateway["volumes"] == ["./gateway/Caddyfile:/etc/caddy/Caddyfile:ro"]
    # It asks for no certificate, so what Caddy writes there may go with the container.
    assert gateway["tmpfs"] == ["/data", "/config"]
    # Plain HTTP only: TLS is your own proxy's.
    assert not any("443" in port for port in gateway["ports"])


def test_the_gateway_waits_for_what_it_stands_in_front_of():
    waited_for = services()["gateway"]["depends_on"]

    assert waited_for == {
        "backend": {"condition": "service_healthy"},
        "frontend": {"condition": "service_healthy"},
    }


def test_the_frontend_is_given_no_secret_and_no_way_to_the_data():
    frontend = services()["frontend"]

    # It renders the shell. The browser, not this container, calls the backend.
    assert set(frontend) == {"image", "build", "healthcheck"}


def test_the_backend_takes_the_gateways_word_for_who_is_calling():
    environment = services()["backend"]["environment"]

    assert environment["MEGOOARTI_FORWARDED_ALLOW_IPS"] == "*"
    assert "ports" not in services()["backend"]  # which is why it can


def test_the_gateway_sends_the_api_the_repositories_the_registry_mcp_and_oauth_to_the_backend():
    matchers = dict(re.findall(r"(@\w+) path (.+)", CODE))

    assert matchers["@backend"].split() == [
        "/api/*",
        "/repository/*",
        "/v2/*",
        "/mcp*",
        "/.well-known/*",
        "/oauth/*",
    ]
    # Caddy tries a reverse_proxy with a matcher before the one without: everything
    # else is the web UI.
    assert re.findall(r"reverse_proxy (?:(@\w+) )?([\w.-]+:\d+) \{", CODE) == [
        ("@backend", "backend:8000"),
        ("", "frontend:3000"),
    ]


def test_the_gateway_passes_a_path_on_exactly_as_it_was_sent():
    # A directive that writes the path again would decode it on the way: an npm scope's
    # encoded slash would become a real one.
    directives = [line.strip() for line in CODE.splitlines()]

    assert not [
        line for line in directives if line.startswith(("rewrite", "uri", "handle_path", "strip_"))
    ]


@pytest.mark.parametrize(
    "directive",
    [
        # Plain HTTP only: no certificate is asked for.
        "auto_https off",
        # The address the gateway sees, added: the backend reads from the right, past
        # trusted proxies only, so what the client wrote of itself is never believed.
        "trusted_proxies static 0.0.0.0/0 ::/0",
        "header_up X-Forwarded-Proto {scheme}",
        "flush_interval -1",
        "response_header_timeout 600s",
        "read_timeout 600s",
        "write_timeout 600s",
    ],
)
def test_the_gateway_does_what_artifacts_and_package_clients_need(directive):
    assert directive in CODE


def test_both_upstreams_are_sent_the_same_and_nothing_is_limited_or_held():
    assert CODE.count("import upstream") == 2
    # Caddy streams a body of any size by default, and passes Host on as it came.
    for directive in ["max_size", "request_buffers", "header_up Host"]:
        assert directive not in CODE


def dockerfile(name: str) -> str:
    return (COMPOSE_FILE.parent / name / "Dockerfile").read_text(encoding="utf-8")


def test_nothing_starts_with_a_password_everybody_knows():
    whole = COMPOSE_FILE.read_text(encoding="utf-8")
    password = services()["db"]["environment"]["POSTGRES_PASSWORD"]
    address = services()["backend"]["environment"]["MEGOOARTI_DATABASE_URL"]

    # `:?` stops Compose, with these words, where the variable is not set or is empty.
    assert password.startswith("${MEGOOARTI_DB_PASSWORD:?Set MEGOOARTI_DB_PASSWORD.")
    assert ".env.example" in password
    # Apart from the address: in it, a password with an @ or a / would be read as a host
    # or a path.
    assert address == "postgresql://megooarti@db:5432/megooarti"
    assert services()["backend"]["environment"]["MEGOOARTI_DATABASE_PASSWORD"] == password
    assert "megooarti:megooarti" not in whole


@pytest.mark.parametrize("name", ["backend", "frontend"])
def test_the_images_are_named_as_a_registry_would_hold_them(name):
    service = services()[name]
    tag = f"${{MEGOOARTI_VERSION:-{__version__}}}"

    # In the place of a registry that is this project's own, where only its owner puts
    # an image. A short name on the public registry is whoever's took it there, and
    # `docker compose pull` would have run what they put under it.
    assert service["image"] == f"ghcr.io/mmhy2003/megooarti-{name}:{tag}"
    source = re.search(r'image\.source="https://github\.com/([^"]+)"', dockerfile(name))[1]
    assert service["image"].startswith(f"ghcr.io/{source.split('/')[0].lower()}/")
    # The image is told the version it is built as, for its label.
    assert service["build"] == {"context": f"./{name}", "args": {"VERSION": tag}}
    # Not built again at every command: what `docker compose run` prints must be what
    # was run, and a build writes into the same place.
    assert "pull_policy" not in service


def test_the_secret_key_is_passed_on_only_if_it_is_set():
    environment = services()["backend"]["environment"]

    # No value: Compose passes on what its own environment has, and nothing otherwise.
    assert "MEGOOARTI_SECRET_KEY" in environment
    assert environment["MEGOOARTI_SECRET_KEY"] is None


def test_the_example_names_everything_the_compose_file_asks_of_the_environment():
    whole = COMPOSE_FILE.read_text(encoding="utf-8")
    example = (COMPOSE_FILE.parent / ".env.example").read_text(encoding="utf-8")
    asked = set(re.findall(r"\$\{(MEGOOARTI_[A-Z_]+)", whole))
    asked |= {name for name, value in services()["backend"]["environment"].items() if value is None}

    named = set(re.findall(r"^#?(MEGOOARTI_[A-Z_]+)=", example, flags=re.MULTILINE))

    assert named == asked
    # The one thing that must be chosen is chosen for nobody.
    assert re.search(r"^MEGOOARTI_DB_PASSWORD=$", example, flags=re.MULTILINE)
    assert len(re.findall(r"^MEGOOARTI_", example, flags=re.MULTILINE)) == 1


def test_the_tests_stack_is_not_configured_by_the_env_file_beside_the_compose_file():
    """Compose reads `.env` beside the Compose file, which is an installation's own.

    The tests' stack names a file of its own instead, which says nothing: a secret key
    or anything else set for the developer's installation must not reach it.
    """
    from tests.containers import ENVIRONMENT

    named = Path(ENVIRONMENT["COMPOSE_ENV_FILES"])

    assert named.is_file()
    assert named.parent == Path(__file__).parent
    said = [line for line in named.read_text(encoding="utf-8").splitlines() if "=" in line]
    assert said == []
