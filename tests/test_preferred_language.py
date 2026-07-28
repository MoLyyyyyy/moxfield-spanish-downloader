from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


def candidate(language: str):
    return {
        "lang": language,
        "name": "Mountain",
        "printed_name": "Montaña" if language == "es" else "Mountain",
        "set": "m20",
        "collector_number": "279",
        "image_status": "highres_scan",
        "highres_image": True,
        "image_uris": {"large": f"https://example.com/{language}.jpg"},
    }


class LanguageClient(ScryfallClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_language_test"))
        self.calls = []

    def _get_card_by_printing(self, set_code, collector_number, language):
        resolved_language = "es" if language == "es" else "en"
        self.calls.append(("exact", resolved_language))
        return candidate(resolved_language)

    def _find_printing(self, name, *, language, prefer_highres):
        self.calls.append(("search", language))
        return candidate(language)


def test_english_can_be_primary() -> None:
    client = LanguageClient()
    try:
        result = client.resolve(
            DeckCard(1, "Mountain", set_code="m20", collector_number="279"),
            preferred_language="en",
            allow_language_fallback=True,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.language == "en"
    assert client.calls == [("exact", "en")]


def test_spanish_can_fallback_for_missing_english() -> None:
    class MissingEnglishClient(LanguageClient):
        def _get_card_by_printing(self, set_code, collector_number, language):
            resolved_language = "es" if language == "es" else "en"
            self.calls.append(("exact", resolved_language))
            return candidate("es") if resolved_language == "es" else None

        def _find_printing(self, name, *, language, prefer_highres):
            self.calls.append(("search", language))
            return candidate("es") if language == "es" else None

    client = MissingEnglishClient()
    try:
        result = client.resolve(
            DeckCard(1, "Mountain", set_code="m20", collector_number="279"),
            preferred_language="en",
            allow_language_fallback=True,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.language == "es"
    assert "respaldo en español" in result.status.casefold()
