from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename_component(
    value: str,
    *,
    fallback: str = "proxy-maker",
    maximum_length: int = 120,
) -> str:
    """Return a filename component that is safe on Windows and Unix."""
    text = str(value or "").strip()
    text = re.sub(r"\s*//\s*", " - ", text)
    text = _INVALID_FILENAME_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")

    if not text:
        text = fallback

    text = text[:maximum_length].rstrip(" .")
    return text or fallback


def commander_pdf_filename(cards: Iterable[Any]) -> str:
    """Use the first card in deck order as the PDF filename."""
    first = next(iter(cards), None)
    if first is None:
        return "proxy-maker.pdf"

    source = getattr(first, "source", first)
    name = getattr(source, "name", "")
    return f"{safe_filename_component(name)}.pdf"



def multi_deck_pdf_filename(
    deck_names: Iterable[str],
    cards: Iterable[Any],
) -> str:
    """Build a useful PDF name for one or several concatenated decks."""
    names = [
        safe_filename_component(name)
        for name in deck_names
        if str(name or "").strip()
    ]
    if not names:
        return commander_pdf_filename(cards)
    if len(names) == 1:
        return f"{names[0]}.pdf"
    if len(names) == 2:
        return (
            f"{safe_filename_component(f'{names[0]} + {names[1]}')}.pdf"
        )
    return (
        f"{safe_filename_component(f'{names[0]} + {len(names) - 1} mazos')}.pdf"
    )
