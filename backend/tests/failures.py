"""What a test said when it could not be set up, kept where it is found afterwards.

A test that fails says why in the run's own output. A setup that fails once in many
runs says it into an output that was piped through `tail`, or scrolled away, and the
suite is then run again and passes. So the text is also written to a file.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

# Beside the tests, and not in the repository (.gitignore).
DIRECTORY = Path(__file__).parent.parent / ".test-failures"
KEPT = 50


def keep_failure(
    directory: Path, nodeid: str, when: str, text: str, now: datetime | None = None
) -> Path:
    """Write one failure to a file of its own, and let go of all but the newest."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%f")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid)[-120:]
    path = directory / f"{stamp}-{when}-{name}.txt"
    path.write_text(f"{nodeid} ({when})\n\n{text}\n", encoding="utf-8")
    for old in sorted(directory.glob("*.txt"))[:-KEPT]:
        old.unlink(missing_ok=True)
    return path


def keep_broken_setup(report, directory: Path = DIRECTORY) -> Path | None:
    """For pytest's `pytest_runtest_logreport`: keep a setup or a teardown that failed.

    Not a test that failed: that is what a test is run to see.
    """
    if not report.failed or report.when == "call":
        return None
    try:
        return keep_failure(directory, report.nodeid, report.when, report.longreprtext)
    except OSError:
        # A place that cannot be written must not cost the run: what failed is still
        # in the run's own output.
        return None


def keep_stack_logs(report, logs, directory: Path = DIRECTORY) -> Path | None:
    """For a test of the running stack that failed: keep what the stack said.

    `logs` asks the stack, and answers its text. The stack is gone when its module of
    tests ends, and with it the one place that says why a client was refused. The text
    has what the backend logs once on its first start, the administrator's first
    password: of a stack that these tests made and remove.
    """
    if not report.failed or "docker" not in report.keywords:
        return None
    try:
        said = logs()
        if not said.strip():
            return None  # no stack: its build failed, and that is in the setup's own text
        return keep_failure(directory, report.nodeid, f"{report.when}-logs", said)
    except Exception:  # noqa: BLE001 (whatever Docker does, the run goes on)
        return None


def say_where(
    write_line, kept: list[Path], one: str = "failed setup", many: str = "failed setups"
) -> None:
    """For pytest's `pytest_terminal_summary`: a file nobody knows of is read by nobody."""
    if kept:
        write_line(f"{len(kept)} {one if len(kept) == 1 else many} kept in {kept[0].parent}")
