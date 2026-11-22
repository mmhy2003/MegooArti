"""MegooArti's release rules, for the release workflow and for whoever releases (docs/releasing.md).

    python tools/release/versions.py check     the version's four places agree
    python tools/release/versions.py plan      what needs releasing (key=value lines, for $GITHUB_OUTPUT)

One product: MegooArti, whose version is `VERSION`, kept equal to the backend's and the web UI's own. It is
released as two images and a GitHub release tagged vX.Y.Z.
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
TAG = "v"
VERSION_FILE = "VERSION"
# what MegooArti is made of: a change here since its last release needs a new version
PATHS = ["backend", "frontend", "gateway", "docker-compose.yml", ".env.example", "VERSION"]
# where else the version is written, and how it is read there
PLACES = {
    "backend/pyproject.toml": lambda text: tomllib.loads(text)["project"]["version"],
    "backend/src/megooarti/__init__.py": lambda text: re.search(
        r'^__version__ = "([^"]*)"$', text, flags=re.MULTILINE
    )[1],
    "frontend/package.json": lambda text: json.loads(text)["version"],
}


def parse(version: str) -> tuple[int, int, int] | None:
    """A release version is exactly X.Y.Z (a leading v allowed); anything else (dev, 0.1.0-dev+abc) is not one."""
    m = RELEASE.match(version.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _read(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8").strip()


def check(root: Path) -> list[str]:
    errors = []
    version = _read(root, VERSION_FILE)
    for path, read in PLACES.items():
        said = read(_read(root, path))
        if said != version:
            errors.append(f"{path} says {said}, VERSION says {version}: they must be equal")
    if parse(version) is None:
        errors.append(f"VERSION holds {version!r}, not a release version (X.Y.Z)")
    return errors


def _last_tag(root: Path) -> str | None:
    tags = [t for t in _git(root, "tag", "--list", f"{TAG}*").split() if parse(t.removeprefix(TAG))]
    return max(tags, key=lambda t: parse(t.removeprefix(TAG)), default=None)


def guard(root: Path) -> list[str]:
    """What changed since the last release must carry a new version, and never a lower one (`latest` would
    move servers back to it)."""
    tag = _last_tag(root)
    if tag is None:
        return []
    version, released = _read(root, VERSION_FILE), tag.removeprefix(TAG)
    if (parse(version) or (0, 0, 0)) < parse(released):
        return [f"VERSION says {version}, lower than the last release {tag}"]
    if version != released:
        return []
    changed = _git(root, "diff", "--name-only", tag, "HEAD", "--", *PATHS).split()
    if changed:
        return [f"{', '.join(PATHS)} changed since {tag} but VERSION is still {released}: bump it (e.g. {changed[0]})"]
    return []


def note_path(version: str) -> str:
    return f"docs/releases/{TAG}{version}.md"


def plan(root: Path) -> dict[str, str]:
    """Whether the version still needs a release, and that version."""
    errors = check(root) + guard(root)
    version = _read(root, VERSION_FILE)
    needed = not _git(root, "tag", "--list", f"{TAG}{version}").strip()
    # added to git, not just on disk: the workflow sees only what was pushed
    if needed and not _git(root, "ls-files", "--", note_path(version)).strip():
        errors.append(f"{note_path(version)} is missing (or not added to git): every release needs its release note")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    return {"app": "true" if needed else "false", "app_version": version}


def main(argv: list[str]) -> int:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    match argv:
        case ["check"]:
            errors = check(root)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            return 0
        case ["plan"]:
            print("\n".join(f"{k}={v}" for k, v in plan(root).items()))
            return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
