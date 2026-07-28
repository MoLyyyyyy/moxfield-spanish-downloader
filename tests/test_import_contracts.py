from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_does_not_import_scryfall_filter_from_review() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(app)

    imported_from_review: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "mtg_downloader.review"
        ):
            imported_from_review.update(
                alias.name for alias in node.names
            )

    assert "filter_scryfall_alternatives" not in imported_from_review
    assert "def filter_scryfall_alternatives(" in app


def test_review_module_remains_backward_compatible() -> None:
    from mtg_downloader.review import filter_scryfall_alternatives

    candidates = [
        {
            "id": "new",
            "set": "new",
            "released_at": "2026-01-01",
            "artist": "Artist A",
        },
        {
            "id": "old",
            "set": "old",
            "released_at": "2024-01-01",
            "artist": "Artist B",
        },
    ]

    assert [
        item["id"]
        for item in filter_scryfall_alternatives(
            candidates,
            set_code="new",
        )
    ] == ["new"]
