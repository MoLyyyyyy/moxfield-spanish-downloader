from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .decklist import parse_exported_decklist
from .deck_workflow import normalise_deck_config, public_deck_settings
from .models import DeckCard
from .print_layout import SheetUsage, calculate_sheet_usage


@dataclass(frozen=True, slots=True)
class DeckSummary:
    index: int
    name: str
    entries: int
    copies: int
    start_index: int
    end_index: int
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


def _parse_single_deck(
    text: str,
    *,
    index: int,
    include_sideboard: bool,
    include_maybeboard: bool,
) -> list[DeckCard]:
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
    return cards


def parse_deck_configurations(
    deck_configs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> MultiDeckResult:
    """Parse each deck with its own inclusion settings."""
    if not deck_configs:
        raise ValueError("Añade al menos una lista de mazo.")

    combined_cards: list[DeckCard] = []
    summaries: list[DeckSummary] = []

    for index, raw_config in enumerate(deck_configs, start=1):
        config = normalise_deck_config(raw_config)
        cards = _parse_single_deck(
            config["decklist"],
            index=index,
            include_sideboard=config["include_sideboard"],
            include_maybeboard=config["include_maybeboard"],
        )

        start_index = len(combined_cards)
        combined_cards.extend(cards)
        end_index = len(combined_cards)
        copies = sum(card.quantity for card in cards)
        summaries.append(
            DeckSummary(
                index=index,
                name=cards[0].name,
                entries=len(cards),
                copies=copies,
                start_index=start_index,
                end_index=end_index,
                sheet_usage=calculate_sheet_usage(copies),
            )
        )

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


def parse_multiple_decklists(
    decklists: list[str] | tuple[str, ...],
    *,
    include_sideboard: bool = False,
    include_maybeboard: bool = False,
) -> MultiDeckResult:
    """Backward-compatible wrapper using the same settings for every deck."""
    return parse_deck_configurations(
        [
            {
                "decklist": text,
                "include_sideboard": include_sideboard,
                "include_maybeboard": include_maybeboard,
            }
            for text in decklists
        ]
    )


def serialise_deck_summaries(
    result: MultiDeckResult,
    deck_configs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    configs = deck_configs or [{} for _ in result.summaries]
    return [
        {
            "index": summary.index,
            "name": summary.name,
            "entries": summary.entries,
            "copies": summary.copies,
            "start_index": summary.start_index,
            "end_index": summary.end_index,
            "sheet_count": summary.sheet_usage.sheet_count,
            "empty_slots": summary.sheet_usage.empty_slots,
            "settings": public_deck_settings(
                configs[position]
                if position < len(configs)
                else {}
            ),
        }
        for position, summary in enumerate(result.summaries)
    ]
