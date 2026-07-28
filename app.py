from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from mtg_downloader.archive import build_zip, cache_stats
from mtg_downloader.backs import standard_magic_back
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
    DEFAULT_PREFERRED_SOURCES,
    MpcFillClient,
    MpcFillError,
    mpc_candidate_key,
    mpc_candidate_label,
)
from mtg_downloader.pdf_export import PdfProgress, build_a4_pdf
from mtg_downloader.profile_resolution import resolve_with_language_fallback
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
    page_title="Proxy Maker",
    page_icon="🃏",
    layout="wide",
)

st.title("🃏 Proxy Maker")

if "app_step" not in st.session_state:
    st.session_state["app_step"] = (
        2 if st.session_state.get("resolved_cards") else 1
    )
app_step = int(st.session_state.get("app_step", 1))
if app_step not in {1, 2, 3}:
    app_step = 1
    st.session_state["app_step"] = 1

step_labels = (
    "1. Lista y opciones",
    "2. Revisar versiones",
    "3. Validar y exportar",
)
step_columns = st.columns(3)
for step_number, (column, label) in enumerate(
    zip(step_columns, step_labels),
    start=1,
):
    with column:
        if step_number == app_step:
            st.markdown(f"### **{label}**")
        elif step_number < app_step:
            st.markdown(f"### ✅ {label}")
        else:
            st.markdown(f"### {label}")
st.progress((app_step - 1) / 2)

flash_message = st.session_state.pop("flash_message", None)
if flash_message:
    st.success(flash_message)

saved_config = dict(st.session_state.get("analysis_config") or {})
analysis_submitted = False

if app_step == 1:
    st.write(
        "Pega la exportación de tu mazo y elige cómo deben buscarse las "
        "impresiones. El resto de la aplicación aparecerá después del análisis."
    )

    with st.expander("Cómo obtener la lista", expanded=False):
        st.markdown(
            """
1. Abre el mazo en Moxfield.
2. Exporta o copia la lista como texto.
3. Pega el contenido en esta aplicación.
4. Pulsa **Analizar mazo**.

```text
Commander:
1 Beorn the Fierce (HOB) 119 *F*

Deck:
1 Arcane Signet (TMC) 57
27 Forest (M20) 279
```

Una entrada con 27 copias genera 27 cartas físicas y puede repartirse entre
varias ilustraciones durante el paso de revisión.
"""
        )

    left, right = st.columns([3, 2])
    with left:
        decklist_text = st.text_area(
            "Lista del mazo",
            value=str(saved_config.get("decklist", "")),
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

        source_labels = {
            "Scryfall": "scryfall",
            "MPCFill": "mpcfill",
        }
        saved_image_source = str(
            saved_config.get("preferred_image_source", "scryfall")
        )
        if saved_image_source not in {"scryfall", "mpcfill"}:
            saved_image_source = "scryfall"
        current_source_label = (
            "MPCFill" if saved_image_source == "mpcfill" else "Scryfall"
        )
        source_label = st.selectbox(
            "Fuente principal",
            options=list(source_labels),
            index=list(source_labels).index(current_source_label),
            help=(
                "Scryfall usa imágenes oficiales. MPCFill usa diseños de la "
                "comunidad y, si existen, prioriza automáticamente a "
                "MrTeferi, PsilosX y Chilli_Axe."
            ),
        )
        preferred_image_source = source_labels[source_label]

        language_labels = {
            "Español": "es",
            "Inglés": "en",
        }
        saved_language = str(
            saved_config.get("preferred_language", "es")
        )
        if saved_language not in {"es", "en"}:
            saved_language = "es"
        current_language_label = (
            "Español" if saved_language == "es" else "Inglés"
        )
        language_label = st.selectbox(
            "Idioma principal",
            options=list(language_labels),
            index=list(language_labels).index(current_language_label),
            help=(
                "La búsqueda se completa en este idioma antes de probar "
                "el idioma de respaldo."
            ),
        )
        preferred_language = language_labels[language_label]

        resolution_labels = {
            "Respetar la edición indicada primero": "exact_first",
            "Usar únicamente la edición indicada": "exact_only",
            "Buscar en cualquier edición": "flexible",
        }
        saved_resolution = str(
            saved_config.get("resolution_mode", "exact_first")
        )
        current_resolution_label = next(
            (
                label
                for label, value in resolution_labels.items()
                if value == saved_resolution
            ),
            "Respetar la edición indicada primero",
        )
        resolution_label = st.selectbox(
            "Edición",
            options=list(resolution_labels),
            index=list(resolution_labels).index(
                current_resolution_label
            ),
            help=(
                "Define cuánto debe respetarse la edición y el número de "
                "coleccionista de la lista."
            ),
        )
        resolution_mode = resolution_labels[resolution_label]

        quality_labels = {
            "Preferir alta resolución": "prefer_highres",
            "Aceptar imágenes lowres": "allow_lowres",
            "Usar solo alta resolución": "highres_only",
        }
        saved_quality = str(
            saved_config.get("quality_mode", "prefer_highres")
        )
        current_quality_label = next(
            (
                label
                for label, value in quality_labels.items()
                if value == saved_quality
            ),
            "Preferir alta resolución",
        )
        quality_label = st.selectbox(
            "Calidad",
            options=list(quality_labels),
            index=list(quality_labels).index(current_quality_label),
        )
        quality_mode = quality_labels[quality_label]

        image_quality = str(saved_config.get("image_quality", "png"))
        with st.expander("Opciones avanzadas", expanded=False):
            fallback_label = (
                "Usar inglés como respaldo si falta una imagen válida"
                if preferred_language == "es"
                else "Usar español como respaldo si falta una imagen válida"
            )
            allow_language_fallback = st.checkbox(
                fallback_label,
                value=bool(
                    saved_config.get("allow_language_fallback", True)
                ),
            )

            image_quality_label = st.selectbox(
                "Formato de imagen",
                [
                    "PNG — máxima calidad",
                    "JPG grande — menos espacio",
                ],
                index=0 if image_quality == "png" else 1,
            )
            image_quality = (
                "png"
                if image_quality_label.startswith("PNG")
                else "large"
            )

            board_options = st.columns(2)
            with board_options[0]:
                include_sideboard = st.checkbox(
                    "Incluir sideboard",
                    value=bool(
                        saved_config.get("include_sideboard", False)
                    ),
                )
            with board_options[1]:
                include_maybeboard = st.checkbox(
                    "Incluir maybeboard",
                    value=bool(
                        saved_config.get("include_maybeboard", False)
                    ),
                )

    analysis_submitted = st.button(
        "Analizar mazo",
        type="primary",
        use_container_width=True,
    )

    analysis_config = {
        "decklist": decklist_text,
        "preferred_image_source": preferred_image_source,
        "preferred_language": preferred_language,
        "allow_language_fallback": allow_language_fallback,
        "resolution_mode": resolution_mode,
        "quality_mode": quality_mode,
        "image_quality": image_quality,
        "include_sideboard": include_sideboard,
        "include_maybeboard": include_maybeboard,
    }
else:
    analysis_config = saved_config
    decklist_text = str(analysis_config.get("decklist", ""))
    preferred_image_source = str(
        analysis_config.get("preferred_image_source", "scryfall")
    )
    preferred_language = str(
        analysis_config.get("preferred_language", "es")
    )
    allow_language_fallback = bool(
        analysis_config.get("allow_language_fallback", True)
    )
    resolution_mode = str(
        analysis_config.get("resolution_mode", "exact_first")
    )
    quality_mode = str(
        analysis_config.get("quality_mode", "prefer_highres")
    )
    image_quality = str(analysis_config.get("image_quality", "png"))
    include_sideboard = bool(
        analysis_config.get("include_sideboard", False)
    )
    include_maybeboard = bool(
        analysis_config.get("include_maybeboard", False)
    )


def current_signature() -> str:
    payload = {
        "decklist": decklist_text,
        "preferred_image_source": preferred_image_source,
        "preferred_language": preferred_language,
        "allow_language_fallback": allow_language_fallback,
        "resolution_mode": resolution_mode,
        "quality_mode": quality_mode,
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


if app_step == 1 and analysis_submitted:
    clear_generated_output()
    try:
        cards = load_cards()
        requested_signature = current_signature()

        if (
            st.session_state.get("analysis_signature")
            == requested_signature
            and st.session_state.get("resolved_cards")
        ):
            st.session_state["analysis_config"] = analysis_config
            st.session_state["app_step"] = 2
            st.session_state["flash_message"] = (
                "Se ha reutilizado el análisis anterior porque la lista y "
                "las opciones no han cambiado."
            )
            st.rerun()

        total_copies = sum(card.quantity for card in cards)
        progress = st.progress(0.0)
        status = st.empty()
        started_at = time.monotonic()
        resolved_cards: list[ResolvedCard] = []
        temporary_failures = 0
        current_card_name = {"value": ""}

        def show_scryfall_retry(
            status_code: int | None,
            attempt: int,
            max_retries: int,
            delay: float,
        ) -> None:
            code_label = (
                f"HTTP {status_code}"
                if status_code is not None
                else "error de conexión"
            )
            status.write(
                f"Scryfall está temporalmente saturado ({code_label}). "
                f"Reintento {attempt}/{max_retries} en "
                f"{delay:.1f} s · "
                f"**{current_card_name['value']}**"
            )

        if preferred_image_source == "mpcfill":
            analysis_client = MpcFillClient(mpc_cache_dir())
        else:
            analysis_client = ScryfallClient(
                cache_dir(),
                image_quality=image_quality,
                retry_callback=show_scryfall_retry,
            )

        with analysis_client as client:
            for index, card in enumerate(cards, start=1):
                current_card_name["value"] = card.name
                elapsed = int(time.monotonic() - started_at)
                status.write(
                    f"Analizando {index}/{len(cards)} · "
                    f"**{card.name}** · "
                    f"{elapsed // 60}:{elapsed % 60:02d}"
                )
                try:
                    if preferred_image_source == "mpcfill":
                        resolved = client.resolve_auto(
                            card,
                            preferred_language=preferred_language,
                            allow_language_fallback=allow_language_fallback,
                            resolution_mode=resolution_mode,
                            quality_mode=quality_mode,
                            preferred_sources=DEFAULT_PREFERRED_SOURCES,
                        )
                    else:
                        resolved = resolve_with_language_fallback(
                            client,
                            card,
                            preferred_language=preferred_language,
                            allow_language_fallback=allow_language_fallback,
                            resolution_mode=resolution_mode,
                            quality_mode=quality_mode,
                        )
                except ScryfallError as exc:
                    temporary_failures += 1
                    resolved = ResolvedCard(
                        source=card,
                        status="Error temporal de Scryfall",
                        error=str(exc),
                    )
                except MpcFillError as exc:
                    temporary_failures += 1
                    resolved = ResolvedCard(
                        source=card,
                        status="Error temporal de MPCFill",
                        provider="mpcfill",
                        error=str(exc),
                    )
                resolved_cards.append(resolved)
                progress.progress(index / len(cards))

        resolved_cards = enforce_automatic_mpcfill_crop_list(
            resolved_cards
        )
        st.session_state["cards"] = cards
        st.session_state["resolved_cards"] = resolved_cards
        st.session_state["analysis_config"] = analysis_config
        st.session_state["analysis_signature"] = requested_signature
        st.session_state["analysis_image_quality"] = image_quality
        st.session_state["alternatives"] = {}
        st.session_state["mpc_alternatives"] = {}
        st.session_state["review_selected_index"] = 0
        st.session_state["review_selector_version"] = 0
        st.session_state["workspace_mode"] = "Vista del mazo"
        st.session_state["workspace_selector_version"] = 0
        st.session_state.pop("review_only_problematic", None)
        st.session_state["app_step"] = 2
        if temporary_failures:
            st.session_state["flash_message"] = (
                f"Análisis completado: {len(cards)} entradas y "
                f"{total_copies} copias. "
                f"{temporary_failures} cartas quedaron pendientes por "
                f"errores temporales de Scryfall."
            )
        else:
            st.session_state["flash_message"] = (
                f"Análisis completado: {len(cards)} entradas y "
                f"{total_copies} copias."
            )
        st.rerun()
    except (ValueError, ScryfallError, OSError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Error inesperado: {exc}")

analysis_ready = bool(st.session_state.get("resolved_cards"))
signature_matches = (
    analysis_ready
    and st.session_state.get("analysis_signature") == current_signature()
)
if app_step == 1 and analysis_ready:
    if signature_matches:
        st.info(
            "El análisis anterior sigue guardado. Puedes volver a revisarlo "
            "sin repetir ninguna búsqueda."
        )
        return_label = "Volver a revisar el análisis guardado →"
    else:
        st.warning(
            "Has cambiado la lista o alguna opción. Puedes analizar de nuevo "
            "o descartar estos cambios y volver al análisis guardado."
        )
        return_label = "Descartar cambios y volver al análisis guardado"

    if st.button(
        return_label,
        key="return_to_saved_analysis",
        use_container_width=True,
    ):
        st.session_state["app_step"] = 2
        st.rerun()


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



def render_gallery_grouped_section(
    title: str,
    description: str,
    section_indices: list[int],
    cards: list[ResolvedCard],
    mpc_client: MpcFillClient | None,
) -> None:
    if title:
        st.markdown(f"## {title}")
    if description:
        st.caption(description)

    filtered_cards = [cards[index] for index in section_indices]
    for category in group_deck(filtered_cards, indices=section_indices):
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
                            "Cambiar versión",
                            key=f"gallery_edit_{index}",
                            use_container_width=True,
                        ):
                            open_card_editor(index)
                            st.rerun(scope="fragment")
        st.divider()


def render_deck_gallery() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    st.subheader("2. Vista del mazo")
    st.caption(
        "Las cartas problemáticas aparecen primero, agrupadas aparte del resto. "
        "Usa los filtros, selecciona varias entradas para cambios masivos o abre una carta concreta."
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

    problematic_indices = [
        index for index in indices if is_problematic(cards[index])
    ]
    healthy_indices = [
        index for index in indices if not is_problematic(cards[index])
    ]

    mpc_client: MpcFillClient | None = None
    if any(cards[index].provider == "mpcfill" for index in indices):
        mpc_client = MpcFillClient(mpc_cache_dir())
    try:
        if problematic_indices:
            render_gallery_grouped_section(
                "⚠️ Cartas con problemas",
                "Estas cartas necesitan revisión o pueden requerir una edición manual.",
                problematic_indices,
                cards,
                mpc_client,
            )
        else:
            st.success("No hay cartas con problemas.")

        if healthy_indices:
            with st.expander(
                f"Ver {len(healthy_indices)} cartas correctas",
                expanded=False,
            ):
                render_gallery_grouped_section(
                    "",
                    "",
                    healthy_indices,
                    cards,
                    mpc_client,
                )
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
        source_options = [
            "Oficiales · Scryfall",
            "Comunidad · MPCFill",
        ]
        source_state_key = f"version_source_{selected_index}"
        if source_state_key not in st.session_state:
            st.session_state[source_state_key] = (
                "Comunidad · MPCFill"
                if preferred_image_source == "mpcfill"
                else "Oficiales · Scryfall"
            )
        source = st.radio(
            "Fuente",
            source_options,
            horizontal=True,
            key=source_state_key,
        )

        primary_language = (
            preferred_language
            if preferred_language in {"es", "en"}
            else "es"
        )
        secondary_language = (
            "en" if primary_language == "es" else "es"
        )
        inherited_language_label = (
            "Español e inglés"
            if allow_language_fallback
            else (
                "Solo español"
                if primary_language == "es"
                else "Solo inglés"
            )
        )
        language_options = [
            "Español e inglés",
            "Solo español",
            "Solo inglés",
        ]

        if source == "Oficiales · Scryfall":
            quality_options = [
                "Preferir alta resolución",
                "Solo alta resolución",
                "Aceptar imágenes lowres",
            ]
            inherited_quality_label = {
                "prefer_highres": "Preferir alta resolución",
                "highres_only": "Solo alta resolución",
                "allow_lowres": "Aceptar imágenes lowres",
            }.get(quality_mode, "Preferir alta resolución")

            with st.expander("Filtros", expanded=False):
                filters = st.columns(2)
                with filters[0]:
                    language_label = st.selectbox(
                        "Idioma",
                        language_options,
                        index=language_options.index(
                            inherited_language_label
                        ),
                        key=f"alt_lang_{selected_index}",
                    )
                with filters[1]:
                    quality_label = st.selectbox(
                        "Calidad",
                        quality_options,
                        index=quality_options.index(
                            inherited_quality_label
                        ),
                        key=f"alt_quality_{selected_index}",
                    )

            languages = {
                "Español e inglés": (
                    primary_language,
                    secondary_language,
                ),
                "Solo español": ("es",),
                "Solo inglés": ("en",),
            }[language_label]
            highres_only = quality_label == "Solo alta resolución"
            visible_key = (
                f"alt_visible_{selected_index}_{languages}_"
                f"{quality_label}"
            )
            visible_limit = int(st.session_state.get(visible_key, 12))
            cache_key = (
                f"{selected_index}|{languages}|"
                f"{highres_only}|{visible_limit}"
            )
            cache = st.session_state.setdefault("alternatives", {})
            if cache_key not in cache:
                try:
                    with st.spinner("Cargando impresiones oficiales..."):
                        with ScryfallClient(
                            cache_dir(),
                            image_quality=st.session_state[
                                "analysis_image_quality"
                            ],
                        ) as client:
                            cache[cache_key] = client.search_alternatives(
                                selected.source.name,
                                languages=languages,
                                highres_only=highres_only,
                                max_results=visible_limit,
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
                            image_quality=st.session_state[
                                "analysis_image_quality"
                            ],
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
                            f"scryfall_{selected_index}_"
                            f"{candidate_key(candidate)}",
                        )

            if len(alternatives) >= visible_limit and visible_limit < 48:
                if st.button(
                    "Mostrar 12 más",
                    key=f"show_more_scryfall_{selected_index}",
                    use_container_width=True,
                ):
                    st.session_state[visible_key] = visible_limit + 12
                    st.rerun(scope="fragment")

        else:
            inherited_dpi = {
                "allow_lowres": 300,
                "prefer_highres": 600,
                "highres_only": 800,
            }.get(quality_mode, 600)
            dpi_options = [300, 600, 800, 1200]

            with st.expander("Filtros", expanded=False):
                filters = st.columns(2)
                with filters[0]:
                    language_label = st.selectbox(
                        "Idioma",
                        language_options,
                        index=language_options.index(
                            inherited_language_label
                        ),
                        key=f"mpc_lang_{selected_index}",
                    )
                with filters[1]:
                    minimum_dpi = st.selectbox(
                        "DPI mínimo",
                        dpi_options,
                        index=dpi_options.index(inherited_dpi),
                        key=f"mpc_dpi_{selected_index}",
                    )

            languages = {
                "Español e inglés": ("ES", "EN"),
                "Solo español": ("ES",),
                "Solo inglés": ("EN",),
            }[language_label]
            visible_key = (
                f"mpc_visible_{selected_index}_{languages}_"
                f"{minimum_dpi}"
            )
            visible_limit = int(st.session_state.get(visible_key, 12))
            cache_key = (
                f"{selected_index}|{languages}|"
                f"{minimum_dpi}|{visible_limit}"
            )
            cache = st.session_state.setdefault("mpc_alternatives", {})
            try:
                with MpcFillClient(mpc_cache_dir()) as client:
                    if cache_key not in cache:
                        with st.spinner("Buscando diseños MPCFill..."):
                            cache[cache_key] = client.search_designs(
                                selected.source.name,
                                languages=languages,
                                minimum_dpi=minimum_dpi,
                                max_results=visible_limit,
                                preferred_sources=DEFAULT_PREFERRED_SOURCES,
                                fuzzy_search=True,
                            )
                    designs = cache.get(cache_key, [])
                    if not designs:
                        st.info(
                            "MPCFill no encontró diseños con esos filtros."
                        )
                    columns = st.columns(3)
                    for design_index, candidate in enumerate(designs):
                        with columns[design_index % 3]:
                            with st.container(border=True):
                                try:
                                    preview = client.preview_bytes(
                                        candidate,
                                        crop_mode=CROP_AUTO,
                                    )
                                    _, image_column, _ = st.columns(
                                        [1, 2, 1]
                                    )
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
                                    f"mpc_{selected_index}_"
                                    f"{mpc_candidate_key(candidate)}_auto",
                                )

                    if len(designs) >= visible_limit and visible_limit < 48:
                        if st.button(
                            "Mostrar 12 más",
                            key=f"show_more_mpc_{selected_index}",
                            use_container_width=True,
                        ):
                            st.session_state[visible_key] = (
                                visible_limit + 12
                            )
                            st.rerun(scope="fragment")
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


def render_export_panel() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    st.subheader("3. Validar y exportar")

    cut_lines = True
    cut_line_style = "ticks"
    cut_line_width = 1.0
    cut_line_color = "#000000"
    cut_line_over_cards = False
    printer_marks = True
    back_spec = standard_magic_back()
    include_backs = True

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
    generation_disabled = bool(validation.errors) and not override_errors

    st.info(
        "PDF A4 3×3 con cartas de 63,5 × 88,9 mm, "
        "sangrado espejo de 1 mm, páginas 1/1B y marcas de imprenta."
    )
    with st.expander("Ajustes del PDF", expanded=False):
        cut_lines = st.checkbox(
            "Añadir marcas de corte",
            value=True,
        )
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
            "Las marcas de registro y la barra CMYK originales de "
            "MPCFillToPDF se incluyen siempre."
        )
        cut_line_over_cards = st.checkbox(
            "Dibujar las líneas por encima de las cartas",
            value=False,
            help=(
                "Déjalo desactivado para el comportamiento estándar "
                "de imprenta de MPCFillToPDF."
            ),
        )

    pdf_requested = st.button(
        "Generar PDF A4",
        type="primary",
        use_container_width=True,
        disabled=generation_disabled,
    )
    st.caption(
        "Las imágenes necesarias se descargan automáticamente al generar."
    )

    images_requested = False
    mpc_requested = False
    naming_mode = "Por categoría"
    with st.expander("Otros formatos", expanded=False):
        naming_mode = st.selectbox(
            "Organización de nombres",
            ["Por categoría", "Por posición del mazo"],
        )
        other_columns = st.columns(2)
        with other_columns[0]:
            images_requested = st.button(
                "Generar ZIP de imágenes",
                use_container_width=True,
                disabled=generation_disabled,
            )
        with other_columns[1]:
            mpc_requested = st.button(
                "Generar paquete MPC / dúplex",
                use_container_width=True,
                disabled=generation_disabled,
            )

    requested_format: str | None = None
    if pdf_requested:
        requested_format = "pdf"
    elif images_requested:
        requested_format = "images"
    elif mpc_requested:
        requested_format = "mpc"

    if requested_format:
        progress = st.progress(0.0)
        status = st.empty()
        try:
            with ScryfallClient(
                cache_dir(),
                image_quality=st.session_state["analysis_image_quality"],
            ) as client:
                if requested_format == "pdf":
                    started_at = time.monotonic()

                    def update_pdf_progress(event: PdfProgress) -> None:
                        elapsed = int(time.monotonic() - started_at)
                        progress.progress(
                            min(event.current / max(event.total, 1), 1.0)
                        )
                        elapsed_text = f"{elapsed // 60}:{elapsed % 60:02d}"

                        if event.phase == "front":
                            status.write(
                                f"Preparando frente "
                                f"{event.phase_current}/{event.phase_total} "
                                f"· página {event.page_label} "
                                f"· **{event.label}** "
                                f"· {elapsed_text}"
                            )
                        elif event.phase == "back":
                            status.write(
                                f"Preparando reverso "
                                f"{event.phase_current}/{event.phase_total} "
                                f"· página {event.page_label} "
                                f"· **{event.label}** "
                                f"· {elapsed_text}"
                            )
                        elif event.phase == "common_back":
                            status.write(
                                f"Preparando reverso común: "
                                f"**{event.label}** · {elapsed_text}"
                            )
                        elif event.phase == "page":
                            status.write(
                                f"Montando página "
                                f"{event.phase_current}/{event.phase_total}: "
                                f"**{event.label}** · {elapsed_text}"
                            )
                        elif event.phase == "finalizing":
                            status.write(
                                f"Finalizando y comprimiendo el PDF "
                                f"· {elapsed_text}"
                            )

                    status.write("Iniciando generación del PDF...")
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
                        progress_callback=update_pdf_progress,
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
                    data, report = build_zip(
                        cards,
                        client,
                        duplicate_copies=True,
                        progress_callback=lambda current, total, name: (
                            status.write(
                                f"Añadiendo {current}/{total}: **{name}**"
                            ),
                            progress.progress(current / max(total, 1)),
                        ),
                        back_spec=back_spec,
                        include_backs=include_backs,
                        naming_mode=(
                            "category"
                            if naming_mode == "Por categoría"
                            else "sequence"
                        ),
                        package_mode=requested_format,
                    )
                    name = (
                        "mazo_paquete_mpc.zip"
                        if requested_format == "mpc"
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
                st.dataframe(
                    pd.DataFrame(report),
                    use_container_width=True,
                    hide_index=True,
                )


if app_step == 2 and signature_matches:
    top_navigation = st.columns([1, 2, 1])
    with top_navigation[0]:
        if st.button(
            "← Lista y opciones",
            key="step2_back_top",
            use_container_width=True,
        ):
            st.session_state["app_step"] = 1
            st.rerun()
    with top_navigation[2]:
        if st.button(
            "Continuar a exportación →",
            key="step2_next_top",
            type="primary",
            use_container_width=True,
        ):
            st.session_state["app_step"] = 3
            st.rerun()

    st.caption(
        "Volver al paso 1 no elimina el análisis ni las versiones elegidas."
    )
    render_workspace()

    bottom_navigation = st.columns([1, 2, 1])
    with bottom_navigation[0]:
        if st.button(
            "← Lista y opciones",
            key="step2_back_bottom",
            use_container_width=True,
        ):
            st.session_state["app_step"] = 1
            st.rerun()
    with bottom_navigation[2]:
        if st.button(
            "Continuar a exportación →",
            key="step2_next_bottom",
            type="primary",
            use_container_width=True,
        ):
            st.session_state["app_step"] = 3
            st.rerun()

elif app_step == 3 and signature_matches:
    navigation = st.columns([1, 3])
    with navigation[0]:
        if st.button(
            "← Volver a revisar",
            use_container_width=True,
        ):
            st.session_state["app_step"] = 2
            st.rerun()

    render_export_panel()

elif app_step in {2, 3} and not signature_matches:
    st.warning(
        "El análisis guardado ya no coincide con la configuración. "
        "Vuelve al primer paso y analiza el mazo de nuevo."
    )
    if st.button("Volver a lista y opciones", type="primary"):
        st.session_state["app_step"] = 1
        st.rerun()

st.divider()
st.caption(
    "Herramienta no oficial para uso personal. Las imágenes y marcas de "
    "Magic: The Gathering pertenecen a sus respectivos titulares."
)
