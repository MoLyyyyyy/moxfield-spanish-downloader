from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import (
    ScryfallClient,
    _candidate_matches_full_name,
    _canonical_card_name,
)


def printing(
    name: str,
    set_code: str,
    number: str,
    *,
    language: str = "en",
):
    return {
        "id": f"{set_code}-{number}-{language}",
        "lang": language,
        "name": name,
        "set": set_code,
        "collector_number": number,
        "image_status": "highres_scan",
        "highres_image": True,
        "image_uris": {
            "large": f"https://example.com/{set_code}-{number}.jpg"
        },
    }


class SearchResponseClient(ScryfallClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_scryfall_name_test"))
        self.queries = []

    def _request_json(
        self,
        path,
        *,
        params=None,
        allow_not_found=False,
    ):
        self.queries.append(params["q"])
        return {
            "data": [
                printing(
                    "Studious First-Year // Rampant Growth",
                    "sos",
                    "162",
                ),
                printing("Rampant Growth", "tdc", "265"),
            ]
        }


def test_single_slash_is_canonicalised_to_double_slash() -> None:
    assert (
        _canonical_card_name(
            "Studious First-Year / Rampant Growth"
        )
        == "Studious First-Year // Rampant Growth"
    )


def test_full_name_matching_rejects_a_matching_face_only() -> None:
    split = printing(
        "Studious First-Year // Rampant Growth",
        "sos",
        "162",
    )
    assert not _candidate_matches_full_name(split, "Rampant Growth")
    assert _candidate_matches_full_name(
        split,
        "Studious First-Year / Rampant Growth",
    )


def test_search_filters_results_by_complete_card_name() -> None:
    client = SearchResponseClient()
    try:
        rampant = client._search_printings(
            "Rampant Growth",
            "en",
        )
        studious = client._search_printings(
            "Studious First-Year / Rampant Growth",
            "en",
        )
    finally:
        client.close()

    assert [card["set"] for card in rampant] == ["tdc"]
    assert [card["set"] for card in studious] == ["sos"]


def test_set_only_exact_first_uses_the_requested_set() -> None:
    client = SearchResponseClient()
    try:
        result = client.resolve(
            DeckCard(
                1,
                "Studious First-Year / Rampant Growth",
                set_code="sos",
            ),
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.selected_set == "sos"
    assert result.faces
    assert result.faces[0].url.endswith("sos-162.jpg")
    assert any("set:sos" in query for query in client.queries)


def test_two_shared_names_resolve_to_different_scryfall_printings() -> None:
    client = SearchResponseClient()
    try:
        studious = client.resolve(
            DeckCard(
                1,
                "Studious First-Year / Rampant Growth",
                set_code="sos",
            ),
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
        rampant = client.resolve(
            DeckCard(
                1,
                "Rampant Growth",
                set_code="tdc",
            ),
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert studious.selected_set == "sos"
    assert rampant.selected_set == "tdc"
    assert studious.faces[0].url != rampant.faces[0].url
