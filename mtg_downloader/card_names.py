from __future__ import annotations

import re

_FACE_SEPARATOR_RE = re.compile(r"\s+/{1,2}\s+")


def card_face_names(value: str) -> tuple[str, ...]:
    """Return every printed card-name component using / or // separators."""
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return ()

    parts = tuple(
        part.strip()
        for part in _FACE_SEPARATOR_RE.split(cleaned)
        if part.strip()
    )
    return parts or (cleaned,)


def canonical_card_name(value: str) -> str:
    """Normalise Moxfield's / and Scryfall's // separators."""
    return " // ".join(card_face_names(value))


def normalised_card_name(value: str) -> str:
    return canonical_card_name(value).casefold()


def is_multi_face_name(value: str) -> bool:
    return len(card_face_names(value)) > 1


def front_card_name(value: str) -> str:
    names = card_face_names(value)
    return names[0] if names else ""
