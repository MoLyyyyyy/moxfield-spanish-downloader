from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from .models import ResolvedCard
from .review import is_problematic, problem_reasons
from .selections import card_has_multiple_arts


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
    indices: list[int] | None = None,
) -> list[DeckCategory]:
    groups: OrderedDict[str, list[tuple[int, ResolvedCard]]] = OrderedDict(
        (key, []) for key, _ in CATEGORY_ORDER
    )

    source_indices = indices if indices is not None else list(range(len(cards)))
    if len(source_indices) != len(cards):
        raise ValueError("El número de índices no coincide con las cartas.")
    for index, card in zip(source_indices, cards):
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
    provider = {
        "mpcfill": "MPCFill",
        "magiccardsinfo": "MagicCards.info",
    }.get(card.provider, "Scryfall")
    set_code = (card.selected_set or "?").upper()
    collector = card.collector_number or "?"
    language = (card.language or "?").upper()
    return f"{provider} · {set_code} {collector} · {language}"


def gallery_status_label(card: ResolvedCard) -> str:
    if is_problematic(card):
        reasons = ", ".join(problem_reasons(card))
        return f"⚠️ {reasons}"
    if card_has_multiple_arts(card):
        return f"🎨 {len(card.allocations)} ilustraciones"
    if card.provider == "mpcfill":
        return "🟣 MPCFill"
    if card.image_status == "lowres" or card.highres_image is False:
        return "🟡 Baja resolución"
    if card.status == "Selección manual":
        return "🔵 Selección manual"
    return "🟢 Automática"


def filtered_indices(
    cards: list[ResolvedCard],
    *,
    query: str = "",
    provider: str = "Todos",
    state: str = "Todos",
    language: str = "Todos",
) -> list[int]:
    result: list[int] = []
    query_value = query.casefold().strip()
    for index, card in enumerate(cards):
        if query_value and query_value not in card.source.name.casefold():
            continue
        if provider == "Scryfall" and card.provider != "scryfall":
            continue
        if provider == "MPCFill" and card.provider != "mpcfill":
            continue
        if language != "Todos" and (card.language or "").casefold() != language.casefold():
            continue
        if state == "Pendientes" and not is_problematic(card):
            continue
        if state == "Manuales" and not (
            card.status == "Selección manual"
            or card.provider == "mpcfill"
            or card.allocations
        ):
            continue
        if state == "Múltiples artes" and not card_has_multiple_arts(card):
            continue
        if state == "Baja resolución" and not (
            card.image_status == "lowres" or card.highres_image is False
        ):
            continue
        if state == "Sin imagen" and card.faces:
            continue
        result.append(index)
    return result
