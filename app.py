from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from mtg_downloader.archive import build_zip
from mtg_downloader.deck_view import (
    gallery_printing_label,
    group_deck,
)
from mtg_downloader.decklist import parse_exported_decklist
from mtg_downloader.image_processing import (
    CROP_AUTO,
    CROP_FORCE,
    CROP_NONE,
)
from mtg_downloader.models import DeckCard, ResolvedCard
from mtg_downloader.mpcfill import (
    MpcFillClient,
    MpcFillError,
    mpc_candidate_key,
    mpc_candidate_label,
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

st.set_page_config(
    page_title="Moxfield Cartas ES",
    page_icon="🃏",
    layout="wide",
)

st.title("🃏 Moxfield Cartas ES")
st.write(
    "Pega la exportación de tu mazo, revisa las impresiones seleccionadas "
    "y descarga todas sus cartas."
)

with st.expander("Cómo obtener la lista", expanded=False):
    st.markdown(
        """
1. Abre el mazo en Moxfield.
2. Utiliza la opción de exportar o copiar la lista como texto.
3. Pega el contenido en la aplicación.
4. Pulsa **Analizar mazo**.
5. Revisa las cartas problemáticas y cambia manualmente cualquier impresión.
6. Genera el ZIP definitivo.

Ejemplo válido:

```text
Commander:
1 Beorn the Fierce (HOB) 119 *F*

Deck:
1 Arcane Signet (TMC) 57
27 Forest (M20) 279
```

Cada copia del listado genera su propio archivo. Las cartas de doble cara
generan una imagen por cada cara y copia.
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
        help=(
            "Se respetan cantidad, edición y número de coleccionista cuando "
            "aparecen en la lista."
        ),
    )

with right:
    st.subheader("Opciones")

    profile_key = st.selectbox(
        "Perfil de descarga",
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
            "Formato del archivo",
            [
                "PNG — máxima calidad (recomendado)",
                "JPG grande — archivos más pequeños",
            ],
            index=0,
        )
        image_quality = (
            "png" if image_quality_label.startswith("PNG") else "large"
        )

        custom_rules = st.checkbox(
            "Personalizar las reglas del perfil",
            value=False,
        )

        if custom_rules:
            resolution_label = st.selectbox(
                "Prioridad de impresión",
                [
                    "Exacta primero — respeta edición si puede",
                    "Solo exacta — no cambia de edición",
                    "Flexible — ignora edición",
                ],
                index={
                    "exact_first": 0,
                    "exact_only": 1,
                    "flexible": 2,
                }[resolution_mode],
            )
            resolution_mode = {
                "Exacta primero — respeta edición si puede": "exact_first",
                "Solo exacta — no cambia de edición": "exact_only",
                "Flexible — ignora edición": "flexible",
            }[resolution_label]

            scan_quality_label = st.selectbox(
                "Calidad mínima del escaneo",
                [
                    "Preferir alta resolución — low-res como último recurso",
                    "Aceptar low-res — respetar estrictamente la prioridad",
                    "Solo alta resolución — omitir low-res",
                ],
                index={
                    "prefer_highres": 0,
                    "allow_lowres": 1,
                    "highres_only": 2,
                }[quality_mode],
            )
            quality_mode = {
                "Preferir alta resolución — low-res como último recurso": "prefer_highres",
                "Aceptar low-res — respetar estrictamente la prioridad": "allow_lowres",
                "Solo alta resolución — omitir low-res": "highres_only",
            }[scan_quality_label]

            allow_english = st.checkbox(
                "Permitir inglés como respaldo",
                value=allow_english,
            )
        else:
            language_summary = (
                "español e inglés" if allow_english else "solo español"
            )
            st.caption(
                f"Reglas activas: `{resolution_mode}` · `{quality_mode}` · "
                f"{language_summary}."
            )

    st.info(
        "Las cantidades se respetan siempre: 8 Montañas generan 8 archivos."
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
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
            "No se ha podido interpretar ninguna carta. Comprueba que cada "
            "línea empiece por una cantidad, por ejemplo: "
            "`1 Arcane Signet (TMC) 57`."
        )

    return cards


def clear_generated_zip() -> None:
    for key in ("zip_data", "zip_name", "report"):
        st.session_state.pop(key, None)


def cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "moxfield_cartas_es_cache"


def mpc_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "moxfield_cartas_es_mpcfill_cache"


def previous_review_index(
    review_indices: list[int],
    current_index: int,
) -> int:
    if not review_indices:
        return current_index
    try:
        position = review_indices.index(current_index)
    except ValueError:
        return review_indices[0]
    if position > 0:
        return review_indices[position - 1]
    return review_indices[0]


def next_review_index(review_indices: list[int], current_index: int) -> int:
    if not review_indices:
        return current_index
    try:
        position = review_indices.index(current_index)
    except ValueError:
        return review_indices[0]
    if position + 1 < len(review_indices):
        return review_indices[position + 1]
    return review_indices[-1]


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
    if (
        card.provider == "mpcfill"
        and isinstance(card.scryfall_data, dict)
        and mpc_client is not None
    ):
        try:
            return mpc_client.preview_bytes(
                card.scryfall_data,
                crop_mode=(
                    card.faces[0].crop_mode
                    if card.faces and card.faces[0].crop_mode
                    else CROP_AUTO
                ),
            )
        except MpcFillError:
            return None

    urls = preview_urls(card.scryfall_data)
    if urls:
        return urls[0]
    if card.faces:
        return card.faces[0].url
    return None


def render_deck_gallery() -> None:
    resolved_cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    categories = group_deck(resolved_cards)
    problematic_count = sum(
        1 for card in resolved_cards if is_problematic(card)
    )

    st.subheader("2. Vista del mazo")
    st.caption(
        "Previsualización de las versiones seleccionadas agrupada por tipo. "
        "Cada entrada aparece una sola vez con su cantidad, igual que en un "
        "constructor de mazos."
    )

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric(
        "Cartas",
        sum(card.source.quantity for card in resolved_cards),
    )
    metric2.metric("Entradas", len(resolved_cards))
    metric3.metric("Pendientes de revisión", problematic_count)

    mpc_client: MpcFillClient | None = None
    if any(card.provider == "mpcfill" for card in resolved_cards):
        mpc_client = MpcFillClient(mpc_cache_dir())

    try:
        for category in categories:
            st.markdown(
                f"### {category.label} "
                f"<small>({category.quantity})</small>",
                unsafe_allow_html=True,
            )

            category_cards = list(category.cards)
            for row_start in range(0, len(category_cards), 6):
                columns = st.columns(6)
                row = category_cards[row_start : row_start + 6]

                for column, (index, card) in zip(columns, row):
                    with column:
                        with st.container(border=True):
                            preview = gallery_preview(card, mpc_client)
                            if preview is not None:
                                left_space, image_column, right_space = (
                                    st.columns([1, 4, 1])
                                )
                                with image_column:
                                    st.image(preview, width=105)
                            else:
                                st.caption("🖼️ Sin imagen disponible")

                            warning_prefix = (
                                "⚠️ " if is_problematic(card) else ""
                            )
                            st.markdown(
                                f"**{warning_prefix}"
                                f"{card.source.quantity}× "
                                f"{card.source.name}**"
                            )
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
        if mpc_client is not None:
            mpc_client.close()


st.subheader("1. Analizar")

if st.button("Analizar mazo", type="primary", use_container_width=True):
    clear_generated_zip()
    try:
        cards = load_cards()
        total_copies = sum(card.quantity for card in cards)
        progress = st.progress(0.0)
        status = st.empty()
        resolved_cards: list[ResolvedCard] = []

        with ScryfallClient(cache_dir(), image_quality=image_quality) as client:
            for index, card in enumerate(cards, start=1):
                status.write(
                    f"Buscando {index}/{len(cards)}: **{card.name}**"
                )
                resolved_cards.append(
                    client.resolve(
                        card,
                        allow_english_fallback=allow_english,
                        resolution_mode=resolution_mode,
                        quality_mode=quality_mode,
                    )
                )
                progress.progress(index / max(len(cards), 1))

        st.session_state["cards"] = cards
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
        st.session_state.pop("review_flash_message", None)
        progress.progress(1.0)
        status.success(
            f"Análisis completado: {len(cards)} entradas y "
            f"{total_copies} cartas contando copias."
        )

    except (ValueError, ScryfallError, OSError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Se produjo un error inesperado: {exc}")


analysis_ready = bool(st.session_state.get("resolved_cards"))
signature_matches = (
    analysis_ready
    and st.session_state.get("analysis_signature") == current_signature()
)

if analysis_ready and not signature_matches:
    st.warning(
        "La lista o las opciones han cambiado desde el último análisis. "
        "Pulsa **Analizar mazo** de nuevo antes de revisar o generar el ZIP."
    )

def render_review_panel() -> None:
    resolved_cards: list[ResolvedCard] = st.session_state["resolved_cards"]
    review_rows = [
        review_row(index, card)
        for index, card in enumerate(resolved_cards)
    ]
    problematic_indices = [
        index
        for index, card in enumerate(resolved_cards)
        if is_problematic(card)
    ]

    back_col, title_col = st.columns([1, 4])
    with back_col:
        if st.button(
            "← Volver al mazo",
            use_container_width=True,
            key="back_to_deck_gallery",
        ):
            set_workspace_mode("Vista del mazo")
            st.rerun(scope="fragment")
    with title_col:
        st.subheader("3. Editar versiones")
    st.caption(
        "Esta zona se actualiza de forma independiente. Se consideran "
        "problemáticas las cartas sin imagen, low-res o que cambiaron de "
        "edición. El idioma no genera una revisión por sí solo."
    )

    flash_message = st.session_state.pop("review_flash_message", None)
    if flash_message:
        st.success(flash_message)

    summary1, summary2, summary3 = st.columns(3)
    summary1.metric("Entradas analizadas", len(resolved_cards))
    summary2.metric("Para revisar", len(problematic_indices))
    summary3.metric(
        "Copias físicas",
        sum(card.source.quantity for card in resolved_cards),
    )

    with st.expander("Ver tabla completa del análisis", expanded=False):
        st.dataframe(
            pd.DataFrame(review_rows),
            use_container_width=True,
            hide_index=True,
        )

    only_problematic = st.checkbox(
        "Mostrar solo cartas problemáticas",
        value=bool(problematic_indices),
        key="review_only_problematic",
    )
    review_indices = (
        problematic_indices
        if only_problematic
        else list(range(len(resolved_cards)))
    )

    if not review_indices:
        st.success(
            "No quedan cartas problemáticas con los criterios actuales. "
            "Desmarca el filtro para revisar cualquier impresión."
        )
        return

    current_review_index = st.session_state.get(
        "review_selected_index",
        review_indices[0],
    )
    if current_review_index not in review_indices:
        current_review_index = review_indices[0]
        st.session_state["review_selected_index"] = current_review_index

    selector_version = st.session_state.get("review_selector_version", 0)
    selected_index = st.selectbox(
        "Carta a revisar",
        options=review_indices,
        index=review_indices.index(current_review_index),
        format_func=lambda index: (
            f"{resolved_cards[index].source.quantity}x "
            f"{resolved_cards[index].source.name} — "
            f"{resolved_cards[index].status}"
        ),
        key=f"review_selector_{selector_version}",
    )
    st.session_state["review_selected_index"] = selected_index

    current_position = review_indices.index(selected_index)
    st.progress(
        (current_position + 1) / len(review_indices),
        text=(
            f"Carta {current_position + 1} de {len(review_indices)} "
            f"en esta revisión"
        ),
    )

    nav_left, nav_keep, nav_right = st.columns([1, 2, 1])
    with nav_left:
        if st.button(
            "← Anterior",
            disabled=current_position == 0,
            use_container_width=True,
            key=f"previous_card_{selector_version}",
        ):
            set_review_index(
                previous_review_index(review_indices, selected_index)
            )
            st.rerun(scope="fragment")

    with nav_keep:
        if st.button(
            "Mantener actual y continuar",
            disabled=current_position == len(review_indices) - 1,
            use_container_width=True,
            key=f"keep_and_continue_{selector_version}",
        ):
            set_review_index(
                next_review_index(review_indices, selected_index)
            )
            st.rerun(scope="fragment")

    with nav_right:
        if st.button(
            "Siguiente →",
            disabled=current_position == len(review_indices) - 1,
            use_container_width=True,
            key=f"next_card_{selector_version}",
        ):
            set_review_index(
                next_review_index(review_indices, selected_index)
            )
            st.rerun(scope="fragment")

    selected = resolved_cards[selected_index]

    top_left, top_right = st.columns([1, 2])

    with top_left:
        st.markdown("#### Versión seleccionada")
        if (
            selected.provider == "mpcfill"
            and isinstance(selected.scryfall_data, dict)
        ):
            try:
                with MpcFillClient(mpc_cache_dir()) as mpc_client:
                    selected_preview = mpc_client.preview_bytes(
                        selected.scryfall_data,
                        crop_mode=(
                            selected.faces[0].crop_mode
                            if selected.faces
                            and selected.faces[0].crop_mode
                            else CROP_AUTO
                        ),
                    )
                spacer_left, image_col, spacer_right = st.columns([1, 2, 1])
                with image_col:
                    st.image(
                        selected_preview,
                        caption="Diseño MPCFill seleccionado",
                        width=210,
                    )
            except MpcFillError as exc:
                st.warning(str(exc))
        else:
            current_urls = preview_urls(selected.scryfall_data)
            if not current_urls:
                current_urls = [face.url for face in selected.faces]
            if current_urls:
                for face_number, url in enumerate(current_urls, start=1):
                    caption = (
                        "Versión seleccionada"
                        if len(current_urls) == 1
                        else f"Versión seleccionada · cara {face_number}"
                    )
                    spacer_left, image_col, spacer_right = st.columns([1, 2, 1])
                    with image_col:
                        st.image(url, caption=caption, width=210)
            else:
                st.warning("La selección actual no tiene imagen.")

        st.markdown("##### Detalles")
        st.caption(
            f"**Carta:** {selected.source.name}  \n"
            f"**Cantidad:** {selected.source.quantity}  \n"
            f"**Solicitada:** "
            f"{(selected.source.set_code or '?').upper()} "
            f"{selected.source.collector_number or '?'}  \n"
            f"**Elegida:** {(selected.selected_set or '?').upper()} "
            f"{selected.collector_number or '?'}  \n"
            f"**Fuente:** "
            f"{'MPCFill' if selected.provider == 'mpcfill' else 'Scryfall'}  \n"
            f"**Idioma:** {(selected.language or '?').upper()}  \n"
            f"**Calidad:** {selected.image_status or 'desconocida'}  \n"
            f"**Recorte:** "
            f"{selected.faces[0].crop_mode if selected.faces and selected.faces[0].crop_mode else 'no aplica'}  \n"
            f"**Estado:** {selected.status}"
        )
        reasons = problem_reasons(selected)
        if reasons:
            st.warning("Revisar: " + ", ".join(reasons))
        else:
            st.success("Selección correcta.")


    with top_right:
        st.markdown("#### Otras versiones")
        version_source = st.radio(
            "Fuente de versiones",
            ["Oficiales · Scryfall", "Comunidad · MPCFill"],
            horizontal=True,
            key=f"version_source_{selected_index}",
        )

        if version_source == "Oficiales · Scryfall":
            st.caption(
                "Impresiones oficiales disponibles en Scryfall. "
                "Puedes filtrarlas por idioma, resolución y cantidad."
            )
            alt_col1, alt_col2, alt_col3 = st.columns([2, 2, 1])
            with alt_col1:
                include_english_alternatives = st.checkbox(
                    "Incluir versiones en inglés",
                    value=True,
                    key=f"alt_english_{selected_index}",
                )
            with alt_col2:
                only_highres_alternatives = st.checkbox(
                    "Mostrar solo alta resolución",
                    value=True,
                    key=f"alt_highres_{selected_index}",
                )
            with alt_col3:
                alternatives_limit = st.selectbox(
                    "Máximo",
                    [6, 9, 12, 18],
                    index=2,
                    key=f"alt_limit_{selected_index}",
                )

            languages = (
                ("es", "en")
                if include_english_alternatives
                else ("es",)
            )
            alternatives_state_key = (
                f"{selected_index}|{','.join(languages)}|"
                f"{only_highres_alternatives}|{alternatives_limit}"
            )

            alternatives_cache = st.session_state.setdefault(
                "alternatives",
                {},
            )
            if alternatives_state_key not in alternatives_cache:
                try:
                    with st.spinner("Cargando impresiones oficiales..."):
                        with ScryfallClient(
                            cache_dir(),
                            image_quality=st.session_state[
                                "analysis_image_quality"
                            ],
                        ) as client:
                            alternatives_cache[alternatives_state_key] = (
                                client.search_alternatives(
                                    selected.source.name,
                                    languages=languages,
                                    highres_only=only_highres_alternatives,
                                    max_results=alternatives_limit,
                                )
                            )
                except (ScryfallError, OSError) as exc:
                    st.error(str(exc))
                    alternatives_cache[alternatives_state_key] = []

            alternatives = alternatives_cache.get(
                alternatives_state_key,
                [],
            )

            if alternatives:
                st.caption(
                    "Elige una miniatura para guardar esa impresión y avanzar "
                    "automáticamente a la siguiente carta."
                )
                columns = st.columns(3)
                for alternative_index, candidate in enumerate(alternatives):
                    column = columns[alternative_index % 3]
                    with column:
                        with st.container(border=True):
                            urls = preview_urls(candidate)
                            if urls:
                                img_left, img_center, img_right = st.columns(
                                    [1, 2, 1]
                                )
                                with img_center:
                                    st.image(urls[0], width=135)
                            st.caption(candidate_label(candidate))
                            if len(urls) > 1:
                                st.caption(f"Carta de {len(urls)} caras.")

                            if st.button(
                                "Elegir y continuar",
                                key=(
                                    f"choose_scryfall_{selected_index}_"
                                    f"{candidate_key(candidate)}"
                                ),
                                use_container_width=True,
                            ):
                                try:
                                    target_index = next_review_index(
                                        review_indices,
                                        selected_index,
                                    )
                                    with ScryfallClient(
                                        cache_dir(),
                                        image_quality=st.session_state[
                                            "analysis_image_quality"
                                        ],
                                    ) as client:
                                        replacement = (
                                            client.resolve_from_candidate(
                                                selected.source,
                                                candidate,
                                                status="Selección manual",
                                            )
                                        )

                                    updated = list(
                                        st.session_state["resolved_cards"]
                                    )
                                    updated[selected_index] = replacement
                                    st.session_state["resolved_cards"] = updated
                                    set_review_index(target_index)
                                    st.session_state[
                                        "review_flash_message"
                                    ] = (
                                        f"Impresión oficial guardada para "
                                        f"{selected.source.name}."
                                    )
                                    clear_generated_zip()
                                    st.rerun(scope="fragment")
                                except (ScryfallError, OSError) as exc:
                                    st.error(str(exc))
            else:
                st.warning(
                    "No se han encontrado impresiones oficiales con esos "
                    "filtros."
                )

        else:
            st.caption(
                "Diseños comunitarios de MPCFill. La previsualización ya "
                "muestra cómo quedará la imagen después de eliminar el sangrado."
            )

            mpc_col1, mpc_col2, mpc_col3, mpc_col4 = st.columns(
                [1.4, 1.4, 1.7, 1]
            )
            with mpc_col1:
                mpc_language_label = st.selectbox(
                    "Idioma",
                    ["Todos", "Español", "Inglés"],
                    key=f"mpc_language_{selected_index}",
                )
            with mpc_col2:
                minimum_dpi = st.selectbox(
                    "DPI mínimo",
                    [300, 600, 800, 1200],
                    index=0,
                    key=f"mpc_dpi_{selected_index}",
                )
            with mpc_col3:
                crop_mode_label = st.selectbox(
                    "Recorte",
                    [
                        "Automático · recomendado",
                        "Mantener sangrado",
                        "Forzar recorte MPC",
                    ],
                    key=f"mpc_crop_{selected_index}",
                )
            with mpc_col4:
                mpc_limit = st.selectbox(
                    "Máximo",
                    [6, 9, 12],
                    index=1,
                    key=f"mpc_limit_{selected_index}",
                )

            mpc_languages = {
                "Todos": (),
                "Español": ("ES",),
                "Inglés": ("EN",),
            }[mpc_language_label]
            crop_mode = {
                "Automático · recomendado": CROP_AUTO,
                "Mantener sangrado": CROP_NONE,
                "Forzar recorte MPC": CROP_FORCE,
            }[crop_mode_label]

            mpc_state_key = (
                f"{selected_index}|{','.join(mpc_languages) or 'all'}|"
                f"{minimum_dpi}|{mpc_limit}"
            )
            mpc_cache = st.session_state.setdefault(
                "mpc_alternatives",
                {},
            )

            try:
                with MpcFillClient(mpc_cache_dir()) as mpc_client:
                    if mpc_state_key not in mpc_cache:
                        with st.spinner(
                            "Buscando diseños comunitarios en MPCFill..."
                        ):
                            mpc_cache[mpc_state_key] = (
                                mpc_client.search_designs(
                                    selected.source.name,
                                    languages=mpc_languages,
                                    minimum_dpi=minimum_dpi,
                                    max_results=mpc_limit,
                                )
                            )

                    mpc_designs = mpc_cache.get(mpc_state_key, [])

                    if mpc_designs:
                        st.caption(
                            "Las miniaturas están recortadas con el modo "
                            "seleccionado. El archivo del ZIP usará exactamente "
                            "el mismo recorte."
                        )
                        columns = st.columns(3)
                        for design_index, candidate in enumerate(mpc_designs):
                            column = columns[design_index % 3]
                            with column:
                                with st.container(border=True):
                                    preview_error = None
                                    try:
                                        preview_data = mpc_client.preview_bytes(
                                            candidate,
                                            crop_mode=crop_mode,
                                        )
                                    except MpcFillError as exc:
                                        preview_data = None
                                        preview_error = str(exc)

                                    if preview_data:
                                        img_left, img_center, img_right = (
                                            st.columns([1, 2, 1])
                                        )
                                        with img_center:
                                            st.image(
                                                preview_data,
                                                width=135,
                                            )
                                    elif preview_error:
                                        st.warning(preview_error)

                                    st.caption(
                                        mpc_candidate_label(candidate)
                                    )
                                    source_link = candidate.get(
                                        "sourceExternalLink"
                                    )
                                    if isinstance(source_link, str) and source_link:
                                        st.link_button(
                                            "Ver fuente",
                                            source_link,
                                            use_container_width=True,
                                        )

                                    if st.button(
                                        "Elegir y continuar",
                                        key=(
                                            f"choose_mpc_{selected_index}_"
                                            f"{mpc_candidate_key(candidate)}_"
                                            f"{crop_mode}"
                                        ),
                                        use_container_width=True,
                                    ):
                                        target_index = next_review_index(
                                            review_indices,
                                            selected_index,
                                        )
                                        replacement = (
                                            mpc_client.resolve_candidate(
                                                selected.source,
                                                candidate,
                                                crop_mode=crop_mode,
                                                type_line=selected.type_line,
                                            )
                                        )

                                        updated = list(
                                            st.session_state["resolved_cards"]
                                        )
                                        updated[selected_index] = replacement
                                        st.session_state[
                                            "resolved_cards"
                                        ] = updated
                                        set_review_index(target_index)
                                        st.session_state[
                                            "review_flash_message"
                                        ] = (
                                            f"Diseño MPCFill guardado para "
                                            f"{selected.source.name}."
                                        )
                                        clear_generated_zip()
                                        st.rerun(scope="fragment")
                    else:
                        st.warning(
                            "MPCFill no ha encontrado diseños con esos filtros."
                        )

            except MpcFillError as exc:
                st.warning(
                    f"MPCFill no está disponible ahora mismo: {exc}"
                )
                st.caption(
                    "Puedes seguir usando las versiones oficiales de Scryfall "
                    "sin que este error afecte al resto del mazo."
                )

@st.fragment
def render_deck_workspace() -> None:
    options = ["Vista del mazo", "Editar cartas"]
    current_mode = st.session_state.get("workspace_mode", options[0])
    if current_mode not in options:
        current_mode = options[0]

    selector_version = st.session_state.get(
        "workspace_selector_version",
        0,
    )
    mode = st.radio(
        "Modo de trabajo",
        options,
        index=options.index(current_mode),
        horizontal=True,
        key=f"workspace_selector_{selector_version}",
    )
    st.session_state["workspace_mode"] = mode

    if mode == "Vista del mazo":
        render_deck_gallery()
    else:
        render_review_panel()


if signature_matches:
    render_deck_workspace()

    st.subheader("4. Generar ZIP")
    st.caption(
        "Se utilizarán las selecciones automáticas y manuales guardadas "
        "durante la revisión."
    )

    if st.button(
        "Generar ZIP con la selección actual",
        type="primary",
        use_container_width=True,
    ):
        try:
            progress = st.progress(0.0)
            status = st.empty()

            def update_zip(current: int, total: int, name: str) -> None:
                status.write(
                    f"Añadiendo imágenes {current}/{total}: **{name}**"
                )
                progress.progress(current / max(total, 1))

            with ScryfallClient(
                cache_dir(),
                image_quality=st.session_state["analysis_image_quality"],
            ) as client:
                zip_data, report = build_zip(
                    st.session_state["resolved_cards"],
                    client,
                    duplicate_copies=True,
                    progress_callback=update_zip,
                )

            progress.progress(1.0)
            status.success("ZIP preparado correctamente.")
            st.session_state["zip_data"] = zip_data
            st.session_state["zip_name"] = "mazo_cartas_es.zip"
            st.session_state["report"] = report

        except (ScryfallError, OSError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Se produjo un error inesperado: {exc}")


if st.session_state.get("report") is not None:
    report = st.session_state["report"]

    st.subheader("Resultado final")
    st.dataframe(
        pd.DataFrame(report),
        use_container_width=True,
        hide_index=True,
    )

    spanish = sum(1 for row in report if row["idioma"] == "es")
    english = sum(1 for row in report if row["idioma"] == "en")
    lowres = sum(1 for row in report if row["estado_imagen"] == "lowres")
    missing = sum(
        1
        for row in report
        if row["estado"] in {
            "No encontrada",
            "Sin imagen",
            "Sin alta resolución",
            "Sin impresión exacta",
        }
    )

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("En español", spanish)
    metric2.metric("En inglés", english)
    metric3.metric("Low-res utilizadas", lowres)
    metric4.metric("Sin imagen", missing)

    st.download_button(
        "Descargar ZIP",
        data=st.session_state["zip_data"],
        file_name=st.session_state["zip_name"],
        mime="application/zip",
        type="primary",
        use_container_width=True,
    )

st.divider()
st.caption(
    "Herramienta no oficial para uso personal. Las imágenes y marcas de "
    "Magic: The Gathering pertenecen a sus respectivos titulares."
)
