from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from mtg_downloader.archive import build_zip, cache_stats, prefetch_cards
from mtg_downloader.backs import (
    BackSpec,
    custom_url_back,
    mpcfill_back,
    neutral_back,
    no_back,
    standard_magic_back,
)
from mtg_downloader.deck_view import (
    filtered_indices,
    gallery_printing_label,
    gallery_status_label,
    group_deck,
)
from mtg_downloader.decklist import parse_exported_decklist
from mtg_downloader.image_processing import CROP_AUTO, CROP_FORCE, CROP_NONE
from mtg_downloader.models import CardVariant, DeckCard, ImageFace, ResolvedCard
from mtg_downloader.mpcfill import (
    MpcFillClient,
    MpcFillError,
    mpc_candidate_key,
    mpc_candidate_label,
)
from mtg_downloader.pdf_export import build_a4_pdf
from mtg_downloader.persistence import (
    SelectionConfigError,
    export_selection_config,
    import_selection_config,
)
from mtg_downloader.profiles import PROFILES, get_profile
from mtg_downloader.review import (
    candidate_key,
    candidate_label,
    is_problematic,
    preview_urls,
    problem_reasons,
    review_row,
)
from mtg_downloader.scryfall import ScryfallClient, ScryfallError
from mtg_downloader.selections import (
    AllocationError,
    add_variant,
    card_has_multiple_arts,
    clone_selection_for_card,
    effective_variants,
    remove_variant,
    replace_all_copies,
    set_allocation_quantities,
)
from mtg_downloader.validation import validate_deck

st.set_page_config(
    page_title="Moxfield Cartas ES",
    page_icon="🃏",
    layout="wide",
)

st.title("🃏 Moxfield Cartas ES")
st.write(
    "Pega la exportación de tu mazo, revisa visualmente las versiones y "
    "genera un paquete listo para imprimir."
)

with st.expander("Cómo obtener la lista", expanded=False):
    st.markdown(
        """
1. Abre el mazo en Moxfield.
2. Exporta o copia la lista como texto.
3. Pega el contenido en esta aplicación.
4. Pulsa **Analizar mazo**.
5. Revisa el mazo visualmente o edita cartas concretas.
6. Valida y genera el ZIP, paquete MPC o PDF A4.

```text
Commander:
1 Beorn the Fierce (HOB) 119 *F*

Deck:
1 Arcane Signet (TMC) 57
27 Forest (M20) 279
```

Una entrada con 27 copias aparece una sola vez en la galería, pero genera 27
cartas físicas. También puede repartirse entre varias ilustraciones.
"""
    )

left, right = st.columns([3, 2])
with left:
    decklist_text = st.text_area(
        "Lista del mazo",
        height=340,
        placeholder=(
            "Commander:\n"
            "1 Beorn the Fierce (HOB) 119 *F*\n\n"
            "Deck:\n"
            "1 Arcane Signet (TMC) 57\n"
            "27 Forest (M20) 279"
        ),
        help="Se respetan cantidad, edición y número de coleccionista.",
    )

with right:
    st.subheader("Opciones de análisis")
    profile_key = st.selectbox(
        "Perfil de selección",
        options=[profile.key for profile in PROFILES],
        format_func=lambda key: get_profile(key).label,
        index=0,
    )
    selected_profile = get_profile(profile_key)
    st.info(selected_profile.description)

    resolution_mode = selected_profile.resolution_mode
    quality_mode = selected_profile.quality_mode
    allow_english = selected_profile.allow_english
    image_quality = "png"

    with st.expander("Opciones avanzadas", expanded=False):
        image_quality_label = st.selectbox(
            "Formato de imagen",
            [
                "PNG — máxima calidad",
                "JPG grande — menos espacio",
            ],
        )
        image_quality = "png" if image_quality_label.startswith("PNG") else "large"

        custom_rules = st.checkbox("Personalizar reglas", value=False)
        if custom_rules:
            resolution_label = st.selectbox(
                "Prioridad de impresión",
                [
                    "Exacta primero",
                    "Solo exacta",
                    "Flexible",
                ],
                index={"exact_first": 0, "exact_only": 1, "flexible": 2}[
                    resolution_mode
                ],
            )
            resolution_mode = {
                "Exacta primero": "exact_first",
                "Solo exacta": "exact_only",
                "Flexible": "flexible",
            }[resolution_label]

            quality_label = st.selectbox(
                "Calidad mínima",
                [
                    "Preferir alta resolución",
                    "Aceptar low-res",
                    "Solo alta resolución",
                ],
                index={
                    "prefer_highres": 0,
                    "allow_lowres": 1,
                    "highres_only": 2,
                }[quality_mode],
            )
            quality_mode = {
                "Preferir alta resolución": "prefer_highres",
                "Aceptar low-res": "allow_lowres",
                "Solo alta resolución": "highres_only",
            }[quality_label]
            allow_english = st.checkbox(
                "Permitir inglés como respaldo",
                value=allow_english,
            )
        else:
            st.caption(
                f"`{resolution_mode}` · `{quality_mode}` · "
                f"{'ES/EN' if allow_english else 'solo ES'}"
            )

    include_sideboard = st.checkbox("Incluir sideboard", value=False)
    include_maybeboard = st.checkbox("Incluir maybeboard", value=False)


def current_signature() -> str:
    payload = {
        "decklist": decklist_text,
        "resolution_mode": resolution_mode,
        "quality_mode": quality_mode,
        "allow_english": allow_english,
        "image_quality": image_quality,
        "include_sideboard": include_sideboard,
        "include_maybeboard": include_maybeboard,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_cards() -> list[DeckCard]:
    if not decklist_text.strip():
        raise ValueError("Pega una lista de mazo.")
    cards = parse_exported_decklist(decklist_text)
    if not include_sideboard:
        cards = [card for card in cards if card.zone != "sideboard"]
    if not include_maybeboard:
        cards = [card for card in cards if card.zone != "maybeboard"]
    if not cards:
        raise ValueError(
            "No se ha interpretado ninguna carta. Cada línea debe comenzar "
            "por una cantidad, por ejemplo `1 Arcane Signet (TMC) 57`."
        )
    return cards


def clear_generated_output() -> None:
    for key in ("output_data", "output_name", "output_mime", "report"):
        st.session_state.pop(key, None)


def cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "moxfield_cartas_es_cache"


def mpc_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "moxfield_cartas_es_mpcfill_cache"


def previous_index(indices: list[int], current: int) -> int:
    if current not in indices:
        return indices[0]
    position = indices.index(current)
    return indices[max(0, position - 1)]


def next_index(indices: list[int], current: int) -> int:
    if current not in indices:
        return indices[0]
    position = indices.index(current)
    return indices[min(len(indices) - 1, position + 1)]


def set_review_index(index: int) -> None:
    st.session_state["review_selected_index"] = index
    st.session_state["review_selector_version"] = (
        st.session_state.get("review_selector_version", 0) + 1
    )


def set_workspace_mode(mode: str) -> None:
    st.session_state["workspace_mode"] = mode
    st.session_state["workspace_selector_version"] = (
        st.session_state.get("workspace_selector_version", 0) + 1
    )


def open_card_editor(index: int) -> None:
    set_review_index(index)
    st.session_state["review_only_problematic"] = False
    set_workspace_mode("Editar cartas")


def gallery_preview(
    card: ResolvedCard,
    mpc_client: MpcFillClient | None,
) -> str | bytes | None:
    if card.provider == "mpcfill" and card.scryfall_data and mpc_client:
        face = card.faces[0] if card.faces else None
        try:
            return mpc_client.preview_bytes(
                card.scryfall_data,
                crop_mode=CROP_AUTO,
                crop_shift_x=face.crop_shift_x if face else 0,
                crop_shift_y=face.crop_shift_y if face else 0,
            )
        except MpcFillError:
            return None
    urls = preview_urls(card.scryfall_data)
    if urls:
        return urls[0]
    return card.faces[0].url if card.faces else None


def prefetch_selection(selection: ResolvedCard) -> None:
    if not selection.faces:
        return
    try:
        with ScryfallClient(
            cache_dir(),
            image_quality=st.session_state.get("analysis_image_quality", "png"),
        ) as client:
            for variant in effective_variants(selection):
                for face in variant.faces:
                    client.download_image(face)
    except (ScryfallError, OSError):
        pass


def enforce_automatic_mpcfill_crop(card: ResolvedCard) -> ResolvedCard:
    updated = copy.deepcopy(card)
    variants = effective_variants(updated)
    for variant in variants:
        if variant.provider != "mpcfill":
            continue
        for face in variant.faces:
            face.crop_mode = CROP_AUTO
        if variant.metadata is not None:
            variant.metadata["crop_mode"] = CROP_AUTO
    if updated.allocations:
        updated.allocations = variants
    elif variants:
        primary = variants[0]
        updated.faces = copy.deepcopy(primary.faces)
        updated.scryfall_data = copy.deepcopy(primary.metadata)
    return updated


def enforce_automatic_mpcfill_crop_list(
    cards: list[ResolvedCard],
) -> list[ResolvedCard]:
    return [enforce_automatic_mpcfill_crop(card) for card in cards]



def save_replacement(
    index: int,
    replacement: ResolvedCard,
    *,
    advance_indices: list[int] | None = None,
    add_to_mix: bool = False,
) -> None:
    cards = list(st.session_state["resolved_cards"])
    current = cards[index]
    if add_to_mix:
        updated = copy.deepcopy(current)
        add_variant(updated, enforce_automatic_mpcfill_crop(replacement))
    else:
        updated = replace_all_copies(current, enforce_automatic_mpcfill_crop(replacement))
    cards[index] = updated
    st.session_state["resolved_cards"] = cards
    prefetch_selection(updated)
    if advance_indices:
        set_review_index(next_index(advance_indices, index))
    clear_generated_output()


def update_mpc_crop(
    index: int,
    *,
    shift_x: int,
    shift_y: int,
) -> None:
    cards = list(st.session_state["resolved_cards"])
    card = copy.deepcopy(cards[index])
    variants = effective_variants(card)
    for variant in variants:
        if variant.provider != "mpcfill":
            continue
        for face in variant.faces:
            face.crop_mode = CROP_AUTO
            face.crop_shift_x = shift_x
            face.crop_shift_y = shift_y
        if variant.metadata is not None:
            variant.metadata["crop_mode"] = CROP_AUTO
            variant.metadata["crop_shift_x"] = shift_x
            variant.metadata["crop_shift_y"] = shift_y
    if card.allocations:
        card.allocations = variants
    else:
        primary = variants[0]
        card.faces = copy.deepcopy(primary.faces)
        card.scryfall_data = copy.deepcopy(primary.metadata)
    cards[index] = card
    st.session_state["resolved_cards"] = cards
    prefetch_selection(card)
    clear_generated_output()


def apply_bulk_action(indices: list[int], action: str) -> None:
    if not indices:
        st.warning("Selecciona al menos una carta.")
        return
    cards = list(st.session_state["resolved_cards"])
    progress = st.progress(0.0)
    status = st.empty()

    try:
        if action in {
            "Solo español y alta calidad",
            "Máxima calidad disponible",
            "Respetar impresión exacta",
        }:
            settings = {
                "Solo español y alta calidad": (False, "flexible", "prefer_highres"),
                "Máxima calidad disponible": (True, "flexible", "highres_only"),
                "Respetar impresión exacta": (True, "exact_only", "allow_lowres"),
            }[action]
            with ScryfallClient(
                cache_dir(),
                image_quality=st.session_state["analysis_image_quality"],
            ) as client:
                for position, index in enumerate(indices, start=1):
                    status.write(f"Actualizando **{cards[index].source.name}**")
                    replacement = client.resolve(
                        cards[index].source,
                        allow_english_fallback=settings[0],
                        resolution_mode=settings[1],
                        quality_mode=settings[2],
                    )
                    cards[index] = replace_all_copies(cards[index], replacement)
                    prefetch_selection(cards[index])
                    progress.progress(position / len(indices))

        elif action == "Primer diseño MPCFill de mayor DPI":
            with MpcFillClient(mpc_cache_dir()) as client:
                for position, index in enumerate(indices, start=1):
                    status.write(f"Buscando MPCFill para **{cards[index].source.name}**")
                    designs = client.search_designs(
                        cards[index].source.name,
                        minimum_dpi=300,
                        max_results=1,
                    )
                    if designs:
                        replacement = client.resolve_candidate(
                            cards[index].source,
                            designs[0],
                            crop_mode=CROP_AUTO,
                            type_line=cards[index].type_line,
                        )
                        cards[index] = replace_all_copies(cards[index], replacement)
                        prefetch_selection(cards[index])
                    progress.progress(position / len(indices))

        elif action == "Unificar por nombre con la primera selección":
            template = cards[indices[0]]
            for position, index in enumerate(indices, start=1):
                if cards[index].source.name.casefold() == template.source.name.casefold():
                    cards[index] = clone_selection_for_card(template, cards[index])
                    prefetch_selection(cards[index])
                progress.progress(position / len(indices))

        st.session_state["resolved_cards"] = cards
        clear_generated_output()
        status.success(f"Acción aplicada a {len(indices)} entradas.")
    except (ScryfallError, MpcFillError, OSError, AllocationError) as exc:
        status.error(str(exc))


st.subheader("1. Analizar")
if st.button("Analizar mazo", type="primary", use_container_width=True):
    clear_generated_output()
    try:
        cards = load_cards()
        total_copies = sum(card.quantity for card in cards)
        progress = st.progress(0.0)
        status = st.empty()
        resolved_cards: list[ResolvedCard] = []
        with ScryfallClient(cache_dir(), image_quality=image_quality) as client:
            for index, card in enumerate(cards, start=1):
                status.write(f"Buscando {index}/{len(cards)}: **{card.name}**")
                resolved_cards.append(
                    client.resolve(
                        card,
                        allow_english_fallback=allow_english,
                        resolution_mode=resolution_mode,
                        quality_mode=quality_mode,
                    )
                )
                progress.progress(index / len(cards))

        st.session_state["cards"] = cards
        resolved_cards = enforce_automatic_mpcfill_crop_list(resolved_cards)
        st.session_state["resolved_cards"] = resolved_cards
        st.session_state["analysis_signature"] = current_signature()
        st.session_state["analysis_image_quality"] = image_quality
        st.session_state["alternatives"] = {}
        st.session_state["mpc_alternatives"] = {}
        st.session_state["review_selected_index"] = 0
        st.session_state["review_selector_version"] = 0
        st.session_state["workspace_mode"] = "Vista del mazo"
        st.session_state["workspace_selector_version"] = 0
        st.session_state.pop("review_only_problematic", None)
        progress.progress(1.0)
        status.success(
            f"Análisis completado: {len(cards)} entradas y {total_copies} copias."
        )
    except (ValueError, ScryfallError, OSError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Error inesperado: {exc}")

analysis_ready = bool(st.session_state.get("resolved_cards"))
signature_matches = (
    analysis_ready
    and st.session_state.get("analysis_signature") == current_signature()
)
if analysis_ready and not signature_matches:
    st.warning(
        "La lista o sus opciones han cambiado. Pulsa **Analizar mazo** de nuevo."
    )


def render_persistence_panel() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    with st.expander("💾 Guardar o restaurar elecciones", expanded=False):
        config = export_selection_config(
            cards,
            deck_signature=st.session_state["analysis_signature"],
        )
        st.download_button(
            "Descargar elecciones JSON",
            data=config,
            file_name="elecciones_mazo.json",
            mime="application/json",
            use_container_width=True,
        )
        import_text = st.text_area(
            "Pegar elecciones guardadas",
            key="selection_config_import",
            height=120,
            placeholder="Pega aquí el contenido de elecciones_mazo.json",
        )
        if st.button("Aplicar elecciones guardadas", use_container_width=True):
            try:
                restored, warnings = import_selection_config(import_text, cards)
                restored = enforce_automatic_mpcfill_crop_list(restored)
                st.session_state["resolved_cards"] = restored
                clear_generated_output()
                if warnings:
                    st.warning(" ".join(warnings))
                else:
                    st.success("Elecciones restauradas correctamente.")
                st.rerun(scope="fragment")
            except SelectionConfigError as exc:
                st.error(str(exc))


def render_bulk_panel(filtered: list[int]) -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    with st.expander("⚙️ Edición masiva", expanded=False):
        selected_indices = st.multiselect(
            "Cartas afectadas",
            options=filtered,
            format_func=lambda index: (
                f"{cards[index].source.quantity}× {cards[index].source.name} — "
                f"{gallery_status_label(cards[index])}"
            ),
            key="bulk_selected_indices",
        )
        action = st.selectbox(
            "Acción",
            [
                "Solo español y alta calidad",
                "Máxima calidad disponible",
                "Respetar impresión exacta",
                "Primer diseño MPCFill de mayor DPI",
                "Unificar por nombre con la primera selección",
            ],
        )
        st.caption(
            "Las imágenes de MPCFill se recortan automáticamente. Las demás no necesitan recorte."
        )
        if st.button("Aplicar acción masiva", type="primary", use_container_width=True):
            apply_bulk_action(selected_indices, action)
            st.rerun(scope="fragment")


def render_deck_gallery() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    st.subheader("2. Vista del mazo")
    st.caption(
        "Versiones seleccionadas agrupadas por tipo. Usa los filtros, selecciona "
        "varias entradas para cambios masivos o abre una carta concreta."
    )

    with ScryfallClient(
        cache_dir(),
        image_quality=st.session_state["analysis_image_quality"],
    ) as cache_client:
        cached, total_cache = cache_stats(cards, cache_client)

    problem_count = sum(is_problematic(card) for card in cards)
    multiple_count = sum(card_has_multiple_arts(card) for card in cards)
    metrics = st.columns(5)
    metrics[0].metric("Copias", sum(card.source.quantity for card in cards))
    metrics[1].metric("Entradas", len(cards))
    metrics[2].metric("Pendientes", problem_count)
    metrics[3].metric("Varios artes", multiple_count)
    metrics[4].metric("Caché", f"{cached}/{total_cache}")

    if st.button("Preparar todas las imágenes ahora", use_container_width=True):
        progress = st.progress(0.0)
        status = st.empty()
        with ScryfallClient(
            cache_dir(),
            image_quality=st.session_state["analysis_image_quality"],
        ) as client:
            downloaded, total = prefetch_cards(
                cards,
                client,
                progress_callback=lambda current, amount, name: (
                    status.write(f"Preparando {current}/{amount}: **{name}**"),
                    progress.progress(current / max(amount, 1)),
                ),
            )
        status.success(
            f"Preparación completada: {downloaded} nuevas; {total} imágenes únicas."
        )

    render_persistence_panel()

    filter_cols = st.columns([2.4, 1, 1.2, 1, 1.1])
    with filter_cols[0]:
        query = st.text_input("Buscar", placeholder="Nombre de carta")
    with filter_cols[1]:
        provider = st.selectbox("Fuente", ["Todos", "Scryfall", "MPCFill"])
    with filter_cols[2]:
        state = st.selectbox(
            "Estado",
            [
                "Todos",
                "Pendientes",
                "Manuales",
                "Múltiples artes",
                "Baja resolución",
                "Sin imagen",
            ],
        )
    with filter_cols[3]:
        language = st.selectbox("Idioma", ["Todos", "es", "en"])
    with filter_cols[4]:
        sorting = st.selectbox("Orden", ["Categoría", "Nombre", "Cantidad"])

    indices = filtered_indices(
        cards,
        query=query,
        provider=provider,
        state=state,
        language=language,
    )
    if sorting == "Nombre":
        indices.sort(key=lambda index: cards[index].source.name.casefold())
    elif sorting == "Cantidad":
        indices.sort(key=lambda index: -cards[index].source.quantity)

    render_bulk_panel(indices)
    if not indices:
        st.info("No hay cartas que coincidan con los filtros.")
        return

    mpc_client: MpcFillClient | None = None
    if any(cards[index].provider == "mpcfill" for index in indices):
        mpc_client = MpcFillClient(mpc_cache_dir())
    try:
        filtered_cards = [cards[index] for index in indices]
        for category in group_deck(filtered_cards, indices=indices):
            st.markdown(
                f"### {category.label} <small>({category.quantity})</small>",
                unsafe_allow_html=True,
            )
            entries = list(category.cards)
            for start in range(0, len(entries), 6):
                columns = st.columns(6)
                for column, (index, card) in zip(columns, entries[start : start + 6]):
                    with column:
                        with st.container(border=True):
                            preview = gallery_preview(card, mpc_client)
                            if preview is not None:
                                _, image_column, _ = st.columns([1, 4, 1])
                                with image_column:
                                    st.image(preview, width=105)
                            else:
                                st.caption("🖼️ Sin imagen")
                            st.markdown(
                                f"**{card.source.quantity}× {card.source.name}**"
                            )
                            st.caption(gallery_status_label(card))
                            st.caption(gallery_printing_label(card))
                            if st.button(
                                "✏️ Editar",
                                key=f"gallery_edit_{index}",
                                use_container_width=True,
                            ):
                                open_card_editor(index)
                                st.rerun(scope="fragment")
            st.divider()
    finally:
        if mpc_client:
            mpc_client.close()


def render_selected_preview(card: ResolvedCard) -> None:
    if card.provider == "mpcfill" and card.scryfall_data:
        face = card.faces[0] if card.faces else None
        try:
            with MpcFillClient(mpc_cache_dir()) as client:
                data = client.preview_bytes(
                    card.scryfall_data,
                    crop_mode=CROP_AUTO,
                    crop_shift_x=face.crop_shift_x if face else 0,
                    crop_shift_y=face.crop_shift_y if face else 0,
                )
            _, image_column, _ = st.columns([1, 3, 1])
            with image_column:
                st.image(data, width=210)
        except MpcFillError as exc:
            st.warning(str(exc))
    else:
        urls = preview_urls(card.scryfall_data) or [face.url for face in card.faces]
        for url in urls:
            _, image_column, _ = st.columns([1, 3, 1])
            with image_column:
                st.image(url, width=210)


def render_crop_editor(index: int, card: ResolvedCard) -> None:
    if card.provider != "mpcfill" or not card.scryfall_data or not card.faces:
        return
    face = card.faces[0]
    with st.expander("✂️ Comparar y ajustar recorte MPCFill", expanded=False):
        st.caption(
            "El recorte se aplica automáticamente a cualquier imagen de MPCFill. "
            "Aquí solo puedes ajustar el encuadre si lo necesitas."
        )
        shift_x = st.slider(
            "Desplazamiento horizontal del recorte",
            -100,
            100,
            face.crop_shift_x,
            key=f"crop_shift_x_{index}",
        )
        shift_y = st.slider(
            "Desplazamiento vertical del recorte",
            -100,
            100,
            face.crop_shift_y,
            key=f"crop_shift_y_{index}",
        )
        try:
            with MpcFillClient(mpc_cache_dir()) as client:
                original = client.preview_bytes(card.scryfall_data, crop_mode=CROP_NONE)
                cropped = client.preview_bytes(
                    card.scryfall_data,
                    crop_mode=CROP_AUTO,
                    crop_shift_x=shift_x,
                    crop_shift_y=shift_y,
                )
            original_col, cropped_col = st.columns(2)
            with original_col:
                st.caption("Original")
                st.image(original, width=190)
            with cropped_col:
                st.caption("Resultado automático")
                st.image(cropped, width=190)
        except MpcFillError as exc:
            st.warning(str(exc))
        if st.button("Guardar ajuste de recorte", use_container_width=True):
            update_mpc_crop(index, shift_x=shift_x, shift_y=shift_y)
            st.success("Ajuste guardado. Las imágenes MPCFill seguirán recortándose automáticamente.")
            st.rerun(scope="fragment")


def render_allocations(index: int, card: ResolvedCard) -> None:
    if card.source.quantity <= 1:
        return
    with st.expander("🎨 Repartir copias entre ilustraciones", expanded=bool(card.allocations)):
        variants = effective_variants(card)
        st.caption(
            f"Distribuye las {card.source.quantity} copias. Las cantidades deben "
            "sumar exactamente el total."
        )
        quantities: list[int] = []
        for variant_index, variant in enumerate(variants):
            columns = st.columns([1, 2.5, 1, 1])
            with columns[0]:
                preview = None
                if variant.provider == "mpcfill" and variant.metadata:
                    try:
                        with MpcFillClient(mpc_cache_dir()) as client:
                            face = variant.faces[0] if variant.faces else None
                            preview = client.preview_bytes(
                                variant.metadata,
                                crop_mode=CROP_AUTO,
                                crop_shift_x=face.crop_shift_x if face else 0,
                                crop_shift_y=face.crop_shift_y if face else 0,
                            )
                    except MpcFillError:
                        preview = None
                elif variant.metadata:
                    urls = preview_urls(variant.metadata)
                    preview = urls[0] if urls else None
                if preview:
                    st.image(preview, width=80)
            with columns[1]:
                st.caption(
                    f"**Arte {variant_index + 1}:** "
                    f"{variant.printed_name or card.source.name}  \n"
                    f"{variant.provider} · {(variant.selected_set or '?').upper()} "
                    f"{variant.collector_number or '?'}"
                )
            with columns[2]:
                quantity = st.number_input(
                    "Copias",
                    min_value=0,
                    max_value=card.source.quantity,
                    value=variant.quantity,
                    step=1,
                    key=f"allocation_qty_{index}_{variant_index}",
                )
                quantities.append(int(quantity))
            with columns[3]:
                if len(variants) > 1 and st.button(
                    "Eliminar",
                    key=f"remove_variant_{index}_{variant_index}",
                    use_container_width=True,
                ):
                    try:
                        cards = list(st.session_state["resolved_cards"])
                        updated = copy.deepcopy(cards[index])
                        remove_variant(updated, variant_index)
                        cards[index] = updated
                        st.session_state["resolved_cards"] = cards
                        clear_generated_output()
                        st.rerun(scope="fragment")
                    except AllocationError as exc:
                        st.error(str(exc))
        if st.button("Guardar reparto", use_container_width=True):
            try:
                cards = list(st.session_state["resolved_cards"])
                updated = copy.deepcopy(cards[index])
                set_allocation_quantities(updated, quantities)
                cards[index] = updated
                st.session_state["resolved_cards"] = cards
                clear_generated_output()
                st.success("Reparto guardado.")
                st.rerun(scope="fragment")
            except AllocationError as exc:
                st.error(str(exc))


def render_candidate_actions(
    index: int,
    replacement: ResolvedCard,
    review_indices: list[int],
    key: str,
) -> None:
    card = st.session_state["resolved_cards"][index]
    if card.source.quantity > 1:
        use_all, add_mix = st.columns(2)
        with use_all:
            if st.button(
                "Usar para todas",
                key=f"all_{key}",
                use_container_width=True,
            ):
                save_replacement(index, replacement, advance_indices=review_indices)
                st.rerun(scope="fragment")
        with add_mix:
            if st.button(
                "Añadir al reparto",
                key=f"mix_{key}",
                use_container_width=True,
            ):
                save_replacement(index, replacement, add_to_mix=True)
                st.success("Ilustración añadida al reparto con una copia.")
                st.rerun(scope="fragment")
    else:
        if st.button(
            "Elegir y continuar",
            key=f"one_{key}",
            use_container_width=True,
        ):
            save_replacement(index, replacement, advance_indices=review_indices)
            st.rerun(scope="fragment")


def render_review_panel() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    problem_indices = [index for index, card in enumerate(cards) if is_problematic(card)]

    back_col, title_col = st.columns([1, 4])
    with back_col:
        if st.button("← Volver al mazo", use_container_width=True):
            set_workspace_mode("Vista del mazo")
            st.rerun(scope="fragment")
    with title_col:
        st.subheader("3. Editar versiones")

    with st.expander("Ver tabla completa", expanded=False):
        st.dataframe(
            pd.DataFrame([review_row(index, card) for index, card in enumerate(cards)]),
            use_container_width=True,
            hide_index=True,
        )

    only_problematic = st.checkbox(
        "Mostrar solo cartas problemáticas",
        value=bool(problem_indices),
        key="review_only_problematic",
    )
    review_indices = problem_indices if only_problematic else list(range(len(cards)))
    if not review_indices:
        st.success("No quedan cartas problemáticas.")
        return

    current = st.session_state.get("review_selected_index", review_indices[0])
    if current not in review_indices:
        current = review_indices[0]
    selector_version = st.session_state.get("review_selector_version", 0)
    selected_index = st.selectbox(
        "Carta a revisar",
        options=review_indices,
        index=review_indices.index(current),
        format_func=lambda index: (
            f"{cards[index].source.quantity}× {cards[index].source.name} — "
            f"{gallery_status_label(cards[index])}"
        ),
        key=f"review_selector_{selector_version}",
    )
    st.session_state["review_selected_index"] = selected_index
    position = review_indices.index(selected_index)
    st.progress(
        (position + 1) / len(review_indices),
        text=f"Carta {position + 1} de {len(review_indices)}",
    )

    nav = st.columns([1, 2, 1])
    with nav[0]:
        if st.button("← Anterior", disabled=position == 0, use_container_width=True):
            set_review_index(previous_index(review_indices, selected_index))
            st.rerun(scope="fragment")
    with nav[1]:
        if st.button(
            "Mantener actual y continuar",
            disabled=position == len(review_indices) - 1,
            use_container_width=True,
        ):
            set_review_index(next_index(review_indices, selected_index))
            st.rerun(scope="fragment")
    with nav[2]:
        if st.button(
            "Siguiente →",
            disabled=position == len(review_indices) - 1,
            use_container_width=True,
        ):
            set_review_index(next_index(review_indices, selected_index))
            st.rerun(scope="fragment")

    selected = cards[selected_index]
    selected_col, alternatives_col = st.columns([1, 2])
    with selected_col:
        st.markdown("#### Versión seleccionada")
        render_selected_preview(selected)
        st.markdown("##### Detalles")
        st.caption(
            f"**Carta:** {selected.source.name}  \n"
            f"**Cantidad:** {selected.source.quantity}  \n"
            f"**Elegida:** {(selected.selected_set or '?').upper()} "
            f"{selected.collector_number or '?'}  \n"
            f"**Fuente:** {selected.provider}  \n"
            f"**Idioma:** {(selected.language or '?').upper()}  \n"
            f"**Calidad:** {selected.image_status or 'desconocida'}  \n"
            f"**Estado:** {gallery_status_label(selected)}"
        )
        reasons = problem_reasons(selected)
        if reasons:
            st.warning("Revisar: " + ", ".join(reasons))
        else:
            st.success("Selección correcta.")
        render_crop_editor(selected_index, selected)
        render_allocations(selected_index, selected)

    with alternatives_col:
        st.markdown("#### Otras versiones")
        source = st.radio(
            "Fuente",
            ["Oficiales · Scryfall", "Comunidad · MPCFill"],
            horizontal=True,
            key=f"version_source_{selected_index}",
        )

        if source == "Oficiales · Scryfall":
            filters = st.columns([2, 2, 1])
            with filters[0]:
                include_en = st.checkbox(
                    "Incluir inglés",
                    value=True,
                    key=f"alt_en_{selected_index}",
                )
            with filters[1]:
                highres_only = st.checkbox(
                    "Solo alta resolución",
                    value=True,
                    key=f"alt_high_{selected_index}",
                )
            with filters[2]:
                limit = st.selectbox(
                    "Máximo",
                    [6, 9, 12, 18],
                    index=2,
                    key=f"alt_limit_{selected_index}",
                )
            languages = ("es", "en") if include_en else ("es",)
            cache_key = f"{selected_index}|{languages}|{highres_only}|{limit}"
            cache = st.session_state.setdefault("alternatives", {})
            if cache_key not in cache:
                try:
                    with st.spinner("Cargando impresiones oficiales..."):
                        with ScryfallClient(
                            cache_dir(),
                            image_quality=st.session_state["analysis_image_quality"],
                        ) as client:
                            cache[cache_key] = client.search_alternatives(
                                selected.source.name,
                                languages=languages,
                                highres_only=highres_only,
                                max_results=limit,
                            )
                except (ScryfallError, OSError) as exc:
                    st.error(str(exc))
                    cache[cache_key] = []
            alternatives = cache.get(cache_key, [])
            if not alternatives:
                st.info("No se encontraron impresiones con esos filtros.")
            columns = st.columns(3)
            for alt_index, candidate in enumerate(alternatives):
                with columns[alt_index % 3]:
                    with st.container(border=True):
                        urls = preview_urls(candidate)
                        if urls:
                            _, image_column, _ = st.columns([1, 2, 1])
                            with image_column:
                                st.image(urls[0], width=135)
                        st.caption(candidate_label(candidate))
                        with ScryfallClient(
                            cache_dir(),
                            image_quality=st.session_state["analysis_image_quality"],
                        ) as client:
                            replacement = client.resolve_from_candidate(
                                selected.source,
                                candidate,
                                status="Selección manual",
                            )
                        render_candidate_actions(
                            selected_index,
                            replacement,
                            review_indices,
                            f"scryfall_{selected_index}_{candidate_key(candidate)}",
                        )

        else:
            filters = st.columns([1.5, 1.5, 1])
            with filters[0]:
                language_label = st.selectbox(
                    "Idioma",
                    ["Todos", "Español", "Inglés"],
                    key=f"mpc_lang_{selected_index}",
                )
            with filters[1]:
                minimum_dpi = st.selectbox(
                    "DPI mínimo",
                    [300, 600, 800, 1200],
                    key=f"mpc_dpi_{selected_index}",
                )
            with filters[2]:
                limit = st.selectbox(
                    "Máximo",
                    [6, 9, 12],
                    index=1,
                    key=f"mpc_limit_{selected_index}",
                )
            st.caption(
                "Las miniaturas de MPCFill se recortan automáticamente. Si la imagen no es de MPCFill, no se recorta."
            )
            languages = {
                "Todos": (),
                "Español": ("ES",),
                "Inglés": ("EN",),
            }[language_label]
            cache_key = f"{selected_index}|{languages}|{minimum_dpi}|{limit}"
            cache = st.session_state.setdefault("mpc_alternatives", {})
            try:
                with MpcFillClient(mpc_cache_dir()) as client:
                    if cache_key not in cache:
                        with st.spinner("Buscando diseños MPCFill..."):
                            cache[cache_key] = client.search_designs(
                                selected.source.name,
                                languages=languages,
                                minimum_dpi=minimum_dpi,
                                max_results=limit,
                            )
                    designs = cache.get(cache_key, [])
                    if not designs:
                        st.info("MPCFill no encontró diseños con esos filtros.")
                    columns = st.columns(3)
                    for design_index, candidate in enumerate(designs):
                        with columns[design_index % 3]:
                            with st.container(border=True):
                                try:
                                    preview = client.preview_bytes(
                                        candidate,
                                        crop_mode=CROP_AUTO,
                                    )
                                    _, image_column, _ = st.columns([1, 2, 1])
                                    with image_column:
                                        st.image(preview, width=135)
                                except MpcFillError as exc:
                                    st.warning(str(exc))
                                st.caption(mpc_candidate_label(candidate))
                                replacement = client.resolve_candidate(
                                    selected.source,
                                    candidate,
                                    crop_mode=CROP_AUTO,
                                    type_line=selected.type_line,
                                )
                                render_candidate_actions(
                                    selected_index,
                                    replacement,
                                    review_indices,
                                    f"mpc_{selected_index}_{mpc_candidate_key(candidate)}_auto",
                                )
            except MpcFillError as exc:
                st.warning(f"MPCFill no está disponible: {exc}")


@st.fragment
def render_workspace() -> None:
    options = ["Vista del mazo", "Editar cartas"]
    current = st.session_state.get("workspace_mode", options[0])
    if current not in options:
        current = options[0]
    version = st.session_state.get("workspace_selector_version", 0)
    mode = st.radio(
        "Modo de trabajo",
        options,
        index=options.index(current),
        horizontal=True,
        key=f"workspace_selector_{version}",
    )
    st.session_state["workspace_mode"] = mode
    if mode == "Vista del mazo":
        render_deck_gallery()
    else:
        render_review_panel()


def render_back_selector() -> BackSpec:
    back_label = st.selectbox(
        "Reverso para cartas de una sola cara",
        [
            "Sin reverso",
            "Reverso estándar de Magic",
            "Reverso neutro",
            "URL personalizada",
            "Diseño MPCFill",
        ],
    )
    if back_label == "Sin reverso":
        return no_back()
    if back_label == "Reverso estándar de Magic":
        return standard_magic_back()
    if back_label == "Reverso neutro":
        return neutral_back()
    if back_label == "URL personalizada":
        url = st.text_input("URL de la imagen del reverso")
        if not url:
            return no_back()
        try:
            return custom_url_back(url)
        except ValueError as exc:
            st.warning(str(exc))
            return no_back()

    query = st.text_input(
        "Buscar reverso en MPCFill",
        value="lotus",
        key="mpc_back_query",
    )
    st.caption(
        "Los reversos de MPCFill se recortan automáticamente para mantener el mismo comportamiento que el resto de diseños MPCFill."
    )
    if not query.strip():
        return no_back()
    try:
        with MpcFillClient(mpc_cache_dir()) as client:
            candidates = client.search_cardbacks(query, minimum_dpi=300, max_results=6)
            if not candidates:
                st.info("No se encontraron reversos MPCFill.")
                return no_back()
            selected = st.selectbox(
                "Diseño de reverso",
                options=list(range(len(candidates))),
                format_func=lambda index: mpc_candidate_label(candidates[index]),
                key="mpc_back_candidate",
            )
            preview = client.preview_bytes(candidates[selected], crop_mode=CROP_AUTO)
            st.image(preview, width=150)
            return mpcfill_back(candidates[selected], crop_mode=CROP_AUTO)
    except MpcFillError as exc:
        st.warning(f"MPCFill no está disponible: {exc}")
        return no_back()


def render_export_panel() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    st.subheader("4. Validar y exportar")
    export_format = st.selectbox(
        "Formato de salida",
        [
            "ZIP de imágenes individuales",
            "Paquete MPC / dúplex",
            "PDF A4 — 9 cartas por página",
        ],
    )
    cut_lines = True
    cut_line_style = "ticks"
    cut_line_width = 1.0
    cut_line_color = "#000000"
    cut_line_over_cards = False
    printer_marks = True

    options = st.columns(2)
    with options[0]:
        naming_mode = st.selectbox(
            "Organización de nombres",
            ["Por categoría", "Por posición del mazo"],
            disabled=export_format == "PDF A4 — 9 cartas por página",
        )
    with options[1]:
        cut_lines = st.checkbox(
            "Añadir marcas de corte",
            value=True,
            disabled=export_format != "PDF A4 — 9 cartas por página",
        )

    if export_format == "PDF A4 — 9 cartas por página":
        st.info(
            "Perfil exacto de MPCFillToPDF: A4 3×3, cartas de "
            "63,5 × 88,9 mm, sangrado espejo de 1 mm, páginas 1/1B "
            "y marcas de imprenta."
        )
        with st.expander(
            "Ajustes del PDF de imprenta",
            expanded=False,
        ):
            style_label = st.selectbox(
                "Tipo de líneas de corte",
                [
                    "Marcas cortas en los márgenes — recomendado",
                    "Líneas completas para corte manual",
                ],
            )
            cut_line_style = (
                "ticks"
                if style_label.startswith("Marcas cortas")
                else "full"
            )
            cut_line_width = st.number_input(
                "Grosor de las líneas (pt)",
                min_value=0.1,
                max_value=10.0,
                value=1.0,
                step=0.1,
            )
            cut_line_color = st.color_picker(
                "Color de las líneas",
                value="#000000",
            )
            st.caption(
                "Las marcas de registro y la barra CMYK son las imágenes "
                "originales de MPCFillToPDF y se incluyen siempre en este perfil."
            )
            printer_marks = True
            cut_line_over_cards = st.checkbox(
                "Dibujar las líneas por encima de las cartas",
                value=False,
                help=(
                    "Déjalo desactivado para el comportamiento estándar "
                    "de imprenta de MPCFillToPDF."
                ),
            )

    with st.expander("Configurar reversos", expanded=False):
        back_spec = render_back_selector()

    include_backs = back_spec.mode != "none"
    validation = validate_deck(cards, back_spec=back_spec)
    metrics = st.columns(6)
    metrics[0].metric("Copias", validation.expected_cards)
    metrics[1].metric("Frentes", validation.expected_front_files)
    metrics[2].metric("Reversos", validation.expected_back_files)
    metrics[3].metric("Variantes", validation.variants)
    metrics[4].metric("Sin imagen", len(validation.missing_entries))
    metrics[5].metric(
        "DPI mínimo",
        validation.minimum_known_dpi or "—",
    )

    for error in validation.errors:
        st.error(error)
    for warning in validation.warnings:
        st.warning(warning)

    with st.expander("Detalles de validación", expanded=False):
        if validation.missing_entries:
            st.write("**Sin imagen:** " + ", ".join(validation.missing_entries))
        if validation.lowres_entries:
            st.write("**Baja resolución:** " + ", ".join(validation.lowres_entries))
        if validation.bleed_retained:
            st.write("**Sangrado conservado:** " + ", ".join(validation.bleed_retained))
        if validation.duplicate_entries:
            st.write("**Entradas duplicadas:** " + ", ".join(validation.duplicate_entries))
        if not any(
            [
                validation.missing_entries,
                validation.lowres_entries,
                validation.bleed_retained,
                validation.duplicate_entries,
            ]
        ):
            st.success("No se han detectado incidencias.")

    override_errors = False
    if validation.errors:
        override_errors = st.checkbox("Generar aunque falten imágenes")

    if st.button(
        "Generar salida",
        type="primary",
        use_container_width=True,
        disabled=bool(validation.errors) and not override_errors,
    ):
        progress = st.progress(0.0)
        status = st.empty()
        try:
            with ScryfallClient(
                cache_dir(),
                image_quality=st.session_state["analysis_image_quality"],
            ) as client:
                if export_format == "PDF A4 — 9 cartas por página":
                    status.write("Generando PDF A4...")
                    result = build_a4_pdf(
                        cards,
                        client,
                        back_spec=back_spec,
                        include_backs=include_backs,
                        cut_lines=cut_lines,
                        cut_line_style=cut_line_style,
                        cut_line_width=cut_line_width,
                        cut_line_color=cut_line_color,
                        cut_line_over_cards=cut_line_over_cards,
                        printer_marks=printer_marks,
                    )
                    data = result.data
                    name = "mazo_impresion_mpcfilltopdf.pdf"
                    mime = "application/pdf"
                    report = []
                    progress.progress(1.0)
                    status.success(
                        f"PDF preparado: {result.pages} páginas, "
                        f"{result.page_pairs} parejas y "
                        f"{result.cards} cartas."
                    )
                else:
                    package_mode = (
                        "mpc"
                        if export_format == "Paquete MPC / dúplex"
                        else "images"
                    )
                    data, report = build_zip(
                        cards,
                        client,
                        duplicate_copies=True,
                        progress_callback=lambda current, total, name: (
                            status.write(f"Añadiendo {current}/{total}: **{name}**"),
                            progress.progress(current / max(total, 1)),
                        ),
                        back_spec=back_spec,
                        include_backs=include_backs,
                        naming_mode=(
                            "category"
                            if naming_mode == "Por categoría"
                            else "sequence"
                        ),
                        package_mode=package_mode,
                    )
                    name = (
                        "mazo_paquete_mpc.zip"
                        if package_mode == "mpc"
                        else "mazo_cartas.zip"
                    )
                    mime = "application/zip"
                    progress.progress(1.0)
                    status.success("Paquete preparado correctamente.")

            st.session_state["output_data"] = data
            st.session_state["output_name"] = name
            st.session_state["output_mime"] = mime
            st.session_state["report"] = report
        except (ScryfallError, OSError, ValueError) as exc:
            status.error(str(exc))

    if st.session_state.get("output_data") is not None:
        st.download_button(
            "Descargar resultado",
            data=st.session_state["output_data"],
            file_name=st.session_state["output_name"],
            mime=st.session_state["output_mime"],
            type="primary",
            use_container_width=True,
        )
        report = st.session_state.get("report") or []
        if report:
            with st.expander("Informe final", expanded=False):
                st.dataframe(pd.DataFrame(report), use_container_width=True, hide_index=True)


if signature_matches:
    render_workspace()
    render_export_panel()

st.divider()
st.caption(
    "Herramienta no oficial para uso personal. Las imágenes y marcas de "
    "Magic: The Gathering pertenecen a sus respectivos titulares."
)
