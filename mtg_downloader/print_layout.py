from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SLOTS_PER_SHEET = 9


@dataclass(frozen=True, slots=True)
class SheetUsage:
    card_count: int
    slots_per_sheet: int
    sheet_count: int
    total_slots: int
    empty_slots: int

    @property
    def is_full(self) -> bool:
        return self.empty_slots == 0

    @property
    def cards_to_complete(self) -> int:
        return self.empty_slots


def calculate_sheet_usage(
    card_count: int,
    *,
    slots_per_sheet: int = DEFAULT_SLOTS_PER_SHEET,
) -> SheetUsage:
    """Calculate paid print positions and unused slots on the final sheet."""
    if card_count < 0:
        raise ValueError("El número de cartas no puede ser negativo.")
    if slots_per_sheet < 1:
        raise ValueError("Las posiciones por hoja deben ser mayores que cero.")

    sheet_count = (
        (card_count + slots_per_sheet - 1) // slots_per_sheet
        if card_count
        else 0
    )
    total_slots = sheet_count * slots_per_sheet
    empty_slots = total_slots - card_count

    return SheetUsage(
        card_count=card_count,
        slots_per_sheet=slots_per_sheet,
        sheet_count=sheet_count,
        total_slots=total_slots,
        empty_slots=empty_slots,
    )
