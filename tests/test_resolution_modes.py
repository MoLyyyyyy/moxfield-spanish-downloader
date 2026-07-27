from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


def candidate(language: str):
    return {
        "lang": language,
        "printed_name": "Montaña" if language == "es" else None,
        "name": "Mountain",
        "set": "m21",
        "collector_number": "312",
        "image_status": "highres_scan",
        "highres_image": True,
        "image_uris": {"png": f"https://example.com/{language}.png"},
    }


class ModeClient(ScryfallClient):
    def __init__(self) -> None:
        super().__init__(Path("/tmp/moxfield_mode_cache"), image_quality="png")
        self.calls = []

    def _get_card_by_printing(self, set_code, collector_number, language):
        self.calls.append(("printing", set_code, collector_number, language))
        return None

    def _find_printing(self, name, *, language, prefer_highres):
        self.calls.append(("find", name, language, prefer_highres))
        return candidate(language)


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
    assert not any(call[0] == "find" for call in client.calls)


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



def test_spanish_only_can_fallback_to_english_if_no_spanish_image_exists() -> None:
    class MissingSpanishClient(ModeClient):
        def _find_printing(self, name, *, language, prefer_highres):
            self.calls.append(("find", name, language, prefer_highres))
            if language == "es":
                return None
            return candidate("en")

    client = MissingSpanishClient()
    try:
        result = client.resolve(
            DeckCard(
                quantity=1,
                name="Mountain",
                set_code="m20",
                collector_number="279",
            ),
            allow_english_fallback=False,
            allow_english_if_missing=True,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.language == "en"
    assert "sin imagen en español" in result.status.casefold()


def test_spanish_only_does_not_fallback_if_spanish_image_exists() -> None:
    class ExistingSpanishClient(ModeClient):
        def _find_printing(self, name, *, language, prefer_highres):
            self.calls.append(("find", name, language, prefer_highres))
            return candidate(language)

    client = ExistingSpanishClient()
    try:
        result = client.resolve(
            DeckCard(
                quantity=1,
                name="Mountain",
                set_code="m20",
                collector_number="279",
            ),
            allow_english_fallback=False,
            allow_english_if_missing=True,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.language == "es"
