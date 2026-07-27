from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


class DummyScryfallClient(ScryfallClient):
    def __init__(self) -> None:
        super().__init__(Path("/tmp/moxfield_test_cache"), image_quality="png")
        self.calls = []

    def _get_card_by_printing(self, set_code: str, collector_number: str, language: str | None):
        self.calls.append(("printing", set_code, collector_number, language))
        if language == "es":
            return None
        if language is None:
            return {
                "lang": "en",
                "name": "Arcane Signet",
                "set": set_code,
                "collector_number": collector_number,
                "image_uris": {"png": "https://example.com/card.png"},
            }
        return None

    def _find_spanish_printing(self, name: str):
        self.calls.append(("spanish", name))
        return {
            "lang": "es",
            "printed_name": "Sello Arcano",
            "name": "Arcane Signet",
            "set": "plst",
            "collector_number": "1",
            "image_uris": {"png": "https://example.com/es.png"},
        }

    def _get_named(self, name: str):
        self.calls.append(("named", name))
        return {
            "lang": "en",
            "name": "Arcane Signet",
            "set": "plst",
            "collector_number": "2",
            "image_uris": {"png": "https://example.com/en.png"},
        }


def test_exact_english_is_checked_before_other_spanish_printing() -> None:
    client = DummyScryfallClient()
    try:
        resolved = client.resolve(
            DeckCard(
                quantity=1,
                name="Arcane Signet",
                set_code="tmc",
                collector_number="57",
            ),
            allow_english_fallback=True,
        )
    finally:
        client.close()

    assert resolved.status == "Misma impresión en inglés"
    assert resolved.language == "en"
    assert ("spanish", "Arcane Signet") not in client.calls[:2]
