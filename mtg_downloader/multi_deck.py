from __future__ import annotations

from dataclasses import dataclass

from .decklist import parse_exported_decklist
from .models import DeckCard
from .print_layout import SheetUsage, calculate_sheet_usage


@dataclass(frozen=True, slots=True)
class DeckSummary:
    index: int
    name: str
    entries: int
    copies: int
    sheet_usage: SheetUsage


@dataclass(frozen=True, slots=True)
class MultiDeckResult:
    cards: list[DeckCard]
    summaries: tuple[DeckSummary, ...]
    combined_usage: SheetUsage
    separate_sheet_count: int
    separate_empty_slots: int

    @property
    def deck_count(self) -> int:
        return len(self.summaries)

    @property
    def saved_sheets(self) -> int:
        return max(
            self.separate_sheet_count - self.combined_usage.sheet_count,
            0,
        )

    @property
    def saved_paid_slots(self) -> int:
        return self.saved_sheets * self.combined_usage.slots_per_sheet

    @property
    def deck_names(self) -> tuple[str, ...]:
        return tuple(summary.name for summary in self.summaries)


def parse_multiple_decklists(
    decklists: list[str] | tuple[str, ...],
    *,
    include_sideboard: bool = False,
    include_maybeboard: bool = False,
) -> MultiDeckResult:
    """Parse decks independently and concatenate them without page breaks."""
    if not decklists:
        raise ValueError("Añade al menos una lista de mazo.")

    combined_cards: list[DeckCard] = []
    summaries: list[DeckSummary] = []

    for index, text in enumerate(decklists, start=1):
        if not str(text).strip():
            raise ValueError(f"Pega la lista del mazo {index}.")

        cards = parse_exported_decklist(str(text))
        if not include_sideboard:
            cards = [
                card for card in cards
                if card.zone != "sideboard"
            ]
        if not include_maybeboard:
            cards = [
                card for card in cards
                if card.zone != "maybeboard"
            ]

        if not cards:
            raise ValueError(
                f"No se ha interpretado ninguna carta en el mazo {index}. "
                "Cada línea debe comenzar por una cantidad, por ejemplo "
                "`1 Arcane Signet (TMC) 57`."
            )

        copies = sum(card.quantity for card in cards)
        summary = DeckSummary(
            index=index,
            name=cards[0].name,
            entries=len(cards),
            copies=copies,
            sheet_usage=calculate_sheet_usage(copies),
        )
        summaries.append(summary)
        combined_cards.extend(cards)

    total_copies = sum(summary.copies for summary in summaries)
    combined_usage = calculate_sheet_usage(total_copies)

    return MultiDeckResult(
        cards=combined_cards,
        summaries=tuple(summaries),
        combined_usage=combined_usage,
        separate_sheet_count=sum(
            summary.sheet_usage.sheet_count
            for summary in summaries
        ),
        separate_empty_slots=sum(
            summary.sheet_usage.empty_slots
            for summary in summaries
        ),
    )


def serialise_deck_summaries(
    result: MultiDeckResult,
) -> list[dict[str, int | str]]:
    return [
        {
            "index": summary.index,
            "name": summary.name,
            "entries": summary.entries,
            "copies": summary.copies,
            "sheet_count": summary.sheet_usage.sheet_count,
            "empty_slots": summary.sheet_usage.empty_slots,
        }
        for summary in result.summaries
    ]
