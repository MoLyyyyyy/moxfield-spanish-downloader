import httpx
import pytest

from mtg_downloader.models import DeckCard
from mtg_downloader.scryfall import ScryfallClient, _candidate_matches_full_name


def test_full_reskin_name_matches_but_partial_names_do_not():
    candidate = {"name": "Cavern of Souls", "flavor_name": "Paths of the Dead"}
    assert _candidate_matches_full_name(candidate, "Paths of the Dead")
    assert _candidate_matches_full_name(candidate, "Cavern of Souls")
    assert not _candidate_matches_full_name(candidate, "Paths")
    assert not _candidate_matches_full_name(
        {"name": "Front // Back", "card_faces": [{"flavor_name": "Paths"}]},
        "Paths",
    )


@pytest.mark.parametrize("preferred_language", [None, "es"])
@pytest.mark.parametrize("highres", [True, False])
def test_reskin_resolution_uses_english_highres_only(tmp_path, preferred_language, highres):
    def respond(request):
        spanish = request.url.path.endswith("/es") or "lang:es" in request.url.params.get("q", "")
        if spanish:
            return httpx.Response(404)
        exact = request.url.path != "/cards/search"
        candidate = {
            "id": "reskin-exact" if exact else "reskin-alternative",
            "name": "Cavern of Souls",
            "flavor_name": "Paths of the Dead",
            "lang": "en",
            "set": "ltc",
            "collector_number": "362" if exact else "392",
            "highres_image": False if exact else highres,
            "image_status": "highres_scan" if not exact and highres else "lowres",
            "image_uris": {"large": "https://example.com/card.jpg"},
        }
        return httpx.Response(200, json=candidate if exact else {"data": [candidate]})

    with ScryfallClient(tmp_path) as client:
        client.client.close()
        client.client = httpx.Client(transport=httpx.MockTransport(respond))
        result = client.resolve(
            DeckCard(1, "Paths of the Dead", set_code="ltc", collector_number="362"),
            preferred_language=preferred_language,
            allow_language_fallback=True,
            quality_mode="highres_only",
        )

    if highres:
        assert result.faces
        assert result.language == "en"
        assert result.collector_number == "392"
        assert result.highres_image
    else:
        assert not result.faces
