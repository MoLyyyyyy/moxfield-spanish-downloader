from mtg_downloader.multi_deck import parse_multiple_decklists


DECK_ONE = """Commander:
1 Beorn the Fierce (HOB) 119

Deck:
7 Forest (M20) 279
"""

DECK_TWO = """Commander:
1 Sauron, the Dark Lord (LTR) 224

Deck:
99 Swamp (M20) 272
"""


def test_multiple_decks_are_concatenated_in_input_order() -> None:
    result = parse_multiple_decklists([DECK_ONE, DECK_TWO])

    assert result.deck_count == 2
    assert result.deck_names == (
        "Beorn the Fierce",
        "Sauron, the Dark Lord",
    )
    assert [card.name for card in result.cards[:3]] == [
        "Beorn the Fierce",
        "Forest",
        "Sauron, the Dark Lord",
    ]
    assert result.summaries[0].copies == 8
    assert result.summaries[1].copies == 100


def test_second_deck_fills_first_decks_last_sheet() -> None:
    result = parse_multiple_decklists([DECK_ONE, DECK_TWO])

    assert result.separate_sheet_count == 13
    assert result.combined_usage.sheet_count == 12
    assert result.saved_sheets == 1
    assert result.saved_paid_slots == 9
    assert result.combined_usage.empty_slots == 0


def test_identical_cards_in_different_decks_stay_separate_entries() -> None:
    result = parse_multiple_decklists(
        [
            "1 Commander One\n1 Sol Ring",
            "1 Commander Two\n1 Sol Ring",
        ]
    )

    sol_rings = [
        card for card in result.cards
        if card.name == "Sol Ring"
    ]
    assert len(sol_rings) == 2


def test_empty_configured_deck_is_reported() -> None:
    try:
        parse_multiple_decklists([DECK_ONE, ""])
    except ValueError as exc:
        assert "mazo 2" in str(exc)
    else:
        raise AssertionError("La lista vacía debía producir un error")
