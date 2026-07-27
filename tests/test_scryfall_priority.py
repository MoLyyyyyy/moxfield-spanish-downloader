from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


class DummyScryfallClient(ScryfallClient):
    def __init__(self) -> None:
        super().__init__(Path("/tmp/moxfield_test_cache"), image_quality="png")
        self.calls = []

    def _get_card_by_printing(
        self,
        set_code: str,
        collector_number: str,
        language: str | None,
    ):
        self.calls.append(("printing", set_code, collector_number, language))
        if language == "es":
            return None
        return {
            "lang": "en",
            "name": "Arcane Signet",
            "set": set_code,
            "collector_number": collector_number,
            "image_status": "highres_scan",
            "highres_image": True,
            "image_uris": {"png": "https://example.com/card.png"},
        }

    def _find_printing(self, name, *, language, prefer_highres):
        self.calls.append(("find", name, language, prefer_highres))
        return {
            "lang": language,
            "printed_name": "Sello Arcano" if language == "es" else None,
            "name": "Arcane Signet",
            "set": "plst",
            "collector_number": "1",
            "image_status": "highres_scan",
            "highres_image": True,
            "image_uris": {"png": f"https://example.com/{language}.png"},
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
            quality_mode="allow_lowres",
        )
    finally:
        client.close()

    assert resolved.status == "Misma impresión en inglés"
    assert resolved.language == "en"
    assert client.calls[:2] == [
        ("printing", "tmc", "57", "es"),
        ("printing", "tmc", "57", None),
    ]
