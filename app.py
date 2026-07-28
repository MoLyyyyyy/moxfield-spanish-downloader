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
from mtg_downloader.filenames import multi_deck_pdf_filename
from mtg_downloader.image_processing import CROP_AUTO, CROP_FORCE, CROP_NONE
from mtg_downloader.models import CardVariant, DeckCard, ImageFace, ResolvedCard
from mtg_downloader.deck_workflow import (
    deck_configs_from_analysis_config,
    deck_position_for_card,
    deck_settings_label,
    indices_for_deck,
    normalise_deck_config,
)
from mtg_downloader.multi_deck import (
    MultiDeckResult,
    parse_deck_configurations,
    serialise_deck_summaries,
)
from mtg_downloader.mpcfill import (
    DEFAULT_PREFERRED_SOURCES,
    MpcFillClient,
    MpcFillError,
    mpc_candidate_key,
    mpc_candidate_label,
    mpc_candidate_mentions_set_code,
)
from mtg_downloader.pdf_export import PdfProgress, build_a4_pdf
from mtg_downloader.pdf_split import (
    PDF_SPLIT_LIMIT_BYTES,
    PdfPart,
    build_pdf_parts_zip,
    format_file_size,
    split_pdf_if_needed,
)
from mtg_downloader.print_layout import calculate_sheet_usage
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

ANALYSIS_ENGINE_VERSION = "per-deck-workflow-v2"
BUILD_VERSION = "2026.07.28-per-deck-workflow-v2"

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
        "Configura cada mazo por separado. Cada lista conserva su propia "
        "fuente, idioma, edición y calidad durante todo el análisis y la revisión."
    )

    with st.expander("Cómo funciona el modo multimazo", expanded=False):
        st.markdown(
            """
1. Elige el **Número de mazos**.
2. Abre la pestaña de cada mazo.
3. Pega su lista y configura su fuente, idioma y calidad.
4. Pulsa **Analizar mazos**.
5. Revisa y corrige un mazo cada vez.

Los mazos permanecen separados durante el análisis, la galería, la edición
manual y las acciones masivas. Solo se concatenan al generar el PDF final,
para que el siguiente mazo rellene los huecos del anterior.
"""
        )

    saved_deck_configs = deck_configs_from_analysis_config(saved_config)
    deck_count = int(
        st.number_input(
            "Número de mazos",
            min_value=1,
            max_value=12,
            value=max(1, len(saved_deck_configs)),
            step=1,
            help=(
                "Cada mazo tendrá su propia lista y sus propios ajustes. "
                "El orden de las pestañas será el orden del PDF final."
            ),
        )
    )
    st.caption(
        "Los ajustes y las correcciones no se mezclan entre mazos. "
        "Durante la exportación, el siguiente mazo rellena los huecos libres "
        "del anterior."
    )

    tabs = st.tabs(
        [
            (
                f"Mazo {position + 1}"
                if position >= len(saved_deck_configs)
                else (
                    f"Mazo {position + 1} · "
                    f"{saved_deck_configs[position]['decklist'].splitlines()[0][:28]}"
                    if saved_deck_configs[position]["decklist"].strip()
                    else f"Mazo {position + 1}"
                )
            )
            for position in range(deck_count)
        ]
    )

    deck_configs: list[dict[str, Any]] = []
    source_labels = {
        "Scryfall · imágenes oficiales": "scryfall",
        "MPCFill · diseños de la comunidad": "mpcfill",
    }
    language_labels = {
        "Español": "es",
        "Inglés": "en",
    }
    resolution_labels = {
        "Respetar la edición indicada primero": "exact_first",
        "Usar únicamente la edición indicada": "exact_only",
        "Buscar en cualquier edición": "flexible",
    }
    quality_labels = {
        "Preferir alta resolución": "prefer_highres",
        "Aceptar imágenes lowres": "allow_lowres",
        "Usar solo alta resolución": "highres_only",
    }

    for deck_position, tab in enumerate(tabs):
        base = (
            saved_deck_configs[deck_position]
            if deck_position < len(saved_deck_configs)
            else normalise_deck_config(None)
        )
        with tab:
            st.markdown(f"### Configuración del mazo {deck_position + 1}")
            list_column, settings_column = st.columns([3, 2])

            with list_column:
                decklist = st.text_area(
                    "Lista",
                    value=base["decklist"],
                    height=390,
                    placeholder=(
                        "Commander:\n"
                        "1 Beorn the Fierce (HOB) 119 *F*\n\n"
                        "Deck:\n"
                        "1 Arcane Signet (TMC) 57\n"
                        "27 Forest (M20) 279"
                    ),
                    help=(
                        "Se respetan cantidad, edición y número de "
                        "coleccionista."
                    ),
                    key=f"decklist_input_{deck_position}",
                )

            with settings_column:
                source_value = base["preferred_image_source"]
                source_label = st.selectbox(
                    "Fuente principal",
                    options=list(source_labels),
                    index=list(source_labels.values()).index(source_value),
                    key=f"deck_source_{deck_position}",
                    help=(
                        "Esta elección solo se aplica a este mazo. "
                        "Las cartas podrán corregirse manualmente con "
                        "Scryfall o MPCFill durante la revisión. MPCFill "
                        "prioriza a MrTeferi, PsilosX, Chilli_Axe, CompC "
                        "y Hathwellcrisping."
                    ),
                )
                preferred_image_source = source_labels[source_label]

                language_value = base["preferred_language"]
                language_label = st.selectbox(
                    "Idioma principal",
                    options=list(language_labels),
                    index=list(language_labels.values()).index(language_value),
                    key=f"deck_language_{deck_position}",
                )
                preferred_language = language_labels[language_label]

                resolution_value = base["resolution_mode"]
                resolution_label = st.selectbox(
                    "Edición",
                    options=list(resolution_labels),
                    index=list(resolution_labels.values()).index(
                        resolution_value
                    ),
                    key=f"deck_resolution_{deck_position}",
                )
                resolution_mode = resolution_labels[resolution_label]

                quality_value = base["quality_mode"]
                quality_label = st.selectbox(
                    "Calidad",
                    options=list(quality_labels),
                    index=list(quality_labels.values()).index(quality_value),
                    key=f"deck_quality_{deck_position}",
                )
                quality_mode = quality_labels[quality_label]

                with st.expander(
                    f"Opciones avanzadas del mazo {deck_position + 1}",
                    expanded=False,
                ):
                    fallback_language = (
                        "inglés"
                        if preferred_language == "es"
                        else "español"
                    )
                    allow_language_fallback = st.checkbox(
                        f"Usar {fallback_language} como respaldo",
                        value=base["allow_language_fallback"],
                        key=f"deck_fallback_{deck_position}",
                    )

                    image_quality_label = st.selectbox(
                        "Formato de imagen",
                        [
                            "PNG · máxima calidad",
                            "JPG grande · menos espacio",
                        ],
                        index=(
                            0
                            if base["image_quality"] == "png"
                            else 1
                        ),
                        key=f"deck_image_quality_{deck_position}",
                    )
                    image_quality = (
                        "png"
                        if image_quality_label.startswith("PNG")
                        else "large"
                    )

                    include_sideboard = st.checkbox(
                        "Incluir sideboard",
                        value=base["include_sideboard"],
                        key=f"deck_sideboard_{deck_position}",
                    )
                    include_maybeboard = st.checkbox(
                        "Incluir maybeboard",
                        value=base["include_maybeboard"],
                        key=f"deck_maybeboard_{deck_position}",
                    )

                st.info(
                    "Este mazo se analizará con: "
                    f"{'MPCFill' if preferred_image_source == 'mpcfill' else 'Scryfall'} "
                    f"· {'español' if preferred_language == 'es' else 'inglés'}."
                )

            deck_configs.append(
                normalise_deck_config(
                    {
                        "decklist": decklist,
                        "preferred_image_source": preferred_image_source,
                        "preferred_language": preferred_language,
                        "allow_language_fallback": allow_language_fallback,
                        "resolution_mode": resolution_mode,
                        "quality_mode": quality_mode,
                        "image_quality": image_quality,
                        "include_sideboard": include_sideboard,
                        "include_maybeboard": include_maybeboard,
                    }
                )
            )

    analysis_submitted = st.button(
        "Analizar mazo" if deck_count == 1 else "Analizar mazos",
        type="primary",
        width="stretch",
    )
    analysis_config = {"decks": deck_configs}
else:
    analysis_config = saved_config
    deck_configs = deck_configs_from_analysis_config(analysis_config)
    deck_count = len(deck_configs)


def current_signature() -> str:
    payload = {
        "engine_version": ANALYSIS_ENGINE_VERSION,
        "decks": deck_configs,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_decks() -> MultiDeckResult:
    return parse_deck_configurations(deck_configs)


def stored_deck_summaries() -> list[dict[str, Any]]:
    return list(st.session_state.get("deck_summaries") or [])


def active_deck_position() -> int:
    summaries = stored_deck_summaries()
    if not summaries:
        return 0
    current = int(st.session_state.get("active_review_deck", 0))
    return min(max(current, 0), len(summaries) - 1)


def active_deck_indices() -> list[int]:
    return indices_for_deck(
        active_deck_position(),
        stored_deck_summaries(),
    )


def deck_config_for_position(position: int) -> dict[str, Any]:
    configs = deck_configs_from_analysis_config(
        st.session_state.get("analysis_config") or analysis_config
    )
    if not configs:
        return normalise_deck_config(None)
    position = min(max(position, 0), len(configs) - 1)
    return configs[position]


def deck_config_for_card_index(index: int) -> dict[str, Any]:
    position = deck_position_for_card(
        index,
        stored_deck_summaries(),
    )
    return deck_config_for_position(position)


def image_quality_for_card_index(index: int | None = None) -> str:
    if index is None:
        position = active_deck_position()
    else:
        position = deck_position_for_card(
            index,
            stored_deck_summaries(),
        )
    return str(
        deck_config_for_position(position).get(
            "image_quality",
            "png",
        )
    )


def set_active_deck(position: int) -> None:
    summaries = stored_deck_summaries()
    if not summaries:
        return
    position = min(max(position, 0), len(summaries) - 1)
    st.session_state["active_review_deck"] = position
    indices = indices_for_deck(position, summaries)
    if indices:
        set_review_index(indices[0])
    st.session_state.pop("review_only_problematic", None)
    st.session_state["workspace_mode"] = "Vista del mazo"
    st.session_state["workspace_selector_version"] = (
        st.session_state.get("workspace_selector_version", 0) + 1
    )


def clear_generated_output() -> None:
    for key in (
        "output_data",
        "output_name",
        "output_mime",
        "report",
        "pdf_output_download",
        "pdf_output_signature",
    ):
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


def prefetch_selection(
    selection: ResolvedCard,
    index: int | None = None,
) -> None:
    if not selection.faces:
        return
    try:
        with ScryfallClient(
            cache_dir(),
            image_quality=image_quality_for_card_index(index),
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
    prefetch_selection(updated, index)
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
    prefetch_selection(card, index)
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
                image_quality=image_quality_for_card_index(indices[0]),
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
                    prefetch_selection(cards[index], index)
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
                        prefetch_selection(cards[index], index)
                    progress.progress(position / len(indices))

        elif action == "Unificar por nombre con la primera selección":
            template = cards[indices[0]]
            for position, index in enumerate(indices, start=1):
                if cards[index].source.name.casefold() == template.source.name.casefold():
                    cards[index] = clone_selection_for_card(template, cards[index])
                    prefetch_selection(cards[index], index)
                progress.progress(position / len(indices))

        st.session_state["resolved_cards"] = cards
        clear_generated_output()
        status.success(f"Acción aplicada a {len(indices)} entradas.")
    except (ScryfallError, MpcFillError, OSError, AllocationError) as exc:
        status.error(str(exc))


if app_step == 1 and analysis_submitted:
    clear_generated_output()
    try:
        multi_deck_result = load_decks()
        cards = multi_deck_result.cards
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
        deck_analysis_stats: list[dict[str, Any]] = []
        temporary_failures = 0
        processed_entries = 0
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

        for deck_position, summary in enumerate(
            multi_deck_result.summaries
        ):
            config = deck_configs[deck_position]
            deck_cards = cards[
                summary.start_index:summary.end_index
            ]
            deck_number = deck_position + 1
            deck_total = len(deck_cards)
            provider = config["preferred_image_source"]
            deck_failures = 0
            deck_stat: dict[str, Any] = {
                "index": deck_number,
                "name": summary.name,
                "provider": provider,
                "preferred_language": config["preferred_language"],
                "entries": deck_total,
                "copies": summary.copies,
                "resolved": 0,
                "failures": 0,
            }

            status.write(
                (
                    "Consultando MPCFill en lote · "
                    if provider == "mpcfill"
                    else "Analizando con Scryfall · "
                )
                + f"**Mazo {deck_number}/{multi_deck_result.deck_count}: "
                f"{summary.name}** · "
                f"{'MPCFill' if provider == 'mpcfill' else 'Scryfall'} · "
                f"{'español' if config['preferred_language'] == 'es' else 'inglés'}"
            )

            if provider == "mpcfill":
                try:
                    with MpcFillClient(mpc_cache_dir()) as client:
                        deck_resolved = client.resolve_many_auto(
                            deck_cards,
                            preferred_language=config[
                                "preferred_language"
                            ],
                            allow_language_fallback=config[
                                "allow_language_fallback"
                            ],
                            resolution_mode=config[
                                "resolution_mode"
                            ],
                            quality_mode=config["quality_mode"],
                            preferred_sources=DEFAULT_PREFERRED_SOURCES,
                        )
                        mpc_stats = dict(client.last_batch_stats)

                    deck_stat.update(
                        {
                            "resolved": int(
                                mpc_stats.get("resolved", 0)
                            ),
                            "queries_with_hits": int(
                                mpc_stats.get(
                                    "queries_with_hits",
                                    0,
                                )
                            ),
                            "preferred_creator": int(
                                mpc_stats.get(
                                    "preferred_creator",
                                    0,
                                )
                            ),
                            "search_requests": int(
                                mpc_stats.get(
                                    "search_requests",
                                    0,
                                )
                            ),
                        }
                    )
                    deck_failures = sum(
                        1 for card in deck_resolved if not card.faces
                    )
                except MpcFillError as exc:
                    deck_failures = deck_total
                    deck_resolved = [
                        ResolvedCard(
                            source=card,
                            status="Error de MPCFill",
                            provider="mpcfill",
                            error=str(exc),
                        )
                        for card in deck_cards
                    ]
                    deck_stat["error"] = str(exc)
            else:
                deck_resolved = []
                with ScryfallClient(
                    cache_dir(),
                    image_quality=config["image_quality"],
                    retry_callback=show_scryfall_retry,
                ) as client:
                    for local_index, card in enumerate(
                        deck_cards,
                        start=1,
                    ):
                        current_card_name["value"] = (
                            f"Mazo {deck_number} · {card.name}"
                        )
                        elapsed = int(
                            time.monotonic() - started_at
                        )
                        status.write(
                            f"Mazo {deck_number}/{multi_deck_result.deck_count} "
                            f"· carta {local_index}/{deck_total} · "
                            f"**{card.name}** · "
                            f"{elapsed // 60}:{elapsed % 60:02d}"
                        )
                        try:
                            resolved = resolve_with_language_fallback(
                                client,
                                card,
                                preferred_language=config[
                                    "preferred_language"
                                ],
                                allow_language_fallback=config[
                                    "allow_language_fallback"
                                ],
                                resolution_mode=config[
                                    "resolution_mode"
                                ],
                                quality_mode=config["quality_mode"],
                            )
                        except ScryfallError as exc:
                            deck_failures += 1
                            resolved = ResolvedCard(
                                source=card,
                                status=(
                                    "Error temporal de Scryfall"
                                ),
                                error=str(exc),
                            )
                        deck_resolved.append(resolved)
                        processed_entries += 1
                        progress.progress(
                            processed_entries / max(len(cards), 1)
                        )

                deck_stat["resolved"] = sum(
                    1 for card in deck_resolved if card.faces
                )

            if provider == "mpcfill":
                processed_entries += deck_total
                progress.progress(
                    processed_entries / max(len(cards), 1)
                )

            deck_resolved = enforce_automatic_mpcfill_crop_list(
                deck_resolved
            )
            resolved_cards.extend(deck_resolved)
            deck_stat["failures"] = deck_failures
            temporary_failures += deck_failures
            deck_analysis_stats.append(deck_stat)

            elapsed = int(time.monotonic() - started_at)
            status.write(
                f"Mazo {deck_number} completado · "
                f"{deck_stat['resolved']}/{deck_total} con imagen · "
                f"{elapsed // 60}:{elapsed % 60:02d}"
            )

        progress.progress(1.0)
        st.session_state["cards"] = cards
        st.session_state["resolved_cards"] = resolved_cards
        st.session_state["deck_summaries"] = (
            serialise_deck_summaries(
                multi_deck_result,
                deck_configs,
            )
        )
        st.session_state["multi_deck_stats"] = {
            "deck_count": multi_deck_result.deck_count,
            "separate_sheet_count": (
                multi_deck_result.separate_sheet_count
            ),
            "combined_sheet_count": (
                multi_deck_result.combined_usage.sheet_count
            ),
            "combined_empty_slots": (
                multi_deck_result.combined_usage.empty_slots
            ),
            "saved_sheets": multi_deck_result.saved_sheets,
            "saved_paid_slots": multi_deck_result.saved_paid_slots,
        }
        st.session_state["analysis_config"] = analysis_config
        st.session_state["analysis_signature"] = requested_signature
        st.session_state["deck_analysis_stats"] = deck_analysis_stats
        st.session_state["alternatives"] = {}
        st.session_state["mpc_alternatives"] = {}
        st.session_state["active_review_deck"] = 0
        st.session_state["reviewed_decks"] = []
        st.session_state["review_selected_index"] = 0
        st.session_state["review_selector_version"] = 0
        st.session_state["workspace_mode"] = "Vista del mazo"
        st.session_state["workspace_selector_version"] = 0
        st.session_state.pop("review_only_problematic", None)
        st.session_state["app_step"] = 2
        if temporary_failures:
            st.session_state["flash_message"] = (
                f"Análisis completado mazo por mazo: "
                f"{multi_deck_result.deck_count} "
                f"{'mazo' if multi_deck_result.deck_count == 1 else 'mazos'}, "
                f"{len(cards)} entradas y {total_copies} copias. "
                f"{temporary_failures} entradas requieren revisión."
            )
        else:
            st.session_state["flash_message"] = (
                f"Análisis completado mazo por mazo: "
                f"{multi_deck_result.deck_count} "
                f"{'mazo' if multi_deck_result.deck_count == 1 else 'mazos'}, "
                f"{len(cards)} entradas y {total_copies} copias."
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
        width="stretch",
    ):
        st.session_state["app_step"] = 2
        st.rerun()


def render_bulk_panel(filtered: list[int]) -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    deck_position = active_deck_position()
    with st.expander("⚙️ Edición masiva de este mazo", expanded=False):
        selected_indices = st.multiselect(
            "Cartas afectadas",
            options=filtered,
            format_func=lambda index: (
                f"{cards[index].source.quantity}× {cards[index].source.name} — "
                f"{gallery_status_label(cards[index])}"
            ),
            key=f"bulk_selected_indices_{deck_position}",
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
            key=f"bulk_action_{deck_position}",
        )
        st.caption(
            "La acción solo afecta al mazo activo. Nunca modifica cartas "
            "de los demás mazos. Los diseños MPCFill se recortan "
            "automáticamente."
        )
        if st.button(
            "Aplicar acción masiva al mazo actual",
            type="primary",
            width="stretch",
            key=f"bulk_apply_{deck_position}",
        ):
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
                            width="stretch",
                        ):
                            open_card_editor(index)
                            st.rerun(scope="fragment")
        st.divider()


def render_deck_gallery() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    summaries = stored_deck_summaries()
    deck_position = active_deck_position()
    summary = summaries[deck_position]
    deck_indices = indices_for_deck(deck_position, summaries)
    deck_cards = [cards[index] for index in deck_indices]
    config = deck_config_for_position(deck_position)

    st.subheader(
        f"2. Mazo {deck_position + 1} de {len(summaries)} · "
        f"{summary['name']}"
    )
    st.caption(
        f"Ajustes de este mazo: {deck_settings_label(config)}. "
        "La galería, los filtros y las acciones masivas están aislados "
        "del resto de mazos."
    )

    analysis_stats = list(
        st.session_state.get("deck_analysis_stats") or []
    )
    if deck_position < len(analysis_stats):
        stats = analysis_stats[deck_position]
        provider_label = (
            "MPCFill"
            if stats.get("provider") == "mpcfill"
            else "Scryfall"
        )
        details = (
            f"{provider_label}: {stats.get('resolved', 0)}/"
            f"{stats.get('entries', len(deck_cards))} entradas con imagen"
        )
        if stats.get("provider") == "mpcfill":
            details += (
                f" · {stats.get('queries_with_hits', 0)} consultas "
                f"con resultados · {stats.get('preferred_creator', 0)} "
                "de autores preferidos"
            )
        st.info(details)

    with ScryfallClient(
        cache_dir(),
        image_quality=config["image_quality"],
    ) as cache_client:
        cached, total_cache = cache_stats(deck_cards, cache_client)

    problem_count = sum(is_problematic(card) for card in deck_cards)
    multiple_count = sum(
        card_has_multiple_arts(card) for card in deck_cards
    )
    metrics = st.columns(5)
    metrics[0].metric(
        "Copias",
        sum(card.source.quantity for card in deck_cards),
    )
    metrics[1].metric("Entradas", len(deck_cards))
    metrics[2].metric("Pendientes", problem_count)
    metrics[3].metric("Varios artes", multiple_count)
    metrics[4].metric("Caché", f"{cached}/{total_cache}")

    filter_cols = st.columns([2.4, 1, 1.2, 1, 1.1])
    with filter_cols[0]:
        query = st.text_input(
            "Buscar",
            placeholder="Nombre de carta",
            key=f"gallery_query_{deck_position}",
        )
    with filter_cols[1]:
        provider = st.selectbox(
            "Fuente",
            ["Todos", "Scryfall", "MPCFill"],
            key=f"gallery_provider_{deck_position}",
        )
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
            key=f"gallery_state_{deck_position}",
        )
    with filter_cols[3]:
        language = st.selectbox(
            "Idioma",
            ["Todos", "es", "en"],
            key=f"gallery_language_{deck_position}",
        )
    with filter_cols[4]:
        sorting = st.selectbox(
            "Orden",
            ["Categoría", "Nombre", "Cantidad"],
            key=f"gallery_sort_{deck_position}",
        )

    local_indices = filtered_indices(
        deck_cards,
        query=query,
        provider=provider,
        state=state,
        language=language,
    )
    indices = [deck_indices[index] for index in local_indices]
    if sorting == "Nombre":
        indices.sort(
            key=lambda index: cards[index].source.name.casefold()
        )
    elif sorting == "Cantidad":
        indices.sort(
            key=lambda index: -cards[index].source.quantity
        )

    render_bulk_panel(indices)
    if not indices:
        st.info("No hay cartas de este mazo que coincidan con los filtros.")
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
                "Estas cartas necesitan revisión y pertenecen "
                "únicamente al mazo activo.",
                problematic_indices,
                cards,
                mpc_client,
            )
        else:
            st.success("Este mazo no tiene cartas con problemas.")

        if healthy_indices:
            with st.expander(
                f"Ver {len(healthy_indices)} cartas correctas de este mazo",
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
        if st.button("Guardar ajuste de recorte", width="stretch"):
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
                    width="stretch",
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
        if st.button("Guardar reparto", width="stretch"):
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
                width="stretch",
            ):
                save_replacement(index, replacement, advance_indices=review_indices)
                st.rerun(scope="fragment")
        with add_mix:
            if st.button(
                "Añadir al reparto",
                key=f"mix_{key}",
                width="stretch",
            ):
                save_replacement(index, replacement, add_to_mix=True)
                st.success("Ilustración añadida al reparto con una copia.")
                st.rerun(scope="fragment")
    else:
        if st.button(
            "Elegir y continuar",
            key=f"one_{key}",
            width="stretch",
        ):
            save_replacement(index, replacement, advance_indices=review_indices)
            st.rerun(scope="fragment")


def render_review_panel() -> None:
    cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    summaries = stored_deck_summaries()
    deck_position = active_deck_position()
    summary = summaries[deck_position]
    deck_indices = indices_for_deck(deck_position, summaries)
    problem_indices = [
        index for index in deck_indices
        if is_problematic(cards[index])
    ]

    back_col, title_col = st.columns([1, 4])
    with back_col:
        if st.button("← Volver al mazo", width="stretch"):
            set_workspace_mode("Vista del mazo")
            st.rerun(scope="fragment")
    with title_col:
        st.subheader(
            f"Editar versiones · Mazo {deck_position + 1}: "
            f"{summary['name']}"
        )

    with st.expander("Ver tabla completa", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    review_row(index, cards[index])
                    for index in deck_indices
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    only_problematic = st.checkbox(
        "Mostrar solo cartas problemáticas",
        value=bool(problem_indices),
        key="review_only_problematic",
    )
    review_indices = (
        problem_indices if only_problematic else deck_indices
    )
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
    deck_config = deck_config_for_card_index(selected_index)
    preferred_image_source = deck_config["preferred_image_source"]
    preferred_language = deck_config["preferred_language"]
    allow_language_fallback = deck_config[
        "allow_language_fallback"
    ]
    resolution_mode = deck_config["resolution_mode"]
    quality_mode = deck_config["quality_mode"]
    image_quality = deck_config["image_quality"]

    position = review_indices.index(selected_index)
    st.progress(
        (position + 1) / len(review_indices),
        text=f"Carta {position + 1} de {len(review_indices)}",
    )

    nav = st.columns([1, 2, 1])
    with nav[0]:
        if st.button("← Anterior", disabled=position == 0, width="stretch"):
            set_review_index(previous_index(review_indices, selected_index))
            st.rerun(scope="fragment")
    with nav[1]:
        if st.button(
            "Mantener actual y continuar",
            disabled=position == len(review_indices) - 1,
            width="stretch",
        ):
            set_review_index(next_index(review_indices, selected_index))
            st.rerun(scope="fragment")
    with nav[2]:
        if st.button(
            "Siguiente →",
            disabled=position == len(review_indices) - 1,
            width="stretch",
        ):
            set_review_index(next_index(review_indices, selected_index))
            st.rerun(scope="fragment")

    selected = cards[selected_index]
    st.caption(
        "Solo estás editando cartas de este mazo. Las selecciones de "
        "los demás mazos permanecen intactas."
    )
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
                            image_quality=image_quality,
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
                            image_quality=image_quality,
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
                    width="stretch",
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
                    if selected.source.set_code:
                        designs = sorted(
                            designs,
                            key=lambda candidate: (
                                0
                                if mpc_candidate_mentions_set_code(
                                    candidate,
                                    selected.source.set_code,
                                )
                                else 1,
                                -int(candidate.get("dpi") or 0),
                            ),
                        )
                    if not designs:
                        st.info(
                            "MPCFill no encontró diseños con esos filtros."
                        )
                    elif selected.source.set_code:
                        st.caption(
                            "Se muestran primero los diseños cuyo nombre o "
                            "archivo parece incluir el set code "
                            f"\"{selected.source.set_code.upper()}\"."
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
                            width="stretch",
                        ):
                            st.session_state[visible_key] = (
                                visible_limit + 12
                            )
                            st.rerun(scope="fragment")
            except MpcFillError as exc:
                st.warning(f"MPCFill no está disponible: {exc}")


def mark_active_deck_reviewed() -> None:
    reviewed = {
        int(value)
        for value in st.session_state.get("reviewed_decks", [])
    }
    reviewed.add(active_deck_position())
    st.session_state["reviewed_decks"] = sorted(reviewed)


def render_deck_review_navigation(
    *,
    location: str,
    show_selector: bool,
) -> None:
    summaries = stored_deck_summaries()
    position = active_deck_position()
    total = len(summaries)
    reviewed = {
        int(value)
        for value in st.session_state.get("reviewed_decks", [])
    }

    if show_selector:
        st.progress(
            (position + 1) / max(total, 1),
            text=f"Revisión del mazo {position + 1} de {total}",
        )
        selector_version = st.session_state.get(
            "active_deck_selector_version",
            0,
        )
        selected_position = st.selectbox(
            "Mazo en revisión",
            options=list(range(total)),
            index=position,
            format_func=lambda item: (
                f"{'✅ ' if item in reviewed else ''}"
                f"{item + 1}. {summaries[item]['name']} · "
                f"{deck_settings_label(deck_config_for_position(item))}"
            ),
            key=f"active_deck_selector_{location}_{selector_version}",
        )
        if selected_position != position:
            set_active_deck(selected_position)
            st.session_state["active_deck_selector_version"] = (
                selector_version + 1
            )
            st.rerun()

    columns = st.columns([1, 1.4, 1.4])
    with columns[0]:
        if st.button(
            "← Lista y opciones",
            key=f"step2_back_{location}",
            width="stretch",
        ):
            st.session_state["app_step"] = 1
            st.rerun()

    with columns[1]:
        if st.button(
            "← Mazo anterior",
            key=f"previous_deck_{location}",
            disabled=position == 0,
            width="stretch",
        ):
            mark_active_deck_reviewed()
            set_active_deck(position - 1)
            st.rerun()

    with columns[2]:
        if position < total - 1:
            if st.button(
                "Marcar revisado y abrir siguiente →",
                key=f"next_deck_{location}",
                type="primary",
                width="stretch",
            ):
                mark_active_deck_reviewed()
                set_active_deck(position + 1)
                st.rerun()
        else:
            if st.button(
                "Finalizar revisión y exportar →",
                key=f"export_after_review_{location}",
                type="primary",
                width="stretch",
            ):
                mark_active_deck_reviewed()
                st.session_state["app_step"] = 3
                st.rerun()




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

    deck_summaries = list(
        st.session_state.get("deck_summaries") or []
    )
    multi_deck_stats = dict(
        st.session_state.get("multi_deck_stats") or {}
    )
    deck_count = max(len(deck_summaries), 1)

    validation = validate_deck(
        cards,
        back_spec=back_spec,
        warn_duplicates=deck_count == 1,
    )
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

    if deck_count > 1:
        st.info(
            f"{deck_count} mazos se imprimirán uno detrás de otro, "
            "sin saltos de hoja entre ellos."
        )
        with st.expander("Mazos incluidos y orden de impresión", expanded=False):
            for summary in deck_summaries:
                st.write(
                    f"**{summary['index']}. {summary['name']}** — "
                    f"{summary['copies']} cartas · "
                    f"{deck_settings_label(summary.get('settings', {}))} · "
                    f"{summary['sheet_count']} hojas por separado"
                )

        saved_sheets = int(multi_deck_stats.get("saved_sheets", 0))
        saved_slots = int(multi_deck_stats.get("saved_paid_slots", 0))
        if saved_sheets:
            st.success(
                f"Al combinarlos se "
                f"{'ahorra' if saved_sheets == 1 else 'ahorran'} "
                f"{saved_sheets} "
                f"{'hoja' if saved_sheets == 1 else 'hojas'} "
                f"({saved_slots} posiciones pagadas) frente a generar "
                "un PDF independiente para cada mazo."
            )
        else:
            st.caption(
                "En esta combinación no se reduce el número total de hojas, "
                "pero tampoco se añaden huecos entre mazos."
            )

    sheet_usage = calculate_sheet_usage(validation.expected_cards)
    if sheet_usage.is_full:
        st.success(
            f"Aprovechamiento completo: {sheet_usage.card_count} cartas "
            f"ocupan {sheet_usage.sheet_count} hojas de "
            f"{sheet_usage.slots_per_sheet}, sin huecos pagados."
        )
    else:
        st.warning(
            f"La última hoja tendrá {sheet_usage.empty_slots} "
            f"{'hueco' if sheet_usage.empty_slots == 1 else 'huecos'} "
            f"en blanco: {sheet_usage.card_count} cartas ocupan "
            f"{sheet_usage.sheet_count} hojas "
            f"({sheet_usage.total_slots} posiciones pagadas). "
            f"Puedes añadir {sheet_usage.cards_to_complete} "
            f"{'carta' if sheet_usage.cards_to_complete == 1 else 'cartas'} "
            "para completar la última hoja."
        )
        st.caption(
            "Los huecos se colocan únicamente al final de la última hoja; "
            "nunca se intercalan entre las cartas."
        )

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
        split_large_pdf = st.checkbox(
            "Dividir automáticamente si supera 200 MB",
            value=True,
            help=(
                "Crea varios PDFs manteniendo juntas las parejas de "
                "páginas 1/1B, 2/2B, etc."
            ),
        )

    pdf_file_name = multi_deck_pdf_filename(
        [summary["name"] for summary in deck_summaries],
        cards,
    )
    pdf_image_quality = deck_config_for_position(0)[
        "image_quality"
    ]
    pdf_output_signature = hashlib.sha256(
        json.dumps(
            {
                "analysis_signature": st.session_state.get(
                    "analysis_signature",
                    "",
                ),
                "file_name": pdf_file_name,
                "cut_lines": cut_lines,
                "cut_line_style": cut_line_style,
                "cut_line_width": cut_line_width,
                "cut_line_color": cut_line_color,
                "cut_line_over_cards": cut_line_over_cards,
                "printer_marks": printer_marks,
                "include_backs": include_backs,
                "image_quality": pdf_image_quality,
                "split_large_pdf": split_large_pdf,
                "split_limit_bytes": PDF_SPLIT_LIMIT_BYTES,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    if (
        st.session_state.get("pdf_output_signature")
        != pdf_output_signature
    ):
        for key in (
            "pdf_output_download",
            "pdf_output_signature",
        ):
            st.session_state.pop(key, None)

    if not st.session_state.get("pdf_output_download"):
        pdf_requested = st.button(
            "Generar PDF",
            type="primary",
            width="stretch",
            disabled=generation_disabled,
        )

        if pdf_requested:
            progress = st.progress(0.0)
            status = st.empty()
            started_at = time.monotonic()

            def update_pdf_progress(event: PdfProgress) -> None:
                elapsed = int(time.monotonic() - started_at)
                phase_labels = {
                    "front": "Preparando frente",
                    "back": "Preparando reverso",
                    "common_back": "Preparando reverso común",
                    "page": "Montando página",
                    "finalizing": "Finalizando el PDF",
                    "done": "PDF preparado",
                }
                phase_label = phase_labels.get(
                    event.phase,
                    "Generando PDF",
                )
                detail = (
                    f"{event.phase_current}/{event.phase_total}"
                    if event.phase_total
                    else ""
                )
                page_detail = (
                    f" · página {event.page_label}"
                    if event.page_label
                    else ""
                )
                card_detail = (
                    f" · **{event.label}**"
                    if event.label and event.label != "PDF"
                    else ""
                )
                status.write(
                    f"{phase_label} {detail}{page_detail}{card_detail} · "
                    f"{elapsed // 60}:{elapsed % 60:02d}"
                )
                progress.progress(
                    min(event.current / max(event.total, 1), 1.0)
                )

            try:
                with ScryfallClient(
                    cache_dir(),
                    image_quality=pdf_image_quality,
                ) as client:
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

                if split_large_pdf:
                    pdf_parts = split_pdf_if_needed(
                        result.data,
                        pdf_file_name,
                        max_bytes=PDF_SPLIT_LIMIT_BYTES,
                        preserve_page_pairs=include_backs,
                    )
                else:
                    pdf_parts = [
                        PdfPart(
                            data=result.data,
                            file_name=pdf_file_name,
                        )
                    ]

                if len(pdf_parts) == 1:
                    download_data = pdf_parts[0].data
                    download_name = pdf_parts[0].file_name
                    download_mime = "application/pdf"
                    download_label = "Descargar PDF"
                else:
                    download_data = build_pdf_parts_zip(pdf_parts)
                    download_name = (
                        f"{Path(pdf_file_name).stem} - partes.zip"
                    )
                    download_mime = "application/zip"
                    download_label = "Descargar todas las partes"

                progress.progress(1.0)
                st.session_state["pdf_output_download"] = {
                    "data": download_data,
                    "file_name": download_name,
                    "mime": download_mime,
                    "label": download_label,
                    "part_count": len(pdf_parts),
                    "part_names": [
                        part.file_name for part in pdf_parts
                    ],
                    "part_sizes": [
                        len(part.data) for part in pdf_parts
                    ],
                    "exceeds_limit": any(
                        part.exceeds_limit for part in pdf_parts
                    ),
                }
                st.session_state[
                    "pdf_output_signature"
                ] = pdf_output_signature
                st.rerun()
            except (ScryfallError, OSError, ValueError) as exc:
                status.error(str(exc))

        st.caption(
            "Primero se genera el PDF y se descargan las imágenes "
            "necesarias. Al terminar aparecerá el botón de descarga."
        )
    else:
        pdf_download = st.session_state["pdf_output_download"]
        st.download_button(
            pdf_download["label"],
            data=pdf_download["data"],
            file_name=pdf_download["file_name"],
            mime=pdf_download["mime"],
            type="primary",
            width="stretch",
            on_click="ignore",
        )

        if pdf_download["part_count"] == 1:
            st.caption(
                f"PDF preparado: `{pdf_download['file_name']}` · "
                f"{format_file_size(len(pdf_download['data']))}"
            )
        else:
            st.success(
                f"El PDF superaba 200 MB y se ha dividido en "
                f"{pdf_download['part_count']} partes. Todas están "
                "incluidas en un único archivo ZIP."
            )
            with st.expander("Ver partes incluidas", expanded=False):
                for name, size in zip(
                    pdf_download["part_names"],
                    pdf_download["part_sizes"],
                ):
                    st.caption(
                        f"`{name}` · {format_file_size(size)}"
                    )

        if pdf_download["exceeds_limit"]:
            st.warning(
                "Una pareja de páginas supera por sí sola los 200 MB. "
                "Se ha mantenido unida para no separar el frente de su "
                "reverso."
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
                width="stretch",
                disabled=generation_disabled,
            )
        with other_columns[1]:
            mpc_requested = st.button(
                "Generar paquete MPC / dúplex",
                width="stretch",
                disabled=generation_disabled,
            )

    requested_format: str | None = None
    if images_requested:
        requested_format = "images"
    elif mpc_requested:
        requested_format = "mpc"

    if requested_format:
        progress = st.progress(0.0)
        status = st.empty()
        try:
            with ScryfallClient(
                cache_dir(),
                image_quality=deck_config_for_position(0)[
                    "image_quality"
                ],
            ) as client:
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
            "Descargar ZIP preparado",
            data=st.session_state["output_data"],
            file_name=st.session_state["output_name"],
            mime=st.session_state["output_mime"],
            type="primary",
            width="stretch",
        )
        report = st.session_state.get("report") or []
        if report:
            with st.expander("Informe final", expanded=False):
                st.dataframe(
                    pd.DataFrame(report),
                    width="stretch",
                    hide_index=True,
                )


if app_step == 2 and signature_matches:
    render_deck_review_navigation(
        location="top",
        show_selector=True,
    )
    st.caption(
        "Cada mazo conserva su propia configuración y sus propias "
        "correcciones. Cambiar de mazo no modifica el resto."
    )
    render_workspace()
    render_deck_review_navigation(
        location="bottom",
        show_selector=False,
    )

elif app_step == 3 and signature_matches:
    navigation = st.columns([1, 3])
    with navigation[0]:
        if st.button(
            "← Volver a revisar",
            width="stretch",
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
