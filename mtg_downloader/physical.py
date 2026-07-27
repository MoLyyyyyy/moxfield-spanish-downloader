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


def physical_cards(cards: list[ResolvedCard]) -> list[PhysicalCard]:
    result: list[PhysicalCard] = []
    sequence = 1
    for card in cards:
        for allocation_index, variant in enumerate(effective_variants(card), start=1):
            for copy_index in range(1, variant.quantity + 1):
                result.append(
                    PhysicalCard(
                        sequence=sequence,
                        source=card.source,
                        variant=variant,
                        allocation_index=allocation_index,
                        copy_in_allocation=copy_index,
                    )
                )
                sequence += 1
    return result
