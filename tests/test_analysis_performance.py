from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


def candidate(language: str, *, highres: bool = True):
    return {
        "lang": language,
        "name": "Mountain",
        "printed_name": "Montaña" if language == "es" else None,
        "set": "m20",
        "collector_number": "279",
        "image_status": "highres_scan" if highres else "lowres",
        "highres_image": highres,
        "image_uris": {"large": f"https://example.com/{language}.jpg"},
    }


class CountingClient(ScryfallClient):
    def __init__(self):
        super().__init__(Path("/tmp/moxfield_performance_cache"))
        self.calls = []

    def _get_card_by_printing(self, set_code, collector_number, language):
        self.calls.append(("exact", language))
        if language == "es":
            return candidate("es", highres=True)
        return candidate("en", highres=True)

    def _find_printing(self, name, *, language, prefer_highres):
        self.calls.append(("search", language))
        return candidate(language, highres=True)


def test_highres_exact_spanish_stops_additional_queries() -> None:
    client = CountingClient()
    try:
        result = client.resolve(
            DeckCard(1, "Mountain", set_code="m20", collector_number="279"),
            allow_english_fallback=True,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.language == "es"
    assert client.calls == [("exact", "es")]
