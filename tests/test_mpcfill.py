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
    )
    assert resolved.provider == "mpcfill"
    assert resolved.status == "Diseño MPCFill"
    assert resolved.faces[0].provider == "mpcfill"
    assert resolved.faces[0].crop_mode == "auto"
    assert resolved.selected_set == "MPCFILL"
