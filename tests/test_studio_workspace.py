from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

from mtg_downloader.deck_workflow import normalise_deck_config
from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.project_io import analysis_signature_for_config


def prepared_app(tmp_path):
    image = tmp_path / "card.png"
    Image.new("RGB", (750, 1050), "#61714a").save(image)
    config = {"decks": [
        normalise_deck_config({"deck_name": "Bosque", "decklist": "1 Forest\n1 Missing"}),
        normalise_deck_config({"deck_name": "Fuego", "decklist": "1 Mountain"}),
    ]}
    cards = [
        ResolvedCard(
            source=DeckCard(1, name), status="Selección manual", provider="upload",
            type_line="Basic Land", language="en", highres_image=True,
            faces=[] if name == "Missing" else [ImageFace(name, str(image), ".png", provider="upload")],
        ) for name in ("Forest", "Missing", "Mountain")
    ]
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
    for key, value in {
        "analysis_config": config,
        "analysis_signature": analysis_signature_for_config(config, engine_version="workflow-v5.6-deck-codes-simple-review"),
        "resolved_cards": cards,
        "deck_summaries": [
            {"index": 1, "name": "Bosque", "copies": 2, "start_index": 0, "end_index": 2},
            {"index": 2, "name": "Fuego", "copies": 1, "start_index": 2, "end_index": 3},
        ],
        "app_step": 2, "active_review_deck": 0, "review_selected_index": 1,
    }.items():
        app.session_state[key] = value
    return app.run()


def test_gallery_stays_visible_when_healthy_card_is_selected(tmp_path):
    app = prepared_app(tmp_path)
    assert not app.exception
    app.button(key="gallery_edit_0").click().run()
    assert not app.exception
    assert app.button(key="gallery_edit_1")
    assert app.session_state["review_selected_index"] == 0
    assert any("Forest" in h.value for h in app.subheader)


def test_switching_decks_preserves_edits_and_selected_card(tmp_path):
    app = prepared_app(tmp_path)
    assert not app.exception
    original = app.session_state["resolved_cards"][0]
    app.button(key="gallery_edit_0").click().run()
    app.button(key="studio_deck_1").click().run()
    assert not app.exception
    assert app.session_state["active_review_deck"] == 1
    app.button(key="studio_deck_0").click().run()
    assert app.session_state["review_selected_index"] == 0
    assert app.session_state["resolved_cards"][0] == original


def test_import_roundtrip_preserves_analysis_but_draft_edit_blocks_navigation(tmp_path):
    app = prepared_app(tmp_path)
    cards = app.session_state["resolved_cards"]
    app.button(key="studio_step_1").click().run()
    assert not app.exception
    assert not app.button(key="studio_step_2").disabled
    app.button(key="studio_step_2").click().run()
    assert app.session_state["resolved_cards"] == cards
    app.button(key="studio_step_1").click().run()
    app.text_area(key="decklist_input_0").set_value("2 Forest").run()
    assert not app.exception
    assert app.button(key="studio_step_2").disabled
    assert app.button(key="studio_step_3").disabled


def test_real_pdf_generation_shows_front_back_preview_and_free_slots(tmp_path, monkeypatch):
    from dataclasses import replace
    from mtg_downloader.scryfall import ScryfallClient
    app = prepared_app(tmp_path)
    cards = app.session_state["resolved_cards"]
    cards[1] = replace(cards[1], faces=cards[0].faces)
    app.session_state["resolved_cards"] = cards
    # Only the remote image boundary is replaced; real PDF assembly/rendering runs.
    monkeypatch.setattr(ScryfallClient, "download_raw_image", lambda self, face: (tmp_path / "card.png").read_bytes())
    app.button(key="studio_step_3").click().run()
    assert not app.exception
    assert any("huecos" in item.value for item in app.warning)
    generate = next(button for button in app.button if button.label == "Generar PDF")
    assert not generate.disabled
    generate.click().run()
    assert not app.exception
    assert app.session_state["pdf_output_download"]["data"].startswith(b"%PDF")
    assert app.session_state["studio_pdf_preview"]["page"] == 0
    selector = next(box for box in app.selectbox if box.label == "Página")
    assert selector.options == ["Hoja 1 · anverso", "Hoja 1 · reverso"]
    selector.select(1).run()
    assert not app.exception
    assert app.session_state["studio_pdf_preview"]["page"] == 1


def test_selecting_english_alternative_resolves_last_pending_and_clears_pdf(tmp_path, monkeypatch):
    from mtg_downloader.scryfall import ScryfallClient
    from mtg_downloader.review import is_problematic
    app = prepared_app(tmp_path)
    candidate = {"id": "qa-english", "name": "Missing", "lang": "en", "set": "tst", "collector_number": "1", "type_line": "Creature", "highres_image": True, "image_status": "highres_scan", "image_uris": {"png": str(tmp_path / "card.png")}}
    monkeypatch.setattr(ScryfallClient, "search_alternatives", lambda *args, **kwargs: [candidate])
    app.session_state["pdf_output_download"] = {"data": b"old"}
    app.session_state["pdf_output_signature"] = "old"
    app.session_state["studio_pdf_preview"] = {"png": b"old"}
    app.radio(key="version_source_1").set_value("Oficiales · Scryfall").run()
    assert not app.exception
    next(button for button in app.button if button.label == "Elegir y continuar").click().run()
    assert not app.exception
    assert app.session_state["review_selected_index"] == 1
    assert not is_problematic(app.session_state["resolved_cards"][1])
    assert app.session_state["resolved_cards"][1].language == "en"
    assert app.button(key="gallery_edit_1")
    assert "pdf_output_download" not in app.session_state
    assert "studio_pdf_preview" not in app.session_state
