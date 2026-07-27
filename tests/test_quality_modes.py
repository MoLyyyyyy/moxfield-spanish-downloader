from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


def card(lang, set_code, number, image_status, highres):
    return {
        "lang": lang,
        "name": "Arcane Signet",
        "printed_name": "Sello Arcano" if lang == "es" else None,
        "set": set_code,
        "collector_number": number,
        "image_status": image_status,
        "highres_image": highres,
        "image_uris": {"png": f"https://example.com/{lang}-{set_code}.png"},
    }


class QualityClient(ScryfallClient):
    def __init__(self):
        super().__init__(Path("/tmp/moxfield_quality_cache"), image_quality="png")

    def _get_card_by_printing(self, set_code, collector_number, language):
        if language == "es":
            return card("es", set_code, collector_number, "lowres", False)
        return card("en", set_code, collector_number, "highres_scan", True)

    def _find_printing(self, name, *, language, prefer_highres):
        return card(
            language,
            "other",
            "1",
            "highres_scan" if prefer_highres else "lowres",
            prefer_highres,
        )


def test_prefer_highres_skips_exact_spanish_lowres():
    client = QualityClient()
    try:
        result = client.resolve(
            DeckCard(1, "Arcane Signet", set_code="tmc", collector_number="57"),
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.status == "Misma impresión en inglés"
    assert result.image_status == "highres_scan"


def test_allow_lowres_keeps_exact_spanish_priority():
    client = QualityClient()
    try:
        result = client.resolve(
            DeckCard(1, "Arcane Signet", set_code="tmc", collector_number="57"),
            resolution_mode="exact_first",
            quality_mode="allow_lowres",
        )
    finally:
        client.close()

    assert result.status == "Misma impresión en español"
    assert result.image_status == "lowres"


class LowresOnlyClient(QualityClient):
    def _get_card_by_printing(self, set_code, collector_number, language):
        lang = "es" if language == "es" else "en"
        return card(lang, set_code, collector_number, "lowres", False)

    def _find_printing(self, name, *, language, prefer_highres):
        return card(language, "other", "1", "lowres", False)


def test_highres_only_rejects_all_lowres_candidates():
    client = LowresOnlyClient()
    try:
        result = client.resolve(
            DeckCard(1, "Arcane Signet", set_code="tmc", collector_number="57"),
            resolution_mode="exact_first",
            quality_mode="highres_only",
        )
    finally:
        client.close()

    assert result.status == "Sin alta resolución"
    assert not result.faces
