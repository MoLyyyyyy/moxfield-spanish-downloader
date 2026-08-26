from __future__ import annotations

from dataclasses import dataclass

from .models import CardVariant, DeckCard, ResolvedCard
from .selections import effective_variants


@dataclass(frozen=True, slots=True)
class PhysicalCard:
    sequence: int
    source: DeckCard
    variant: CardVariant
    allocation_index: int
    copy_in_allocation: int
    deck_code: str | None = None


def physical_cards(
    cards: list[ResolvedCard],
    deck_codes: list[str | None] | None = None,
) -> list[PhysicalCard]:
    result: list[PhysicalCard] = []
    sequence = 1
    for card_index, card in enumerate(cards):
        deck_code = (
            deck_codes[card_index]
            if deck_codes is not None and card_index < len(deck_codes)
            else None
        )
        for allocation_index, variant in enumerate(effective_variants(card), start=1):
            for copy_index in range(1, variant.quantity + 1):
                result.append(
                    PhysicalCard(
                        sequence=sequence,
                        source=card.source,
                        variant=variant,
                        allocation_index=allocation_index,
                        copy_in_allocation=copy_index,
                        deck_code=deck_code,
                    )
                )
                sequence += 1
    return result
