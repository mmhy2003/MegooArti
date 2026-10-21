import json
import logging

import pytest
import structlog

from megooarti.log import configure_logging, redact


@pytest.fixture
def isolated_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def read_lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_lines_to_read_are_the_default_format(isolated_logging, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    configure_logging("INFO")

    structlog.get_logger("megooarti.test").info("artifact_stored")

    (line,) = capsys.readouterr().out.splitlines()
    assert not line.startswith("{")
    assert "artifact_stored" in line


def test_structlog_events_are_json_lines_with_bound_context(isolated_logging, capsys):
    configure_logging("INFO", "json")
    structlog.contextvars.bind_contextvars(request_id="abc123")

    structlog.get_logger("megooarti.test").info("artifact_stored", size=42)

    (line,) = read_lines(capsys)
    assert line["event"] == "artifact_stored"
    assert line["size"] == 42
    assert line["level"] == "info"
    assert line["logger"] == "megooarti.test"
    assert line["request_id"] == "abc123"
    assert "timestamp" in line


def test_standard_library_logs_use_the_same_format(isolated_logging, capsys):
    configure_logging("INFO", "json")
    structlog.contextvars.bind_contextvars(request_id="abc123")

    logging.getLogger("thirdparty").warning("plain %s", "message")

    (line,) = read_lines(capsys)
    assert line["event"] == "plain message"
    assert line["level"] == "warning"
    assert line["logger"] == "thirdparty"
    assert line["request_id"] == "abc123"


def test_exceptions_are_rendered_inside_the_json_line(isolated_logging, capsys):
    configure_logging("INFO", "json")

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logging.getLogger("thirdparty").exception("calculation failed")

    (line,) = read_lines(capsys)
    assert line["event"] == "calculation failed"
    assert "ZeroDivisionError" in line["exception"]


def test_level_filters_lower_severity(isolated_logging, capsys):
    configure_logging("WARNING", "json")

    structlog.get_logger("megooarti.test").info("ignored")
    structlog.get_logger("megooarti.test").warning("kept")

    assert [line["event"] for line in read_lines(capsys)] == ["kept"]


def test_the_http_client_does_not_log_each_request(isolated_logging):
    # Its INFO line is the full URL of every outbound request.
    configure_logging("INFO", "json")

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_a_token_in_an_address_is_not_logged(isolated_logging, capsys):
    configure_logging("INFO", "json")
    address = "/repository/npm/-/user/token/mga_a-secret-value"

    # The line uvicorn writes for every request.
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "10.0.0.1:5000", "DELETE", address, "1.1", 503
    )

    (line,) = read_lines(capsys)
    assert "mga_a-secret-value" not in line["event"]
    assert "/repository/npm/-/user/token/[redacted]" in line["event"]
    assert redact("/x/-/user/token/mga_abc?write=true") == "/x/-/user/token/[redacted]?write=true"
    assert redact("/repository/npm/left-pad") == "/repository/npm/left-pad"


def test_console_lines_are_one_readable_line_per_event(isolated_logging, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    configure_logging("INFO", "console")
    structlog.contextvars.bind_contextvars(request_id="abc123")

    structlog.get_logger("megooarti.test").info("login_failed", username="admin")
    logging.getLogger("thirdparty").warning("plain %s", "message")

    first, second = capsys.readouterr().out.splitlines()
    assert "[" not in first
    assert not first.startswith("{")
    for part in (
        "[info",
        "login_failed",
        "[megooarti.test]",
        "username=admin",
        "request_id=abc123",
    ):
        assert part in first
    for part in ("[warning", "plain message", "[thirdparty]", "request_id=abc123"):
        assert part in second


def test_console_lines_keep_the_traceback(isolated_logging, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    configure_logging("INFO", "console")

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logging.getLogger("thirdparty").exception("calculation failed")

    out = capsys.readouterr().out
    assert "calculation failed" in out
    assert "ZeroDivisionError" in out


def access_line(path: str, status: int) -> None:
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:0", "GET", path, "1.1", status
    )


def test_a_passing_readiness_check_is_not_logged(isolated_logging, capsys):
    # The container's health check asks every few seconds.
    configure_logging("INFO", "json")

    access_line("/api/v1/status/ready", 200)
    access_line("/api/v1/status/ready", 503)
    access_line("/api/v1/status/ready?verbose=1", 200)
    access_line("/api/v1/auth/session", 200)

    assert [line["event"].split('"')[1] for line in read_lines(capsys)] == [
        "GET /api/v1/status/ready HTTP/1.1",
        "GET /api/v1/auth/session HTTP/1.1",
    ]
