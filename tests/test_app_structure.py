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
    assert "Cambiar versión" in app
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
    assert "Original" in app and "Resultado automático" in app
    assert "se recortan automáticamente" in app
    assert "Modo de recorte" not in app


def test_multiple_art_distribution_exists() -> None:
    app = app_text()
    assert "Repartir copias entre ilustraciones" in app
    assert "Añadir al reparto" in app
    assert "Guardar reparto" in app
    assert "set_allocation_quantities" in app


def test_bulk_editing_remains_without_manual_persistence_panel() -> None:
    app = app_text()
    assert "Guardar o restaurar elecciones" not in app
    assert "Descargar elecciones JSON" not in app
    assert "Aplicar elecciones guardadas" not in app
    assert "Edición masiva" in app
    assert "Aplicar acción masiva" in app
    assert "Primer diseño MPCFill de mayor DPI" in app
    assert "Aplicar recorte a diseños MPCFill" not in app


def test_gallery_filters_and_statuses_exist() -> None:
    app = app_text()
    assert "filtered_indices(" in app
    assert "Múltiples artes" in app
    assert "Baja resolución" in app
    assert "Preparar todas las imágenes ahora" not in app
    assert "Al terminar aparecerá el botón de descarga" in app
    assert "cache_stats(" in app


def test_validation_and_simplified_export_actions_exist() -> None:
    app = app_text()
    assert "Validar y exportar" in app
    assert "Generar PDF" in app
    assert "Descargar PDF" in app
    assert "Otros formatos" in app
    assert "Generar ZIP de imágenes" in app
    assert "Generar paquete MPC / dúplex" in app
    assert "Formato de salida" not in app
    assert "back_spec = standard_magic_back()" in app
    assert "validate_deck(" in app


def test_output_can_be_generated_despite_errors_only_by_override() -> None:
    app = app_text()
    assert "Generar aunque falten imágenes" in app
    assert "generation_disabled = bool(validation.errors) and not override_errors" in app
    assert "disabled=generation_disabled" in app



def test_pdf_matches_mpcfilltopdf_profile() -> None:
    app = app_text()
    assert "PDF A4 3×3" in app
    assert "63,5 × 88,9 mm" in app
    assert "sangrado espejo de 1 mm" in app
    assert "Marcas cortas en los márgenes" in app
    assert "Líneas completas para corte manual" in app
    assert "barra CMYK" in app
    assert "páginas 1/1B" in app
    assert "cut_line_over_cards=cut_line_over_cards" in app



def test_exact_mpcfilltopdf_assets_are_mandatory() -> None:
    app = app_text()
    assert "PDF A4 3×3" in app
    assert "Las marcas de registro y la barra CMYK originales de " in app
    assert "MPCFillToPDF se incluyen siempre" in app
    assert "printer_marks = True" in app



def test_pdf_uses_generate_then_download_flow() -> None:
    app = app_text()
    assert 'pdf_requested = st.button(' in app
    assert '"Generar PDF"' in app
    assert '"Descargar PDF"' in app
    assert "update_pdf_progress" in app
    assert "progress_callback=update_pdf_progress" in app
    assert 'st.session_state["pdf_output_download"] = {' in app
    assert "st.rerun()" in app



def test_problematic_cards_are_grouped_first_in_gallery() -> None:
    app = app_text()
    assert "def render_gallery_grouped_section(" in app
    assert "⚠️ Cartas con problemas" in app
    assert "Ver {len(healthy_indices)} cartas correctas" in app
    assert "problematic_indices = [" in app
    assert "healthy_indices = [" in app
    assert "Estas cartas necesitan revisión" in app
    assert "Ver {len(healthy_indices)} cartas correctas" in app



def test_language_controls_are_explicit() -> None:
    app = app_text()
    assert '"Idioma principal"' in app
    assert '"Edición"' in app
    assert '"Calidad"' in app
    assert "allow_language_fallback" in app
    assert "preferred_language=preferred_language" in app
    assert "Perfil de selección" not in app
    assert "Personalizar reglas" not in app


def test_app_uses_a_three_step_wizard() -> None:
    app = app_text()
    assert "1. Lista y opciones" in app
    assert "2. Revisar versiones" in app
    assert "3. Validar y exportar" in app
    assert 'st.form("analysis_form")' not in app
    assert 'analysis_submitted = st.button(' in app
    assert 'st.session_state["app_step"] = 2' in app
    assert "Continuar a exportación →" in app
    assert "← Volver a revisar" in app
    assert "render_workspace()" in app
    assert "render_export_panel()" in app


def test_analysis_reuses_unchanged_results() -> None:
    app = app_text()
    assert "Se ha reutilizado el análisis anterior" in app
    assert "requested_signature = current_signature()" in app
    assert 'st.session_state.get("analysis_signature")' in app



def test_analysis_handles_temporary_scryfall_errors() -> None:
    app = app_text()
    assert "show_scryfall_retry" in app
    assert "Scryfall está temporalmente saturado" in app
    assert "Error temporal de Scryfall" in app
    assert "temporary_failures" in app
    assert "retry_callback=show_scryfall_retry" in app



def test_magic_back_is_always_used_without_selector() -> None:
    app = app_text()
    assert "back_spec = standard_magic_back()" in app
    assert "include_backs = True" in app
    assert "Reverso estándar de Magic aplicado siempre" not in app
    assert "def render_back_selector" not in app
    assert "Configurar reversos" not in app
    assert "Reverso para cartas de una sola cara" not in app



def test_pdf_is_the_primary_export_action() -> None:
    app = app_text()
    assert '"Generar PDF"' in app
    assert '"Descargar PDF"' in app
    assert 'type="primary"' in app
    assert 'with st.expander("Otros formatos"' in app
    assert 'export_format = st.selectbox(' not in app


def test_decklist_placeholder_uses_real_line_breaks() -> None:
    app = app_text()
    assert '"Commander:\\n"' in app
    assert '"Commander:\\\\n"' not in app
    assert '"Deck:\\n"' in app



def test_application_is_named_proxy_maker() -> None:
    app = app_text()
    assert 'page_title="Proxy Maker"' in app
    assert 'st.title("🃏 Proxy Maker")' in app
    assert "Moxfield Cartas ES" not in app
    readme = Path("README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Proxy Maker")



def test_search_options_are_always_visible() -> None:
    app = app_text()
    assert "Personalizar reglas" not in app
    assert '"Idioma principal"' in app
    assert '"Edición"' in app
    assert '"Calidad"' in app



def test_step_two_can_return_without_losing_analysis() -> None:
    app = app_text()
    assert '"← Lista y opciones"' in app
    assert 'key="step2_back_top"' in app
    assert 'key="step2_back_bottom"' in app
    assert "Volver al paso 1 no elimina el análisis" in app
    assert "Volver a revisar el análisis guardado" in app
    assert "Descartar cambios y volver al análisis guardado" in app
    assert 'st.session_state["app_step"] = 1' in app
    assert 'st.session_state["app_step"] = 2' in app



def test_alternative_filters_are_inherited_and_collapsed() -> None:
    app = app_text()
    assert 'with st.expander("Filtros", expanded=False)' in app
    assert 'inherited_language_label' in app
    assert 'inherited_quality_label' in app
    assert '"Mostrar 12 más"' in app
    assert 'key=f"alt_limit_{selected_index}"' not in app
    assert 'key=f"mpc_limit_{selected_index}"' not in app


def test_step_one_only_shows_core_search_options() -> None:
    app = app_text()
    advanced = app.index('with st.expander("Opciones avanzadas"')
    assert app.index('fallback_label =', advanced) > advanced
    assert app.index('"Formato de imagen"', advanced) > advanced
    assert app.index('"Incluir sideboard"', advanced) > advanced
    assert app.index('"Incluir maybeboard"', advanced) > advanced


def test_healthy_cards_are_collapsed() -> None:
    app = app_text()
    assert 'f"Ver {len(healthy_indices)} cartas correctas"' in app
    assert 'expanded=False' in app
    assert 'st.success("No hay cartas con problemas.")' in app



def test_primary_source_selector_exists() -> None:
    app = app_text()
    assert '"Fuente principal"' in app
    assert '"Scryfall"' in app
    assert '"MPCFill"' in app
    assert "MrTeferi, PsilosX, Chilli_Axe, CompC y Hathwellcrisping" in app
    assert '"preferred_image_source"' in app
    assert "client.resolve_many_auto(" in app



def test_mpcfill_analysis_respects_resolution_mode() -> None:
    app = app_text()
    assert "resolution_mode=resolution_mode" in app
    assert "fuzzy_search=True" in app



def test_mpcfill_analysis_is_batched() -> None:
    app = app_text()
    assert "client.resolve_many_auto(" in app
    assert "Consultando MPCFill en lote" in app
    assert "mpcfill_analysis_stats" in app
    analysis_section = app[
        app.index('if preferred_image_source == "mpcfill":'):
        app.index("resolved_cards = enforce_automatic_mpcfill_crop_list")
    ]
    assert "client.resolve_auto(" not in analysis_section



def test_analysis_engine_version_invalidates_stale_results() -> None:
    app = app_text()
    assert 'ANALYSIS_ENGINE_VERSION = "multi-deck-v1"' in app
    assert '"engine_version": ANALYSIS_ENGINE_VERSION' in app



def test_manual_mpcfill_results_prioritize_same_set_code() -> None:
    app = app_text()
    assert "mpc_candidate_mentions_set_code" in app
    assert "Se muestran primero los diseños cuyo nombre o " in app
    assert "archivo parece incluir el set code " in app



def test_pdf_uses_deck_names_for_filename() -> None:
    app = app_text()
    assert "from mtg_downloader.filenames import multi_deck_pdf_filename" in app
    assert "pdf_file_name = multi_deck_pdf_filename(" in app
    assert '[summary["name"] for summary in deck_summaries]' in app
    assert "mazo_impresion_mpcfilltopdf.pdf" not in app



def test_pdf_generation_replaces_button_with_download() -> None:
    app = app_text()
    assert 'if not st.session_state.get("pdf_output_download"):' in app
    assert 'pdf_requested = st.button(' in app
    assert '"Generar PDF"' in app
    assert 'st.download_button(' in app
    assert '"Descargar PDF"' in app
    assert 'data=pdf_download["data"]' in app
    assert 'file_name=pdf_download["file_name"]' in app
    assert 'mime=pdf_download["mime"]' in app
    assert 'on_click="ignore"' in app
    assert 'requested_format = "pdf"' not in app
    assert '"Descargar ZIP preparado"' in app



def test_app_has_no_deprecated_container_width() -> None:
    app = app_text()
    assert "use_container_width" not in app
    assert 'width="stretch"' in app



def test_pdf_can_split_over_200_mb() -> None:
    app = app_text()
    assert '"Dividir automáticamente si supera 200 MB"' in app
    assert "PDF_SPLIT_LIMIT_BYTES" in app
    assert "split_pdf_if_needed(" in app
    assert "preserve_page_pairs=include_backs" in app
    assert "build_pdf_parts_zip(pdf_parts)" in app
    assert '"Descargar todas las partes"' in app
    assert '"pdf_output_download"' in app
    assert '"Descargar parte {index} de {len(pdf_parts)}"' not in app



def test_export_warns_about_paid_empty_slots() -> None:
    app = app_text()
    assert "calculate_sheet_usage(validation.expected_cards)" in app
    assert "posiciones pagadas" in app
    assert "Puedes añadir" in app
    assert "para completar la última hoja" in app
    assert "sin huecos pagados" in app
    assert "únicamente al final de la última hoja" in app



def test_multiple_deck_inputs_are_supported() -> None:
    app = app_text()
    assert '"Número de mazos"' in app
    assert "max_value=12" in app
    assert "decklist_texts: list[str]" in app
    assert 'key=f"decklist_input_{deck_index}"' in app
    assert '"Analizar mazos"' in app
    assert "parse_multiple_decklists(" in app
    assert '"deck_summaries"' in app
    assert '"multi_deck_stats"' in app


def test_multiple_decks_fill_pages_continuously() -> None:
    app = app_text()
    assert "sin saltos de hoja entre ellos" in app
    assert "rellena los huecos libres" in app
    assert "saved_paid_slots" in app
    assert "posiciones pagadas" in app
    assert "warn_duplicates=deck_count == 1" in app
    assert "multi_deck_pdf_filename(" in app



def test_build_version_identifies_multideck_download() -> None:
    app = app_text()
    assert 'BUILD_VERSION = "2026.07.28-multideck-v1"' in app
    assert '"Número de mazos"' in app
