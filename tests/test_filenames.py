from mtg_downloader.filenames import (
    commander_pdf_filename,
    multi_deck_pdf_filename,
    safe_filename_component,
)
from mtg_downloader.models import DeckCard, ResolvedCard


def test_pdf_filename_uses_first_card_name() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(1, "Beorn the Fierce"),
            status="Encontrada",
        ),
        ResolvedCard(
            source=DeckCard(1, "Arcane Signet"),
            status="Encontrada",
        ),
    ]

    assert commander_pdf_filename(cards) == "Beorn the Fierce.pdf"


def test_pdf_filename_sanitises_double_faced_names() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(1, "Fire // Ice"),
            status="Encontrada",
        )
    ]

    assert commander_pdf_filename(cards) == "Fire - Ice.pdf"


def test_pdf_filename_has_fallback() -> None:
    assert commander_pdf_filename([]) == "proxy-maker.pdf"
    assert safe_filename_component('  <>:"/\\|?*  ') == "proxy-maker"



def test_multiple_decks_get_a_bundle_filename() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(1, "Beorn the Fierce"),
            status="Encontrada",
        )
    ]
    assert multi_deck_pdf_filename(
        ["Beorn the Fierce", "Sauron, the Dark Lord"],
        cards,
    ) == "Beorn the Fierce + Sauron, the Dark Lord.pdf"
