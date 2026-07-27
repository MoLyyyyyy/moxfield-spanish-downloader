from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


def candidate(card_id, language, set_code, number, highres):
    return {
        "id": card_id,
        "lang": language,
        "name": "Arcane Signet",
        "printed_name": "Sello Arcano" if language == "es" else None,
        "set": set_code,
        "collector_number": number,
        "image_status": "highres_scan" if highres else "lowres",
        "highres_image": highres,
        "released_at": "2025-01-01",
        "image_uris": {"png": f"https://x/{card_id}.png"},
    }


class AlternativesClient(ScryfallClient):
    def __init__(self):
        super().__init__(Path("/tmp/moxfield_alternatives"), image_quality="png")

    def _search_printings(self, name, language):
        if language == "es":
            return [
                candidate("es-high", "es", "cmm", "396", True),
                candidate("es-low", "es", "tmc", "57", False),
            ]
        return [
            candidate("en-high", "en", "tmc", "57", True),
            candidate("en-low", "en", "cmm", "396", False),
        ]


def test_search_alternatives_includes_both_languages() -> None:
    client = AlternativesClient()
    try:
        alternatives = client.search_alternatives(
            "Arcane Signet",
            languages=("es", "en"),
            highres_only=False,
            max_results=4,
        )
    finally:
        client.close()

    assert {item["id"] for item in alternatives} == {
        "es-high",
        "es-low",
        "en-high",
        "en-low",
    }


def test_search_alternatives_can_filter_lowres() -> None:
    client = AlternativesClient()
    try:
        alternatives = client.search_alternatives(
            "Arcane Signet",
            languages=("es", "en"),
            highres_only=True,
            max_results=12,
        )
    finally:
        client.close()

    assert [item["id"] for item in alternatives] == [
        "es-high",
        "en-high",
    ]


def test_manual_candidate_becomes_resolved_card() -> None:
    client = AlternativesClient()
    try:
        result = client.resolve_from_candidate(
            DeckCard(2, "Arcane Signet"),
            candidate("es-high", "es", "cmm", "396", True),
            status="Selección manual",
        )
    finally:
        client.close()

    assert result.status == "Selección manual"
    assert result.language == "es"
    assert result.selected_set == "cmm"
    assert result.faces[0].extension == ".png"
