import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from alembic.script import ScriptDirectory

from megooarti.db.schema import alembic_config, head_revision
from tests.databases import fetch_all

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_DIR / "scripts" / "db.py"
USER_TABLES = (
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
)


def load_script():
    spec = importlib.util.spec_from_file_location("megooarti_db_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=BACKEND_DIR,
        env={**os.environ, "MEGOOARTI_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def fake_history(*revisions: str) -> SimpleNamespace:
    return SimpleNamespace(
        walk_revisions=lambda: [SimpleNamespace(revision=revision) for revision in revisions]
    )


def test_first_revision_number():
    assert load_script().next_revision_id(fake_history()) == "0001"


def test_next_revision_number_follows_the_highest_and_ignores_non_numeric_ids():
    history = fake_history("0001", "0007", "a1b2c3")
    assert load_script().next_revision_id(history) == "0008"


def test_next_revision_number_for_the_real_history():
    history = ScriptDirectory.from_config(alembic_config())
    expected = f"{int(head_revision()) + 1:04d}"
    assert load_script().next_revision_id(history) == expected


def test_upgrade_then_current_reports_head(empty_database):
    upgraded = run_script(empty_database, "upgrade")
    assert upgraded.returncode == 0, upgraded.stderr

    current = run_script(empty_database, "current")
    assert current.returncode == 0, current.stderr
    assert f"{head_revision()} (head)" in current.stdout


def test_check_passes_at_head(empty_database):
    run_script(empty_database, "upgrade")

    checked = run_script(empty_database, "check")
    assert checked.returncode == 0, checked.stderr


def test_downgrade_to_base_removes_every_table(empty_database):
    run_script(empty_database, "upgrade")

    downgraded = run_script(empty_database, "downgrade", "base")
    assert downgraded.returncode == 0, downgraded.stderr
    assert fetch_all(empty_database, USER_TABLES) == []


def test_history_lists_the_first_revision(empty_database):
    history = run_script(empty_database, "history")
    assert history.returncode == 0, history.stderr
    assert "0001" in history.stdout


def test_unknown_action_is_a_usage_error(empty_database):
    result = run_script(empty_database, "explode")
    assert result.returncode == 2
    assert "usage:" in result.stderr
