from pathlib import Path


def app_text() -> str:
    return Path("app.py").read_text(encoding="utf-8")


def test_app_has_no_deck_file_uploader() -> None:
    app = app_text()
    assert "st.file_uploader" not in app
    assert "Subir exportación del mazo" not in app


def test_app_has_visual_deck_and_editor() -> None:
    app = app_text()
    assert "Analizar mazo" in app
    assert "Vista del mazo" in app
    assert "Editar versiones" in app
    assert "✏️ Editar" in app
    assert "Mantener actual y continuar" in app
    assert "Elegir y continuar" in app


def test_workspace_uses_fragment_navigation() -> None:
    app = app_text()
    assert "@st.fragment\ndef render_workspace()" in app
    assert 'st.rerun(scope="fragment")' in app
    assert "← Volver al mazo" in app
    assert "← Anterior" in app
    assert "Siguiente →" in app


def test_alternatives_are_automatic_and_side_by_side() -> None:
    app = app_text()
    assert "selected_col, alternatives_col = st.columns([1, 2])" in app
    assert "Cargando impresiones oficiales..." in app
    assert "Buscando diseños MPCFill..." in app
    assert "Buscar impresiones alternativas" not in app


def test_previews_are_compact_and_centered() -> None:
    app = app_text()
    assert "st.image(urls[0], width=135)" in app
    assert "st.image(preview, width=135)" in app
    assert "st.columns([1, 2, 1])" in app
    assert "st.columns([1, 3, 1])" in app


def test_mpcfill_crop_comparator_exists() -> None:
    app = app_text()
    assert "Comparar y ajustar recorte MPCFill" in app
    assert "Desplazamiento horizontal del recorte" in app
    assert "Desplazamiento vertical del recorte" in app
    assert "Guardar ajuste de recorte" in app
    assert "Original" in app and "Resultado" in app


def test_multiple_art_distribution_exists() -> None:
    app = app_text()
    assert "Repartir copias entre ilustraciones" in app
    assert "Añadir al reparto" in app
    assert "Guardar reparto" in app
    assert "set_allocation_quantities" in app


def test_persistence_and_bulk_editing_exist() -> None:
    app = app_text()
    assert "Guardar o restaurar elecciones" in app
    assert "Descargar elecciones JSON" in app
    assert "Aplicar elecciones guardadas" in app
    assert "Edición masiva" in app
    assert "Aplicar acción masiva" in app
    assert "Primer diseño MPCFill de mayor DPI" in app


def test_gallery_filters_and_statuses_exist() -> None:
    app = app_text()
    assert "filtered_indices(" in app
    assert "Múltiples artes" in app
    assert "Baja resolución" in app
    assert "Preparar todas las imágenes ahora" in app
    assert "cache_stats(" in app


def test_validation_backs_and_export_profiles_exist() -> None:
    app = app_text()
    assert "Validar y exportar" in app
    assert "ZIP de imágenes individuales" in app
    assert "Paquete MPC / dúplex" in app
    assert "PDF A4 — 9 cartas por página" in app
    assert "Reverso estándar de Magic" in app
    assert "Reverso neutro" in app
    assert "URL personalizada" in app
    assert "Diseño MPCFill" in app
    assert "validate_deck(" in app


def test_output_can_be_generated_despite_errors_only_by_override() -> None:
    app = app_text()
    assert "Generar aunque falten imágenes" in app
    assert "disabled=bool(validation.errors) and not override_errors" in app



def test_pdf_matches_mpcfilltopdf_profile() -> None:
    app = app_text()
    assert "Perfil compatible con MPCFillToPDF" in app
    assert "63,5 × 88,9 mm" in app
    assert "sangrado espejo de 1 mm" in app
    assert "Marcas cortas en los márgenes" in app
    assert "Líneas completas para corte manual" in app
    assert "barra CMYK" in app
    assert "numeración 1/1B" in app
    assert "cut_line_over_cards=cut_line_over_cards" in app
