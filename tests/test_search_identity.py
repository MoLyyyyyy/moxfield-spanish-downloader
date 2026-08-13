from mtg_downloader.models import DeckCard, ResolvedCard
from mtg_downloader.search_identity import (
    resolved_search_name,
    source_printing_key,
)


def test_reskin_uses_scryfall_canonical_name_for_searches() -> None:
    card = ResolvedCard(
        source=DeckCard(
            1,
            "Paths of the Dead",
            set_code="ltc",
            collector_number="362",
        ),
        status="Misma impresión en inglés",
        printed_name="Paths of the Dead",
        selected_set="ltc",
        collector_number="362",
        scryfall_data={
            "name": "Cavern of Souls",
            "printed_name": "Paths of the Dead",
        },
    )

    assert resolved_search_name(card) == "Cavern of Souls"


def test_source_printing_key_distinguishes_nazgul_collectors() -> None:
    first = DeckCard(1, "Nazgûl", set_code="ltr", collector_number="336")
    second = DeckCard(1, "Nazgûl", set_code="ltr", collector_number="335")

    assert source_printing_key(first) != source_printing_key(second)

from pathlib import Path

from mtg_downloader.scryfall import ScryfallClient


class CanonicalPrintingClient(ScryfallClient):
    def __init__(self) -> None:
        super().__init__(Path("/tmp/proxy-maker-canonical-printing-test"))

    def _get_card_by_printing(self, set_code, collector_number, language):
        assert set_code == "ltc"
        assert collector_number == "362"
        return {
            "name": "Cavern of Souls",
            "printed_name": "Paths of the Dead",
        }


def test_exact_printing_can_resolve_oracle_name_for_reskin() -> None:
    client = CanonicalPrintingClient()
    try:
        name = client.canonical_name_for_printing(
            DeckCard(
                1,
                "Paths of the Dead",
                set_code="ltc",
                collector_number="362",
            )
        )
    finally:
        client.close()

    assert name == "Cavern of Souls"


def test_mpcfill_design_name_does_not_replace_source_identity() -> None:
    card = ResolvedCard(
        source=DeckCard(1, "Paths of the Dead", set_code="ltc", collector_number="362"),
        status="Diseño MPCFill",
        provider="mpcfill",
        scryfall_data={"name": "Fancy Custom Frame by Artist"},
    )
    assert resolved_search_name(card) == "Paths of the Dead"


def test_mpcfill_preserved_canonical_name_is_reused() -> None:
    card = ResolvedCard(
        source=DeckCard(1, "Paths of the Dead", set_code="ltc", collector_number="362"),
        status="Diseño MPCFill",
        provider="mpcfill",
        scryfall_data={
            "name": "Fancy Custom Frame by Artist",
            "canonical_name": "Cavern of Souls",
        },
    )
    assert resolved_search_name(card) == "Cavern of Souls"
