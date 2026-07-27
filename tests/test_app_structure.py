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
    assert "Revisar impresiones" in app
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
    assert "Cargando impresiones alternativas..." in app
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
