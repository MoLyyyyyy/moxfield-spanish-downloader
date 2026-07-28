from mtg_downloader.models import CardVariant, DeckCard, ImageFace, ResolvedCard
from mtg_downloader.project_io import (
    analysis_signature_for_config,
    export_project,
    import_project,
)


def selected_card() -> ResolvedCard:
    return ResolvedCard(
        source=DeckCard(1, "Fire / Ice", set_code="mh2", collector_number="290"),
        status="Selección manual",
        provider="scryfall",
        language="en",
        selected_set="mh2",
        collector_number="290",
        faces=[ImageFace("Fire // Ice", "https://example.com/fire.png", ".png")],
        allocations=[
            CardVariant(
                quantity=1,
                status="Selección manual",
                faces=[ImageFace("Fire // Ice", "https://example.com/fire.png", ".png")],
                metadata={"released_at": "2021-06-18"},
            )
        ],
    )


def test_full_project_round_trip_preserves_selection_and_settings() -> None:
    config = {
        "decks": [
            {
                "decklist": "1 Fire / Ice (MH2) 290",
                "deck_name": "Izzet",
                "preferred_language": "en",
            }
        ]
    }
    signature = analysis_signature_for_config(config, engine_version="workflow-v5")
    payload = export_project(
        analysis_config=config,
        analysis_signature=signature,
        resolved_cards=[selected_card()],
        deck_summaries=[
            {
                "index": 1,
                "name": "Izzet",
                "copies": 1,
                "start_index": 0,
                "end_index": 1,
            }
        ],
        multi_deck_stats={"saved_sheets": 0},
        deck_analysis_stats=[{"provider": "scryfall"}],
        reviewed_decks=[0],
        active_review_deck=0,
        review_selected_index=0,
        workspace_mode="Editar cartas",
        review_only_problematic=True,
        pdf_settings={"pdf_cut_lines": False},
        build_version="test",
    )

    loaded = import_project(payload, engine_version="workflow-v5")

    assert loaded.analysis_config["decks"][0]["deck_name"] == "Izzet"
    assert loaded.analysis_signature == signature
    assert loaded.resolved_cards[0].status == "Selección manual"
    assert loaded.resolved_cards[0].allocations[0].quantity == 1
    assert loaded.pdf_settings == {"pdf_cut_lines": False}
    assert loaded.reviewed_decks == [0]
    assert loaded.workspace_mode == "Editar cartas"
    assert loaded.review_only_problematic is True


def test_project_rejects_mismatched_deck_count() -> None:
    import json
    import pytest
    from mtg_downloader.project_io import ProjectFileError

    config = {"decks": [{"decklist": "1 Fire / Ice"}]}
    payload = export_project(
        analysis_config=config,
        analysis_signature="x",
        resolved_cards=[selected_card()],
        deck_summaries=[],
        multi_deck_stats={},
        deck_analysis_stats=[],
        reviewed_decks=[],
        active_review_deck=0,
        review_selected_index=0,
        workspace_mode="Vista del mazo",
        review_only_problematic=False,
        pdf_settings={},
        build_version="test",
    )
    data = json.loads(payload)
    data["deck_summaries"] = []

    with pytest.raises(ProjectFileError):
        import_project(json.dumps(data), engine_version="workflow-v5")
