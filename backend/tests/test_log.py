import json
import logging

import pytest
import structlog

from megooarti.log import configure_logging


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


def test_structlog_events_are_json_lines_with_bound_context(isolated_logging, capsys):
    configure_logging("INFO")
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
    configure_logging("INFO")
    structlog.contextvars.bind_contextvars(request_id="abc123")

    logging.getLogger("thirdparty").warning("plain %s", "message")

    (line,) = read_lines(capsys)
    assert line["event"] == "plain message"
    assert line["level"] == "warning"
    assert line["logger"] == "thirdparty"
    assert line["request_id"] == "abc123"


def test_exceptions_are_rendered_inside_the_json_line(isolated_logging, capsys):
    configure_logging("INFO")

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logging.getLogger("thirdparty").exception("calculation failed")

    (line,) = read_lines(capsys)
    assert line["event"] == "calculation failed"
    assert "ZeroDivisionError" in line["exception"]


def test_level_filters_lower_severity(isolated_logging, capsys):
    configure_logging("WARNING")

    structlog.get_logger("megooarti.test").info("ignored")
    structlog.get_logger("megooarti.test").warning("kept")

    assert [line["event"] for line in read_lines(capsys)] == ["kept"]
