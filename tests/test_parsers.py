from mtg_downloader.decklist import parse_exported_decklist
from mtg_downloader.moxfield import extract_deck_id, parse_deck


def test_extract_deck_id_from_url() -> None:
    assert (
        extract_deck_id(
            "https://www.moxfield.com/decks/oEWXWHM5eEGMmopExLWRCA"
        )
        == "oEWXWHM5eEGMmopExLWRCA"
    )


def test_parse_exported_decklist() -> None:
    cards = parse_exported_decklist(
        """
Commander:
1 Sauron, the Dark Lord (LTR) 224

Deck:
1 Sol Ring (CMM) 396
10 Swamp (FDN) 277
"""
    )
    assert len(cards) == 3
    assert cards[0].zone == "commanders"
    assert cards[0].name == "Sauron, the Dark Lord"
    assert cards[1].set_code == "cmm"
    assert cards[2].quantity == 10


def test_parse_old_moxfield_payload() -> None:
    data = {
        "name": "Prueba",
        "commanders": {
            "cmd": {
                "quantity": 1,
                "card": {
                    "name": "Atraxa, Praetors' Voice",
                    "set": "2xm",
                    "cn": "190",
                },
            }
        },
        "mainboard": {
            "ring": {
                "quantity": 1,
                "card": {
                    "name": "Sol Ring",
                    "set": "cmm",
                    "cn": "396",
                },
            }
        },
    }
    name, cards = parse_deck(data)
    assert name == "Prueba"
    assert len(cards) == 2


def test_parse_current_boards_payload() -> None:
    data = {
        "name": "Prueba V3",
        "boards": {
            "commanders": {
                "count": 1,
                "cards": {
                    "cmd": {
                        "quantity": 1,
                        "card": {
                            "name": "Sauron, the Dark Lord",
                            "set": "ltr",
                            "cn": "224",
                        },
                    }
                },
            },
            "mainboard": {
                "count": 10,
                "cards": {
                    "swamp": {
                        "quantity": 10,
                        "card": {
                            "name": "Swamp",
                            "set": "fdn",
                            "cn": "277",
                        },
                    }
                },
            },
        },
    }
    name, cards = parse_deck(data)
    assert name == "Prueba V3"
    assert len(cards) == 2
    assert cards[1].quantity == 10
