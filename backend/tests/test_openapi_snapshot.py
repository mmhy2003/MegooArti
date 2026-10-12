"""The copy of the API document that the web UI's types are generated from.

The UI is written against `frontend/openapi.json`. This test fails when the API has
changed and the copy has not, so the two cannot drift apart unnoticed. To bring the
copy up to date, and then the types:

    MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py
    cd ../frontend && pnpm gen:api
"""

import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def written(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_the_copy_of_the_api_document_is_up_to_date(app):
    current = written(app.openapi())
    if os.environ.get("MEGOOARTI_UPDATE_OPENAPI"):
        SNAPSHOT.write_text(current, encoding="utf-8", newline="\n")

    assert SNAPSHOT.exists(), "frontend/openapi.json is missing: see this file's first lines"
    assert SNAPSHOT.read_text(encoding="utf-8") == current, (
        "The API has changed. Run this test with MEGOOARTI_UPDATE_OPENAPI=1, then "
        "`pnpm gen:api` in frontend/, and commit both files."
    )
