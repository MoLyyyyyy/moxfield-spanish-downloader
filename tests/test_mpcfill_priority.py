from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.mpcfill import (
    DEFAULT_PREFERRED_SOURCES,
    MpcFillClient,
    mpc_candidate_mentions_set_code,
)


def design(
    identifier: str,
    source: str,
    *,
    dpi: int = 800,
    language: str = "EN",
):
    return {
        "identifier": identifier,
        "name": f"Card {identifier}",
        "language": language,
        "dpi": dpi,
        "priority": 1,
        "sourceName": source,
        "sourceType": "Google Drive",
        "download_url": f"https://example.com/{identifier}.jpg",
    }


class FakeMpcClient(MpcFillClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_mpcfill_test"))
        self.search_calls = []

    def _search_identifiers(self, *args, **kwargs):
        self.search_calls.append(kwargs)
        return ["1", "2", "3"]

    def _get_cards(self, identifiers):
        cards = {
            "1": design("1", "OtherArtist", dpi=1200),
            "2": design("2", "PsilosX proxy drive", dpi=800),
            "3": design("3", "Chilli_Axe", dpi=700),
        }
        return [cards[value] for value in identifiers]


def test_search_designs_prioritizes_preferred_sources() -> None:
    client = FakeMpcClient()
    try:
        results = client.search_designs(
            "Lightning Bolt",
            languages=("EN",),
            minimum_dpi=300,
            max_results=3,
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
        )
    finally:
        client.close()

    assert results[0]["sourceName"] == "PsilosX proxy drive"
    assert results[1]["sourceName"] == "Chilli_Axe"
    assert results[2]["sourceName"] == "OtherArtist"


def test_resolve_auto_uses_preferred_source_when_available() -> None:
    client = FakeMpcClient()
    try:
        result = client.resolve_auto(
            DeckCard(1, "Lightning Bolt"),
            preferred_language="en",
            allow_language_fallback=False,
            quality_mode="prefer_highres",
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
        )
    finally:
        client.close()

    assert result.provider == "mpcfill"
    assert result.faces
    assert result.faces[0].url.endswith("2.jpg")


class QualityFallbackClient(MpcFillClient):
    def __init__(self):
        super().__init__(
            Path("/tmp/proxy_maker_mpcfill_quality_test")
        )
        self.minimum_dpi_calls = []
        self.fuzzy_calls = []

    def search_designs(self, name, **kwargs):
        minimum_dpi = kwargs["minimum_dpi"]
        self.minimum_dpi_calls.append(minimum_dpi)
        self.fuzzy_calls.append(kwargs.get("fuzzy_search"))
        if minimum_dpi >= 600:
            return []
        return [design("low", "MrTeferi", dpi=450)]


def test_prefer_highres_falls_back_to_300_dpi() -> None:
    client = QualityFallbackClient()
    try:
        result = client.resolve_auto(
            DeckCard(1, "Lightning Bolt"),
            preferred_language="en",
            allow_language_fallback=False,
            quality_mode="prefer_highres",
        )
    finally:
        client.close()

    assert result.faces
    assert client.minimum_dpi_calls == [600, 300]
    assert "calidad de respaldo" in result.status


def test_flexible_resolution_enables_fuzzy_search() -> None:
    client = QualityFallbackClient()
    try:
        client.resolve_auto(
            DeckCard(1, "Fire // Ice"),
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="flexible",
            quality_mode="allow_lowres",
        )
    finally:
        client.close()

    assert client.fuzzy_calls == [True]


class ApiShapeClient(MpcFillClient):
    def __init__(self):
        super().__init__(
            Path("/tmp/proxy_maker_mpcfill_api_test")
        )
        self.requests = []

    def _source_documents(self):
        return {
            "other": {"pk": 1, "name": "Other Artist"},
            "psilos": {"pk": 2, "name": "PsilosX Proxy Drive"},
            "chilli": {"pk": 3, "name": "Chilli Axe"},
            "teferi": {"pk": 4, "name": "Mr_Teferi"},
        }

    def _request_json(self, path, *, method="GET", payload=None):
        self.requests.append((path, payload))
        if path == "3/editorSearch/":
            query_key = next(iter(payload["queries"]))
            return {"results": {query_key: ["abc", "def"]}}
        raise AssertionError(path)


def test_current_editor_search_api_and_source_order() -> None:
    client = ApiShapeClient()
    try:
        identifiers = client._search_identifiers(
            "Lightning Bolt",
            languages=("EN",),
            minimum_dpi=300,
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
            fuzzy_search=True,
        )
    finally:
        client.close()

    path, payload = client.requests[0]
    assert path == "3/editorSearch/"
    assert isinstance(payload["queries"], dict)
    assert payload["searchSettings"][
        "searchTypeSettings"
    ]["fuzzySearch"]
    rows = payload["searchSettings"]["sourceSettings"]["sources"]
    assert [row[0] for row in rows[:3]] == [4, 2, 3]
    assert identifiers == ["abc", "def"]



def test_new_preferred_sources_are_registered() -> None:
    assert "CompC" in DEFAULT_PREFERRED_SOURCES
    assert "Hathwellcrisping" in DEFAULT_PREFERRED_SOURCES



def test_set_code_is_detected_in_candidate_name_or_url() -> None:
    candidate = design(
        "hob-1",
        "PsilosX",
        dpi=800,
    )
    candidate["name"] = "Beorn the Fierce (HOB)"
    candidate["download_url"] = "https://example.com/Beorn_HOB_119.jpg"
    assert mpc_candidate_mentions_set_code(candidate, "hob")


def test_auto_selection_prefers_same_set_code() -> None:
    class SetCodeClient(MpcFillClient):
        def __init__(self):
            super().__init__(Path("/tmp/proxy_maker_set_code_test"))

        def _search_identifiers(self, *args, **kwargs):
            return ["a", "b"]

        def _get_cards(self, identifiers):
            cards = {
                "a": {
                    **design("a", "MrTeferi", dpi=1000),
                    "name": "Random Artist Version",
                    "download_url": "https://example.com/random.jpg",
                },
                "b": {
                    **design("b", "OtherArtist", dpi=700),
                    "name": "Lightning Bolt (HOB)",
                    "download_url": "https://example.com/bolt_hob.jpg",
                },
            }
            return [cards[value] for value in identifiers]

    client = SetCodeClient()
    try:
        result = client.resolve_auto(
            DeckCard(
                1,
                "Lightning Bolt",
                set_code="hob",
                collector_number="119",
            ),
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="flexible",
            quality_mode="prefer_highres",
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
        )
    finally:
        client.close()

    assert result.faces
    assert result.faces[0].url.endswith("bolt_hob.jpg")



class SetCodeAwareClient(MpcFillClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_mpcfill_set_code_test"))

    def search_designs(self, name, **kwargs):
        return [
            {
                "identifier": "sos",
                "name": "Studious First-Year / Rampant Growth (SOS)",
                "language": "EN",
                "dpi": 800,
                "priority": 1,
                "sourceName": "PsilosX",
                "download_url": "https://example.com/sos.jpg",
            },
            {
                "identifier": "tdc",
                "name": "Rampant Growth (TDC)",
                "language": "EN",
                "dpi": 1200,
                "priority": 1,
                "sourceName": "PsilosX",
                "download_url": "https://example.com/tdc.jpg",
            },
        ]


def test_set_code_disambiguates_shared_names() -> None:
    client = SetCodeAwareClient()
    try:
        result = client.resolve_auto(
            DeckCard(
                1,
                "Studious First-Year / Rampant Growth",
                set_code="sos",
            ),
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
        )
    finally:
        client.close()

    assert result.provider == "mpcfill"
    assert result.faces
    assert result.faces[0].url.endswith("sos.jpg")
