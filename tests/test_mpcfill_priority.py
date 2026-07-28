from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.mpcfill import DEFAULT_PREFERRED_SOURCES, MpcFillClient


class FakeMpcClient(MpcFillClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_mpcfill_test"))

    def _search_identifiers(self, *args, **kwargs):
        return ["1", "2", "3"]

    def _get_cards(self, identifiers):
        return [
            {
                "identifier": "1",
                "name": "Card A",
                "language": "EN",
                "dpi": 1200,
                "sourceName": "OtherArtist",
                "download_url": "https://example.com/1.jpg",
            },
            {
                "identifier": "2",
                "name": "Card B",
                "language": "EN",
                "dpi": 800,
                "sourceName": "PsilosX",
                "download_url": "https://example.com/2.jpg",
            },
            {
                "identifier": "3",
                "name": "Card C",
                "language": "EN",
                "dpi": 700,
                "sourceName": "Chilli_Axe",
                "download_url": "https://example.com/3.jpg",
            },
        ]


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

    assert results[0]["sourceName"] == "PsilosX"
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
