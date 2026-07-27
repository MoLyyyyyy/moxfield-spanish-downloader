import json
from pathlib import Path

import httpx

from mtg_downloader.models import DeckCard
from mtg_downloader.mpcfill import MpcFillClient


def test_search_and_resolve_mpcfill_design(tmp_path: Path) -> None:
    seen_payloads = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/sources/":
            return httpx.Response(
                200,
                json={
                    "results": {
                        "1": {"pk": 1, "name": "Fuente uno"},
                        "2": {"pk": 2, "name": "Fuente dos"},
                    }
                },
            )

        if request.url.path == "/2/editorSearch/":
            payload = json.loads(request.content)
            seen_payloads["search"] = payload
            return httpx.Response(
                200,
                json={
                    "results": {
                        "sol ring": {
                            "CARD": ["high", "low"],
                        }
                    }
                },
            )

        if request.url.path == "/2/cards/":
            payload = json.loads(request.content)
            seen_payloads["cards"] = payload
            return httpx.Response(
                200,
                json={
                    "results": {
                        "high": {
                            "identifier": "high",
                            "name": "Sol Ring - Alternate",
                            "dpi": 1200,
                            "extension": "jpg",
                            "language": "EN",
                            "priority": 1,
                            "sourceName": "Artist A",
                            "sourceType": "Google Drive",
                            "mediumThumbnailUrl": "https://images.test/high.jpg",
                            "downloadLink": "https://images.test/high-full.jpg",
                        },
                        "low": {
                            "identifier": "low",
                            "name": "Sol Ring - Low",
                            "dpi": 200,
                            "extension": "jpg",
                            "language": "EN",
                            "priority": 2,
                            "sourceName": "Artist B",
                            "sourceType": "Google Drive",
                            "mediumThumbnailUrl": "https://images.test/low.jpg",
                            "downloadLink": "https://images.test/low-full.jpg",
                        },
                    }
                },
            )

        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    mpc = MpcFillClient(tmp_path, client=client)
    designs = mpc.search_designs(
        "Sol Ring",
        languages=("EN",),
        minimum_dpi=300,
        max_results=9,
    )

    assert [design["identifier"] for design in designs] == ["high"]
    assert seen_payloads["search"]["searchSettings"]["sourceSettings"][
        "sources"
    ] == [[1, True], [2, True]]
    assert seen_payloads["cards"]["cardIdentifiers"] == ["high", "low"]

    resolved = mpc.resolve_candidate(
        DeckCard(1, "Sol Ring"),
        designs[0],
        crop_mode="auto",
        type_line="Artifact",
    )
    assert resolved.provider == "mpcfill"
    assert resolved.type_line == "Artifact"
    assert resolved.status == "Diseño MPCFill"
    assert resolved.faces[0].provider == "mpcfill"
    assert resolved.faces[0].crop_mode == "auto"
    assert resolved.selected_set == "MPCFILL"


def test_search_cardbacks_uses_cardback_type(tmp_path: Path) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/sources/":
            return httpx.Response(200, json={"results": {"1": {"pk": 1}}})
        if request.url.path == "/2/editorSearch/":
            payload = json.loads(request.content)
            seen["payload"] = payload
            return httpx.Response(
                200,
                json={"results": {"lotus": {"CARDBACK": ["back"]}}},
            )
        if request.url.path == "/2/cards/":
            return httpx.Response(
                200,
                json={
                    "results": {
                        "back": {
                            "identifier": "back",
                            "name": "Lotus Back",
                            "dpi": 1200,
                            "extension": "png",
                            "sourceType": "Google Drive",
                            "downloadLink": "https://images.test/back.png",
                        }
                    }
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    mpc = MpcFillClient(tmp_path, client=client)
    results = mpc.search_cardbacks("lotus")
    assert results[0]["identifier"] == "back"
    query = seen["payload"]["queries"][0]
    assert query["cardType"] == "CARDBACK"
    assert seen["payload"]["searchSettings"]["searchTypeSettings"][
        "filterCardbacks"
    ]
