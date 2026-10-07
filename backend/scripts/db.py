"""Database migration helper for developers.

Run from the backend/ directory, with MEGOOARTI_DATABASE_URL set or a .env file present:

    uv run python scripts/db.py new "add users table"   create the next revision from the models
    uv run python scripts/db.py upgrade [revision]      apply migrations (default: head)
    uv run python scripts/db.py downgrade [revision]    revert migrations (default: -1, one step)
    uv run python scripts/db.py current                 show the revision the database is at
    uv run python scripts/db.py history                 list every revision
    uv run python scripts/db.py check                   fail if models and migrations differ
"""

import argparse

from alembic import command
from alembic.script import ScriptDirectory

from megooarti.db.schema import alembic_config


def next_revision_id(history: ScriptDirectory) -> str:
    """The next sequential revision number, zero-padded to four digits."""
    numbers = [
        int(script.revision) for script in history.walk_revisions() if script.revision.isdigit()
    ]
    return f"{max(numbers, default=0) + 1:04d}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("new").add_argument("message")
    actions.add_parser("upgrade").add_argument("revision", nargs="?", default="head")
    actions.add_parser("downgrade").add_argument("revision", nargs="?", default="-1")
    actions.add_parser("current")
    actions.add_parser("history")
    actions.add_parser("check")
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    config = alembic_config()

    if arguments.action == "new":
        revision_id = next_revision_id(ScriptDirectory.from_config(config))
        command.revision(config, message=arguments.message, autogenerate=True, rev_id=revision_id)
    elif arguments.action == "upgrade":
        command.upgrade(config, arguments.revision)
    elif arguments.action == "downgrade":
        command.downgrade(config, arguments.revision)
    elif arguments.action == "current":
        command.current(config)
    elif arguments.action == "history":
        command.history(config)
    elif arguments.action == "check":
        command.check(config)


if __name__ == "__main__":
    main()
