from mtg_downloader.decklist import parse_exported_decklist


def test_parse_exported_decklist() -> None:
    cards = parse_exported_decklist(
        """
Commander:
1 Beorn the Fierce (HOB) 119 *F*

Deck:
1 Arcane Signet (TMC) 57
27 Forest (M20) 279
"""
    )

    assert len(cards) == 3
    assert cards[0].zone == "commanders"
    assert cards[0].name == "Beorn the Fierce"
    assert cards[0].set_code == "hob"
    assert cards[0].collector_number == "119"
    assert cards[1].set_code == "tmc"
    assert cards[2].quantity == 27


def test_parser_merges_identical_entries() -> None:
    cards = parse_exported_decklist(
        """
Deck:
4 Mountain (M20) 279
4 Mountain (M20) 279
"""
    )

    assert len(cards) == 1
    assert cards[0].quantity == 8


def test_parser_keeps_different_printings_separate() -> None:
    cards = parse_exported_decklist(
        """
Deck:
4 Mountain (M20) 279
4 Mountain (M21) 312
"""
    )

    assert len(cards) == 2


def test_nine_nazgul_printings_remain_nine_entries() -> None:
    cards = parse_exported_decklist(
        """
1 Nazgûl (LTR) 336
1 Nazgûl (LTR) 335
1 Nazgûl (LTR) 100
1 Nazgûl (LTR) 332
1 Nazgûl (LTR) 334
1 Nazgûl (LTR) 333
1 Nazgûl (LTR) 337
1 Nazgûl (LTR) 338
1 Nazgûl (LTR) 339
"""
    )

    assert len(cards) == 9
    assert {card.collector_number for card in cards} == {
        "100", "332", "333", "334", "335", "336", "337", "338", "339"
    }
