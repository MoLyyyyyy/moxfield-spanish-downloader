from __future__ import annotations

import itertools
import string
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any


def _letters(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", str(value))
    return "".join(
        character
        for character in normalised.upper()
        if character in string.ascii_uppercase
    )


def _candidates(name: str) -> Iterable[str]:
    letters = _letters(name)
    padded = (letters + "XXX")[:3]
    yield padded

    for positions in itertools.combinations(range(len(letters)), 3):
        yield "".join(letters[position] for position in positions)

    for characters in itertools.product(string.ascii_uppercase, repeat=3):
        yield "".join(characters)


def assign_deck_codes(names: Sequence[str]) -> list[str]:
    """Return stable, unique three-letter identifiers for deck names."""
    used: set[str] = set()
    result: list[str] = []
    for name in names:
        code = next(candidate for candidate in _candidates(name) if candidate not in used)
        used.add(code)
        result.append(code)
    return result


def codes_by_card(
    summaries: Sequence[dict[str, Any]],
    card_count: int,
) -> list[str | None]:
    """Expand deck identifiers to the resolved-card entry ranges."""
    result: list[str | None] = [None] * max(int(card_count), 0)
    codes = assign_deck_codes(
        [str(summary.get("name") or "Mazo") for summary in summaries]
    )
    for summary, code in zip(summaries, codes):
        start = max(int(summary.get("start_index", 0)), 0)
        end = min(int(summary.get("end_index", start)), len(result))
        for index in range(start, max(start, end)):
            result[index] = code
    return result
