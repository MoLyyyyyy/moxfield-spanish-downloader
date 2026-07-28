from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient


def candidate(
    card_id,
    language,
    set_code,
    number,
    highres,
    released_at="2025-01-01",
):
    return {
        "id": card_id,
        "lang": language,
        "name": "Arcane Signet",
        "printed_name": "Sello Arcano" if language == "es" else None,
        "set": set_code,
        "collector_number": number,
        "image_status": "highres_scan" if highres else "lowres",
        "highres_image": highres,
        "released_at": released_at,
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



def test_manual_double_faced_candidate_preserves_both_faces() -> None:
    candidate_data = {
        "id": "dfc-en",
        "lang": "en",
        "name": "Studious First-Year // Rampant Growth",
        "set": "sos",
        "collector_number": "162",
        "image_status": "highres_scan",
        "highres_image": True,
        "card_faces": [
            {
                "name": "Studious First-Year",
                "image_uris": {
                    "png": "https://x/studious-front.png",
                },
            },
            {
                "name": "Rampant Growth",
                "image_uris": {
                    "png": "https://x/rampant-back.png",
                },
            },
        ],
    }
    client = AlternativesClient()
    try:
        result = client.resolve_from_candidate(
            DeckCard(
                1,
                "Studious First-Year / Rampant Growth",
                set_code="sos",
            ),
            candidate_data,
            status="Selección manual",
        )
    finally:
        client.close()

    assert result.selected_set == "sos"
    assert [face.label for face in result.faces] == [
        "Studious First-Year",
        "Rampant Growth",
    ]
    assert [face.url for face in result.faces] == [
        "https://x/studious-front.png",
        "https://x/rampant-back.png",
    ]



class ChronologicalAlternativesClient(ScryfallClient):
    def __init__(self):
        super().__init__(
            Path("/tmp/moxfield_alternatives_chronological"),
            image_quality="png",
        )

    def _search_printings(self, name, language):
        if language == "es":
            return [
                candidate(
                    "es-older-high",
                    "es",
                    "old",
                    "1",
                    True,
                    "2024-02-01",
                ),
                candidate(
                    "es-newest-low",
                    "es",
                    "new",
                    "2",
                    False,
                    "2026-07-01",
                ),
            ]
        return [
            candidate(
                "en-middle-high",
                "en",
                "mid",
                "3",
                True,
                "2025-10-15",
            ),
            candidate(
                "en-oldest-high",
                "en",
                "anc",
                "4",
                True,
                "2023-01-01",
            ),
        ]


def test_search_alternatives_are_newest_first_across_languages() -> None:
    client = ChronologicalAlternativesClient()
    try:
        alternatives = client.search_alternatives(
            "Arcane Signet",
            languages=("es", "en"),
            highres_only=False,
            max_results=12,
        )
    finally:
        client.close()

    assert [item["id"] for item in alternatives] == [
        "es-newest-low",
        "en-middle-high",
        "es-older-high",
        "en-oldest-high",
    ]
