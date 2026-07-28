from pathlib import Path

from mtg_downloader.models import DeckCard
from mtg_downloader.mpcfill import (
    DEFAULT_PREFERRED_SOURCES,
    MpcFillClient,
    _normalise_query,
)


def candidate(identifier: str, source: str, language: str = "EN"):
    return {
        "identifier": identifier,
        "name": identifier,
        "language": language,
        "dpi": 800,
        "priority": 1,
        "sourceName": source,
        "sourceType": "Google Drive",
        "downloadLink": f"https://example.com/{identifier}.jpg",
    }


class BatchClient(MpcFillClient):
    def __init__(self):
        super().__init__(Path("/tmp/proxy_maker_batch_test"))
        self.search_batches = []

    def _source_rows(self, preferred_sources=()):
        return [[1, True], [2, True]]

    def _search_many_identifiers(self, query_documents, **kwargs):
        self.search_batches.append(dict(query_documents))
        return (
            {
                key: [f"other-{key}", f"psilos-{key}"]
                for key in query_documents
            },
            1,
        )

    def _get_card_documents(self, identifiers):
        documents = {}
        for identifier in identifiers:
            source = (
                "PsilosX Proxy Drive"
                if identifier.startswith("psilos-")
                else "Other Artist"
            )
            documents[identifier] = candidate(identifier, source)
        return documents


def test_complete_deck_uses_one_batched_search() -> None:
    client = BatchClient()
    cards = [DeckCard(1, f"Card {index}") for index in range(99)]
    try:
        results = client.resolve_many_auto(
            cards,
            preferred_language="en",
            allow_language_fallback=False,
            resolution_mode="flexible",
            quality_mode="prefer_highres",
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
        )
    finally:
        client.close()

    assert len(client.search_batches) == 1
    assert len(client.search_batches[0]) == 99
    assert len(results) == 99
    assert all(result.faces for result in results)
    assert all("psilos-" in result.faces[0].url for result in results)
    assert client.last_batch_stats["resolved"] == 99
    assert client.last_batch_stats["search_requests"] == 1


def test_query_normalisation_matches_mpcfill_frontend() -> None:
    assert _normalise_query("Frodo, Sauron's Bane") == "frodo saurons bane"
    assert _normalise_query("Fire // Ice") == "fire ice"
