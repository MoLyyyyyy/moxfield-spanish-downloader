from pathlib import Path

import httpx
import pytest

from mtg_downloader.scryfall import ScryfallClient, ScryfallError


class SequenceTransport(httpx.BaseTransport):
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def handle_request(self, request):
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        if status == 200:
            return httpx.Response(
                200,
                request=request,
                json={"object": "card", "name": "Forest"},
            )
        return httpx.Response(
            status,
            request=request,
            headers={"Retry-After": "0"},
            json={"object": "error"},
        )


def test_503_is_retried_until_success(tmp_path, monkeypatch) -> None:
    events = []
    client = ScryfallClient(
        tmp_path,
        retry_callback=lambda code, attempt, maximum, delay: events.append(
            (code, attempt, maximum)
        ),
    )
    transport = SequenceTransport([503, 503, 200])
    client.client.close()
    client.client = httpx.Client(
        transport=transport,
        headers={"User-Agent": "test", "Accept": "application/json"},
    )
    monkeypatch.setattr("mtg_downloader.scryfall.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "mtg_downloader.scryfall.random.uniform",
        lambda _a, _b: 0.0,
    )

    try:
        result = client._request_json("/cards/test")
    finally:
        client.close()

    assert result["name"] == "Forest"
    assert transport.calls == 3
    assert [event[0] for event in events] == [503, 503]


def test_exhausted_503_has_clear_error(tmp_path, monkeypatch) -> None:
    client = ScryfallClient(tmp_path)
    transport = SequenceTransport([503])
    client.client.close()
    client.client = httpx.Client(
        transport=transport,
        headers={"User-Agent": "test", "Accept": "application/json"},
    )
    monkeypatch.setattr("mtg_downloader.scryfall.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "mtg_downloader.scryfall.random.uniform",
        lambda _a, _b: 0.0,
    )

    try:
        with pytest.raises(ScryfallError, match="HTTP 503"):
            client._request_json("/cards/test")
    finally:
        client.close()

    assert transport.calls == 5
