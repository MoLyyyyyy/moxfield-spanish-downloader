from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from .models import ResolvedCard


@dataclass(frozen=True, slots=True)
class DeckCategory:
    key: str
    label: str
    cards: tuple[tuple[int, ResolvedCard], ...]

    @property
    def quantity(self) -> int:
        return sum(card.source.quantity for _, card in self.cards)


CATEGORY_ORDER = (
    ("commanders", "Comandante"),
    ("companions", "Compañero"),
    ("creatures", "Criaturas"),
    ("planeswalkers", "Planeswalkers"),
    ("instants", "Instantáneos"),
    ("sorceries", "Conjuros"),
    ("enchantments", "Encantamientos"),
    ("artifacts", "Artefactos"),
    ("battles", "Batallas"),
    ("lands", "Tierras"),
    ("signatureSpells", "Hechizos distintivos"),
    ("other", "Otros"),
    ("sideboard", "Banquillo"),
    ("maybeboard", "Maybeboard"),
)


def category_key(card: ResolvedCard) -> str:
    zone = card.source.zone
    if zone in {"commanders", "partners"}:
        return "commanders"
    if zone == "companions":
        return "companions"
    if zone == "sideboard":
        return "sideboard"
    if zone == "maybeboard":
        return "maybeboard"
    if zone == "signatureSpells":
        return "signatureSpells"

    type_line = (card.type_line or "").casefold()
    if "creature" in type_line:
        return "creatures"
    if "planeswalker" in type_line:
        return "planeswalkers"
    if "instant" in type_line:
        return "instants"
    if "sorcery" in type_line:
        return "sorceries"
    if "enchantment" in type_line:
        return "enchantments"
    if "artifact" in type_line:
        return "artifacts"
    if "battle" in type_line:
        return "battles"
    if "land" in type_line:
        return "lands"
    return "other"


def group_deck(
    cards: list[ResolvedCard],
) -> list[DeckCategory]:
    groups: OrderedDict[str, list[tuple[int, ResolvedCard]]] = OrderedDict(
        (key, []) for key, _ in CATEGORY_ORDER
    )

    for index, card in enumerate(cards):
        groups[category_key(card)].append((index, card))

    label_by_key = dict(CATEGORY_ORDER)
    return [
        DeckCategory(
            key=key,
            label=label_by_key[key],
            cards=tuple(items),
        )
        for key, items in groups.items()
        if items
    ]


def gallery_printing_label(card: ResolvedCard) -> str:
    provider = "MPCFill" if card.provider == "mpcfill" else "Scryfall"
    set_code = (card.selected_set or "?").upper()
    collector = card.collector_number or "?"
    language = (card.language or "?").upper()
    return f"{provider} · {set_code} {collector} · {language}"
