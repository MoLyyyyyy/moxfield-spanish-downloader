from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from mtg_downloader.archive import build_zip
from mtg_downloader.decklist import parse_exported_decklist
from mtg_downloader.models import DeckCard, ResolvedCard
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

if signature_matches:
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

    st.subheader("2. Revisar impresiones")
    st.caption(
        "La selección automática ya está aplicada. Se consideran problemáticas "
        "las cartas sin imagen, low-res o que cambiaron de edición. El idioma no "
        "genera una revisión por sí solo."
    )

    summary1, summary2, summary3 = st.columns(3)
    summary1.metric("Entradas analizadas", len(resolved_cards))
    summary2.metric("Para revisar", len(problematic_indices))
    summary3.metric(
        "Copias físicas",
        sum(card.source.quantity for card in resolved_cards),
    )

    st.dataframe(
        pd.DataFrame(review_rows),
        use_container_width=True,
        hide_index=True,
    )

    only_problematic = st.checkbox(
        "Mostrar solo cartas problemáticas",
        value=bool(problematic_indices),
    )
    review_indices = (
        problematic_indices
        if only_problematic
        else list(range(len(resolved_cards)))
    )

    if not review_indices:
        st.success(
            "No hay cartas problemáticas con los criterios actuales. "
            "Desmarca el filtro para revisar cualquier impresión."
        )
    else:
        selected_index = st.selectbox(
            "Carta a revisar",
            options=review_indices,
            format_func=lambda index: (
                f"{resolved_cards[index].source.quantity}x "
                f"{resolved_cards[index].source.name} — "
                f"{resolved_cards[index].status}"
            ),
        )
        selected = resolved_cards[selected_index]

        preview_col, details_col = st.columns([1, 2])
        with preview_col:
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
                    st.image(url, caption=caption, width=210)
            else:
                st.warning("La selección actual no tiene imagen.")

        with details_col:
            st.markdown(f"### {selected.source.name}")
            st.write(
                f"**Cantidad:** {selected.source.quantity}  \n"
                f"**Solicitada:** "
                f"{(selected.source.set_code or '?').upper()} "
                f"{selected.source.collector_number or '?'}  \n"
                f"**Elegida:** {(selected.selected_set or '?').upper()} "
                f"{selected.collector_number or '?'}  \n"
                f"**Idioma:** {(selected.language or '?').upper()}  \n"
                f"**Calidad:** {selected.image_status or 'desconocida'}  \n"
                f"**Estado:** {selected.status}"
            )
            reasons = problem_reasons(selected)
            if reasons:
                st.warning("Motivos de revisión: " + ", ".join(reasons))
            else:
                st.success("La selección automática no presenta incidencias.")

        st.markdown("#### Buscar otras versiones")
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

        if st.button(
            "Buscar impresiones alternativas",
            use_container_width=True,
            key=f"search_alternatives_{selected_index}",
        ):
            try:
                with ScryfallClient(
                    cache_dir(),
                    image_quality=st.session_state["analysis_image_quality"],
                ) as client:
                    alternatives = client.search_alternatives(
                        selected.source.name,
                        languages=languages,
                        highres_only=only_highres_alternatives,
                        max_results=alternatives_limit,
                    )
                st.session_state.setdefault("alternatives", {})[
                    alternatives_state_key
                ] = alternatives
            except (ScryfallError, OSError) as exc:
                st.error(str(exc))

        alternatives = st.session_state.get("alternatives", {}).get(
            alternatives_state_key,
            [],
        )

        if alternatives:
            st.caption(
                "Selecciona una miniatura para sustituir la impresión actual. "
                "La cantidad de copias no cambia."
            )
            columns = st.columns(4)
            for alternative_index, candidate in enumerate(alternatives):
                column = columns[alternative_index % 4]
                with column:
                    urls = preview_urls(candidate)
                    if urls:
                        st.image(urls[0], width=145)
                    st.caption(candidate_label(candidate))
                    if len(urls) > 1:
                        st.caption(f"Carta de {len(urls)} caras.")

                    if st.button(
                        "Elegir esta versión",
                        key=(
                            f"choose_{selected_index}_"
                            f"{candidate_key(candidate)}"
                        ),
                        use_container_width=True,
                    ):
                        try:
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
                            updated = list(st.session_state["resolved_cards"])
                            updated[selected_index] = replacement
                            st.session_state["resolved_cards"] = updated
                            clear_generated_zip()
                            st.rerun()
                        except (ScryfallError, OSError) as exc:
                            st.error(str(exc))

        elif alternatives_state_key in st.session_state.get(
            "alternatives",
            {},
        ):
            st.warning(
                "No se han encontrado alternativas con esos filtros. "
                "Prueba a incluir inglés o permitir imágenes que no estén "
                "marcadas como alta resolución."
            )

    st.subheader("3. Generar ZIP")
    st.caption(
        "Se utilizarán las selecciones automáticas y manuales que aparecen "
        "en la tabla de revisión."
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
