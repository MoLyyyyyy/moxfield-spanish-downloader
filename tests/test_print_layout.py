import pytest

from mtg_downloader.print_layout import calculate_sheet_usage


def test_one_hundred_cards_leave_eight_empty_slots() -> None:
    usage = calculate_sheet_usage(100)

    assert usage.sheet_count == 12
    assert usage.total_slots == 108
    assert usage.empty_slots == 8
    assert usage.cards_to_complete == 8
    assert not usage.is_full


def test_exact_multiple_has_no_empty_slots() -> None:
    usage = calculate_sheet_usage(108)

    assert usage.sheet_count == 12
    assert usage.total_slots == 108
    assert usage.empty_slots == 0
    assert usage.is_full


def test_empty_deck_uses_no_sheets() -> None:
    usage = calculate_sheet_usage(0)

    assert usage.sheet_count == 0
    assert usage.total_slots == 0
    assert usage.empty_slots == 0


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_sheet_usage(-1)
    with pytest.raises(ValueError):
        calculate_sheet_usage(10, slots_per_sheet=0)
