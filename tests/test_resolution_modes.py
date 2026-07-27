from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


class ModeClient(ScryfallClient):
    def __init__(self) -> None:
        super().__init__(Path("/tmp/moxfield_mode_cache"), image_quality="png")
        self.calls = []

    def _get_card_by_printing(self, set_code, collector_number, language):
        self.calls.append(("printing", set_code, collector_number, language))
        return None

    def _find_spanish_printing(self, name):
        self.calls.append(("spanish", name))
        return {
            "lang": "es",
            "printed_name": "Montaña",
            "name": "Mountain",
            "set": "m21",
            "collector_number": "312",
            "image_uris": {"png": "https://example.com/es.png"},
        }

    def _get_named(self, name):
        self.calls.append(("named", name))
        return {
            "lang": "en",
            "name": name,
            "set": "m21",
            "collector_number": "312",
            "image_uris": {"png": "https://example.com/en.png"},
        }


def test_exact_only_does_not_change_printing() -> None:
    client = ModeClient()
    try:
        result = client.resolve(
            DeckCard(
                quantity=1,
                name="Mountain",
                set_code="m20",
                collector_number="279",
            ),
            resolution_mode="exact_only",
        )
    finally:
        client.close()

    assert result.status == "No encontrada"
    assert ("spanish", "Mountain") not in client.calls
    assert ("named", "Mountain") not in client.calls


def test_flexible_ignores_exact_printing() -> None:
    client = ModeClient()
    try:
        result = client.resolve(
            DeckCard(
                quantity=1,
                name="Mountain",
                set_code="m20",
                collector_number="279",
            ),
            resolution_mode="flexible",
        )
    finally:
        client.close()

    assert result.status == "Impresión flexible en español"
    assert not any(call[0] == "printing" for call in client.calls)


def test_exact_only_requires_printing_data() -> None:
    client = ModeClient()
    try:
        result = client.resolve(
            DeckCard(quantity=1, name="Mountain"),
            resolution_mode="exact_only",
        )
    finally:
        client.close()

    assert result.status == "Sin impresión exacta"
