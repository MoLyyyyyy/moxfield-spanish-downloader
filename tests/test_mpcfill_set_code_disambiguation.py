from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.mpcfill import (
    DEFAULT_PREFERRED_SOURCES,
    MpcFillClient,
)


def make_candidate(identifier: str, name: str, *, dpi: int = 800):
    return {
        "identifier": identifier,
        "name": name,
        "language": "EN",
        "dpi": dpi,
        "priority": 1,
        "sourceName": "PsilosX",
        "sourceType": "Google Drive",
        "download_url": f"https://example.com/{identifier}.jpg",
        "downloadLink": f"https://example.com/{identifier}.jpg",
    }


class SingleCardSetCodeClient(MpcFillClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_single_set_code_test"))

    def search_designs(self, name, **kwargs):
        return [
            make_candidate("sos", "Studious First-Year / Rampant Growth (SOS)"),
            make_candidate("tdc", "Rampant Growth (TDC)", dpi=1200),
        ]


def test_single_card_resolution_prefers_matching_set_code() -> None:
    client = SingleCardSetCodeClient()
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

    assert result.faces
    assert result.faces[0].url.endswith("sos.jpg")


class BatchSetCodeClient(MpcFillClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_batch_set_code_test"))

    def _source_rows(self, preferred_sources=()):
        return [[1, True]]

    def _search_many_identifiers(self, query_documents, **kwargs):
        return ({key: ["sos", "tdc"] for key in query_documents}, 1)

    def _get_card_documents(self, identifiers):
        return {
            "sos": make_candidate(
                "sos",
                "Studious First-Year / Rampant Growth (SOS)",
            ),
            "tdc": make_candidate(
                "tdc",
                "Rampant Growth (TDC)",
                dpi=1200,
            ),
        }


def test_batch_resolution_keeps_shared_names_separate_by_set_code() -> None:
    client = BatchSetCodeClient()
    cards = [
        DeckCard(1, "Studious First-Year / Rampant Growth", set_code="sos"),
        DeckCard(1, "Rampant Growth", set_code="tdc"),
    ]
    try:
        results = client.resolve_many_auto(
            cards,
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="exact_first",
            quality_mode="prefer_highres",
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
        )
    finally:
        client.close()

    assert results[0].faces
    assert results[1].faces
    assert results[0].faces[0].url.endswith("sos.jpg")
    assert results[1].faces[0].url.endswith("tdc.jpg")
