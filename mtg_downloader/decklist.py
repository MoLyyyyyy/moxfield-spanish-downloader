from __future__ import annotations

import re
from collections import OrderedDict

from .models import DeckCard

_ZONE_HEADINGS = {
    "commander": "commanders",
    "commanders": "commanders",
    "comandante": "commanders",
    "comandantes": "commanders",
    "partner": "partners",
    "partners": "partners",
    "mainboard": "mainboard",
    "deck": "mainboard",
    "mazo": "mainboard",
    "sideboard": "sideboard",
    "banquillo": "sideboard",
    "maybeboard": "maybeboard",
    "considerando": "maybeboard",
    "companion": "companions",
    "companions": "companions",
    "compañero": "companions",
    "signature spell": "signatureSpells",
    "signature spells": "signatureSpells",
    "hechizo distintivo": "signatureSpells",
}

_QUANTITY_RE = re.compile(r"^\s*(\d+)\s*[xX]?\s+(.+?)\s*$")
_SET_AND_NUMBER_RE = re.compile(
    r"^(.*?)\s+\(([A-Za-z0-9]{2,8})\)\s+([A-Za-z0-9★*._-]+)\s*$"
)
_SET_ONLY_RE = re.compile(r"^(.*?)\s+\(([A-Za-z0-9]{2,8})\)\s*$")
_BRACKET_PRINTING_RE = re.compile(
    r"^(.*?)\s+\[([A-Za-z0-9]{2,8})\s*[:#]\s*([A-Za-z0-9★*._-]+)\]\s*$"
)


def parse_exported_decklist(text: str) -> list[DeckCard]:
    """Interpreta una exportación de Moxfield o una lista sencilla."""
    current_zone = "mainboard"
    parsed: list[DeckCard] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        heading = line.rstrip(":").strip().lower()
        if heading in _ZONE_HEADINGS:
            current_zone = _ZONE_HEADINGS[heading]
            continue

        line = re.sub(r"\s+\*(?:F|E)\*\s*$", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\s+#.+$", "", line).strip()

        match = _QUANTITY_RE.match(line)
        if not match:
            continue

        quantity = int(match.group(1))
        remainder = match.group(2).strip()
        name = remainder
        set_code: str | None = None
        collector_number: str | None = None

        printing = _SET_AND_NUMBER_RE.match(remainder)
        if printing:
            name, set_code, collector_number = printing.groups()
        else:
            printing = _BRACKET_PRINTING_RE.match(remainder)
            if printing:
                name, set_code, collector_number = printing.groups()
            else:
                printing = _SET_ONLY_RE.match(remainder)
                if printing:
                    name, set_code = printing.groups()

        name = name.strip()
        if not name:
            continue

        parsed.append(
            DeckCard(
                quantity=max(quantity, 1),
                name=name,
                zone=current_zone,
                set_code=set_code.lower() if set_code else None,
                collector_number=collector_number,
            )
        )

    return merge_cards(parsed)


def merge_cards(cards: list[DeckCard]) -> list[DeckCard]:
    merged: OrderedDict[tuple[str, str, str | None, str | None], DeckCard] = OrderedDict()
    for card in cards:
        key = (
            card.zone,
            card.name.casefold(),
            card.set_code.casefold() if card.set_code else None,
            card.collector_number,
        )
        if key in merged:
            merged[key].quantity += card.quantity
        else:
            merged[key] = DeckCard(
                quantity=card.quantity,
                name=card.name,
                zone=card.zone,
                set_code=card.set_code,
                collector_number=card.collector_number,
            )
    return list(merged.values())
