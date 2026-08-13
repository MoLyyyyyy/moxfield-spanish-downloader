import json
from pathlib import Path

import httpx

from mtg_downloader.models import DeckCard
from mtg_downloader.mpcfill import (
    DEFAULT_PREFERRED_SOURCES,
    MpcFillClient,
)


def test_batch_analysis_uses_current_mpcfill_http_shape(
    tmp_path: Path,
) -> None:
    seen = {"search": 0, "cards": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/sources/":
            return httpx.Response(
                200,
                json={
                    "results": {
                        "1": {
                            "pk": 1,
                            "key": "other",
                            "name": "Other Artist",
                        },
                        "2": {
                            "pk": 2,
                            "key": "psilos",
                            "name": "PsilosX Proxy Drive",
                        },
                    }
                },
            )

        if request.url.path == "/3/editorSearch/":
            payload = json.loads(request.content)
            seen["search"] += 1
            assert len(payload["queries"]) == 99
            assert payload["searchSettings"]["sourceSettings"][
                "sources"
            ][:2] == [[2, True], [1, True]]
            return httpx.Response(
                200,
                json={
                    "results": {
                        key: [f"psilos-{key}"]
                        for key in payload["queries"]
                    }
                },
            )

        if request.url.path == "/2/cards/":
            payload = json.loads(request.content)
            seen["cards"] += 1
            return httpx.Response(
                200,
                json={
                    "results": {
                        identifier: {
                            "identifier": identifier,
                            "cardType": "CARD",
                            "name": identifier,
                            "priority": 1,
                            "source": "psilos",
                            "sourceName": "PsilosX Proxy Drive",
                            "sourceVerbose": "PsilosX",
                            "sourceType": "Google Drive",
                            "dpi": 800,
                            "extension": "jpg",
                            "language": "EN",
                            "mediumThumbnailUrl": "",
                            "smallThumbnailUrl": "",
                        }
                        for identifier in payload["cardIdentifiers"]
                    }
                },
            )

        raise AssertionError(request.url)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = MpcFillClient(tmp_path, client=http_client)
    cards = [DeckCard(1, f"Card {index}") for index in range(99)]
    results = client.resolve_many_auto(
        cards,
        preferred_language="en",
        allow_language_fallback=False,
        resolution_mode="flexible",
        quality_mode="prefer_highres",
        preferred_sources=DEFAULT_PREFERRED_SOURCES,
    )

    assert seen == {"search": 1, "cards": 1}
    assert len(results) == 99
    assert all(result.faces for result in results)
    assert all("autor preferido" in result.status for result in results)
    assert client.last_batch_stats["queries_with_hits"] == 99
    assert client.last_batch_stats["resolved"] == 99


def test_legacy_search_does_not_collapse_same_name_different_collectors(
    tmp_path: Path,
) -> None:
    seen_collectors: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/sources/":
            return httpx.Response(
                200,
                json={
                    "results": {
                        "1": {
                            "pk": 1,
                            "key": "psilos",
                            "name": "PsilosX Proxy Drive",
                        }
                    }
                },
            )

        if request.url.path == "/3/editorSearch/":
            return httpx.Response(
                404,
                request=request,
                json={"detail": "legacy only"},
            )

        if request.url.path == "/2/editorSearch/":
            payload = json.loads(request.content)
            queries = payload["queries"]
            assert len(queries) == 1
            collector = str(queries[0].get("collectorNumber") or "")
            seen_collectors.append(collector)
            return httpx.Response(
                200,
                json={
                    "results": {
                        "nazgûl": {
                            "CARD": [f"nazgul-{collector}"]
                        }
                    }
                },
            )

        raise AssertionError(request.url)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = MpcFillClient(tmp_path, client=http_client)
    query_documents = {
        f"nazgul-{number}": {
            "query": "nazgûl",
            "cardType": "CARD",
            "expansionCode": "LTR",
            "collectorNumber": number,
        }
        for number in (
            "336", "335", "100", "332", "334",
            "333", "337", "338", "339",
        )
    }

    try:
        results, request_count = client._search_many_identifiers(
            query_documents,
            languages=("EN",),
            minimum_dpi=300,
            preferred_sources=DEFAULT_PREFERRED_SOURCES,
            fuzzy_search=False,
        )
    finally:
        client.close()

    collectors = [
        "336", "335", "100", "332", "334",
        "333", "337", "338", "339",
    ]
    assert sorted(seen_collectors) == sorted(collectors)
    assert request_count == 9  # nine independent legacy requests
    assert {
        key: values[0]
        for key, values in results.items()
    } == {
        f"nazgul-{number}": f"nazgul-{number}"
        for number in collectors
    }
