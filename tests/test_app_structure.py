from pathlib import Path


def test_app_has_no_file_uploader() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "st.file_uploader" not in app
    assert "uploaded_list" not in app
    assert "uploaded_text" not in app
    assert "Subir exportación del mazo" not in app


def test_app_has_visual_review_flow() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "Analizar mazo" in app
    assert "Editar versiones" in app
    assert "Elegir y continuar" in app
    assert "Generar ZIP con la selección actual" in app


def test_previews_are_compact() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "width=210" in app
    assert "width=135" in app
    assert "st.columns(3)" in app


def test_app_advances_to_next_card_after_manual_choice() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "def next_review_index(" in app
    assert "def set_review_index(" in app
    assert "set_review_index(target_index)" in app
    assert "next_review_index(" in app
    assert "Elegir y continuar" in app


def test_review_uses_fragment_navigation() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "@st.fragment" in app
    assert 'st.rerun(scope="fragment")' in app
    assert "Mantener actual y continuar" in app
    assert "Elegir y continuar" in app
    assert "← Anterior" in app
    assert "Siguiente →" in app
    assert "def previous_review_index(" in app
    assert "def set_review_index(" in app
    assert "st.rerun()" not in app



def test_alternatives_are_loaded_automatically() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "Cargando impresiones oficiales..." in app
    assert 'alternatives_state_key not in alternatives_cache' in app



def test_review_layout_places_alternatives_next_to_selected_card() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "top_left, top_right = st.columns([1, 2])" in app
    assert "#### Versión seleccionada" in app
    assert "#### Otras versiones" in app
    assert "##### Detalles" in app
    assert "Selector rápido de alternativas" not in app
    assert "Usar alternativa seleccionada y continuar" not in app



def test_details_are_below_selected_image() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    image_pos = app.index('st.image(url, caption=caption, width=210)')
    details_pos = app.index('st.markdown("##### Detalles")')
    alternatives_pos = app.index('with top_right:')
    assert image_pos < details_pos < alternatives_pos
    assert "#### Detalles de la versión seleccionada" not in app
    assert "st.caption(" in app[details_pos:alternatives_pos]



def test_mpcfill_selector_and_crop_controls() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "Comunidad · MPCFill" in app
    assert "Oficiales · Scryfall" in app
    assert "MpcFillClient" in app
    assert "Automático · recomendado" in app
    assert "Mantener sangrado" in app
    assert "Forzar recorte MPC" in app
    assert "DPI mínimo" in app
    assert "Fuente de versiones" in app


def test_selected_mpcfill_preview_is_cropped() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert 'selected.provider == "mpcfill"' in app
    assert "mpc_client.preview_bytes(" in app
    assert "Diseño MPCFill seleccionado" in app



def test_moxfield_style_deck_gallery() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "def render_deck_gallery()" in app
    assert "Vista del mazo" in app
    assert "Editar cartas" in app
    assert "group_deck(" in app
    assert "gallery_printing_label(" in app
    assert '"✏️ Editar"' in app
    assert "st.columns(6)" in app


def test_gallery_edit_opens_selected_card() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "def open_card_editor(index: int)" in app
    assert 'st.session_state["review_only_problematic"] = False' in app
    assert 'set_workspace_mode("Editar cartas")' in app
    assert "← Volver al mazo" in app


def test_workspace_owns_the_fragment() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "@st.fragment\ndef render_deck_workspace()" in app
    assert "@st.fragment\ndef render_review_panel()" not in app
