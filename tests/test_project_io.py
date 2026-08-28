from __future__ import annotations

import json

import pytest

from mtg_downloader.models import (
    CardVariant,
    DeckCard,
    ImageFace,
    ResolvedCard,
)
from mtg_downloader.persistence import _resolved_to_dict
from mtg_downloader.project_io import (
    ProjectFileError,
    analysis_signature_for_config,
    export_project,
    import_project,
    project_selection_summary,
    selection_fingerprint,
)


def selected_card() -> ResolvedCard:
    return ResolvedCard(
        source=DeckCard(
            2,
            "Studious First-Year / Rampant Growth",
            set_code="sos",
            collector_number="162",
        ),
        status="Selección manual",
        provider="scryfall",
        type_line="Creature // Sorcery",
        language="en",
        printed_name=(
            "Studious First-Year // Rampant Growth"
        ),
        selected_set="sos",
        collector_number="162",
        faces=[
            ImageFace(
                "Studious First-Year",
                "https://example.com/front.png",
                ".png",
            ),
            ImageFace(
                "Rampant Growth",
                "https://example.com/back.png",
                ".png",
            ),
        ],
        scryfall_data={
            "id": "sos-162",
            "released_at": "2026-07-01",
            "set": "sos",
        },
        downloaded_format="png",
        image_status="highres_scan",
        highres_image=True,
        allocations=[
            CardVariant(
                quantity=1,
                status="Selección manual",
                provider="scryfall",
                language="en",
                selected_set="sos",
                collector_number="162",
                faces=[
                    ImageFace(
                        "Studious First-Year",
                        "https://example.com/front.png",
                        ".png",
                    ),
                    ImageFace(
                        "Rampant Growth",
                        "https://example.com/back.png",
                        ".png",
                    ),
                ],
                metadata={
                    "id": "sos-162",
                    "released_at": "2026-07-01",
                },
            ),
            CardVariant(
                quantity=1,
                status="Selección manual MPCFill",
                provider="mpcfill",
                selected_set="sos",
                collector_number="community-7",
                faces=[
                    ImageFace(
                        "Community art",
                        "https://example.com/community.jpg",
                        ".jpg",
                        provider="mpcfill",
                        crop_mode="auto",
                        crop_shift_x=7,
                        crop_shift_y=-4,
                    ),
                ],
                metadata={
                    "identifier": "community-7",
                    "crop_mode": "auto",
                    "crop_shift_x": 7,
                    "crop_shift_y": -4,
                },
            ),
        ],
    )


def project_payload(
    *,
    project_revision: int = 0,
) -> bytes:
    config = {
        "decks": [
            {
                "decklist": (
                    "2 Studious First-Year / "
                    "Rampant Growth (SOS) 162"
                ),
                "deck_name": "Growth",
                "preferred_language": "en",
            }
        ]
    }
    signature = analysis_signature_for_config(
        config,
        engine_version="workflow-v5",
    )
    return export_project(
        analysis_config=config,
        analysis_signature=signature,
        resolved_cards=[selected_card()],
        deck_summaries=[
            {
                "index": 1,
                "name": "Growth",
                "copies": 2,
                "start_index": 0,
                "end_index": 1,
            }
        ],
        multi_deck_stats={"saved_sheets": 0},
        deck_analysis_stats=[
            {"provider": "scryfall"}
        ],
        reviewed_decks=[0],
        active_review_deck=0,
        review_selected_index=0,
        workspace_mode="Editar cartas",
        review_only_problematic=True,
        pdf_settings={"pdf_cut_lines": False},
        build_version="test",
        project_revision=project_revision,
    )


def test_full_project_round_trip_preserves_exact_selection() -> None:
    original = selected_card()
    payload = project_payload(project_revision=9)

    loaded = import_project(
        payload,
        engine_version="workflow-v5",
    )

    assert (
        loaded.analysis_config["decks"][0]["deck_name"]
        == "Growth"
    )
    assert loaded.project_revision == 9
    assert loaded.resolved_cards[0].status == "Selección manual"
    assert loaded.resolved_cards[0].selected_set == "sos"
    assert loaded.resolved_cards[0].collector_number == "162"
    assert len(loaded.resolved_cards[0].faces) == 2
    assert len(loaded.resolved_cards[0].allocations) == 2
    assert (
        loaded.resolved_cards[0]
        .allocations[1]
        .faces[0]
        .crop_shift_x
        == 7
    )
    assert (
        _resolved_to_dict(loaded.resolved_cards[0])
        == _resolved_to_dict(original)
    )
    assert loaded.pdf_settings == {
        "pdf_cut_lines": False
    }
    assert loaded.reviewed_decks == [0]
    assert loaded.workspace_mode == "Editar cartas"
    assert loaded.review_only_problematic is True


def test_project_contains_and_verifies_selection_fingerprint() -> None:
    payload = project_payload()
    data = json.loads(payload)

    assert data["schema_version"] == 3
    assert data["selection_fingerprint"] == (
        selection_fingerprint([selected_card()])
    )
    assert data["selection_summary"] == (
        project_selection_summary([selected_card()])
    )

    data["resolved_cards"][0]["selection"][
        "collector_number"
    ] = "999"

    with pytest.raises(
        ProjectFileError,
        match="integridad",
    ):
        import_project(
            json.dumps(data),
            engine_version="workflow-v5",
        )


def test_legacy_schema_one_project_still_loads() -> None:
    data = json.loads(project_payload())
    data["schema_version"] = 1
    data.pop("selection_fingerprint")
    data.pop("selection_summary")
    data.pop("saved_at")
    data.pop("project_revision")

    loaded = import_project(
        json.dumps(data),
        engine_version="workflow-v5",
    )

    assert loaded.project_revision == 0
    assert loaded.resolved_cards[0].selected_set == "sos"
    assert len(loaded.resolved_cards[0].allocations) == 2


def test_project_rejects_mismatched_deck_count() -> None:
    data = json.loads(project_payload())
    data["deck_summaries"] = []

    with pytest.raises(ProjectFileError):
        import_project(
            json.dumps(data),
            engine_version="workflow-v5",
        )


from pathlib import Path


def uploaded_card(tmp_path: Path) -> ResolvedCard:
    front = tmp_path / "custom-front.png"
    back = tmp_path / "custom-back.png"
    front.write_bytes(b"front-custom-bytes")
    back.write_bytes(b"back-custom-bytes")
    return ResolvedCard(
        source=DeckCard(1, "Custom DFC", set_code="cst", collector_number="1"),
        status="Imagen subida manualmente",
        provider="upload",
        type_line="Artifact // Artifact",
        language="es",
        printed_name="Carta personalizada",
        selected_set="cst",
        collector_number="1",
        faces=[
            ImageFace("Front", str(front), ".png", provider="upload"),
            ImageFace("Back", str(back), ".png", provider="upload"),
        ],
    )


@pytest.mark.parametrize('portable', [False, True])
def test_project_embeds_uploaded_images_and_restores_them(tmp_path, monkeypatch, portable) -> None:
    if portable:
        monkeypatch.setenv('PROXY_MAKER_DATA_DIR', str(tmp_path / 'Datos'))
    else:
        monkeypatch.delenv('PROXY_MAKER_DATA_DIR', raising=False)
    card = uploaded_card(tmp_path)
    config = {
        "decks": [
            {
                "decklist": "1 Custom DFC (CST) 1",
                "deck_name": "Custom",
                "preferred_language": "es",
            }
        ]
    }
    signature = analysis_signature_for_config(
        config,
        engine_version="workflow-v5",
    )
    payload = export_project(
        analysis_config=config,
        analysis_signature=signature,
        resolved_cards=[card],
        deck_summaries=[
            {
                "index": 1,
                "name": "Custom",
                "copies": 1,
                "start_index": 0,
                "end_index": 1,
            }
        ],
        multi_deck_stats={},
        deck_analysis_stats=[{}],
        reviewed_decks=[0],
        active_review_deck=0,
        review_selected_index=0,
        workspace_mode="Editar cartas",
        review_only_problematic=False,
        pdf_settings={},
        build_version="test",
    )
    data = json.loads(payload)
    assert len(data["embedded_upload_assets"]) == 2

    loaded = import_project(payload, engine_version="workflow-v5")

    assert loaded.embedded_upload_count == 2
    restored = loaded.resolved_cards[0]
    assert restored.provider == "upload"
    assert restored.faces[0].provider == "upload"
    assert Path(restored.faces[0].url).read_bytes() == b"front-custom-bytes"
    assert Path(restored.faces[1].url).read_bytes() == b"back-custom-bytes"
    if portable:
        assert Path(restored.faces[0].url).is_relative_to(tmp_path / 'Datos')
        assert Path(restored.faces[1].url).is_relative_to(tmp_path / 'Datos')
    assert _resolved_to_dict(restored) == _resolved_to_dict(card)
