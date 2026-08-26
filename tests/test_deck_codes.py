from mtg_downloader.deck_codes import assign_deck_codes, codes_by_card


def test_assign_deck_codes_makes_three_letter_codes_unique() -> None:
    codes = assign_deck_codes(["Atraxa", "Atraxa infect", "Átraxa tokens"])

    assert codes[0] == "ATR"
    assert len(set(codes)) == 3
    assert all(len(code) == 3 and code.isalpha() for code in codes)


def test_assign_deck_codes_handles_short_and_symbol_only_names() -> None:
    codes = assign_deck_codes(["Ur", "!!!"])

    assert codes == ["URX", "XXX"]


def test_codes_by_card_uses_deck_entry_ranges() -> None:
    summaries = [
        {"name": "Atraxa", "start_index": 0, "end_index": 2},
        {"name": "Breya", "start_index": 2, "end_index": 4},
    ]

    assert codes_by_card(summaries, 4) == ["ATR", "ATR", "BRE", "BRE"]
