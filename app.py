from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from mtg_downloader.archive import build_zip
from mtg_downloader.decklist import parse_exported_decklist
from mtg_downloader.models import DeckCard
from mtg_downloader.moxfield import MoxfieldError, fetch_deck, parse_deck
from mtg_downloader.profiles import PROFILES, get_profile
from mtg_downloader.scryfall import ScryfallClient, ScryfallError

st.set_page_config(
    page_title="Moxfield Cartas ES",
    page_icon="🃏",
    layout="wide",
)

st.title("🃏 Moxfield Cartas ES")
st.write(
    "Pega un enlace público de Moxfield y descarga todas las copias del mazo "
    "priorizando imágenes oficiales en español y de buena calidad."
)

with st.expander("Cómo funciona", expanded=False):
    st.markdown(
        """
1. Se intenta leer el mazo desde Moxfield.
2. El perfil elegido decide cómo combinar edición, idioma y calidad.
3. Cada copia del listado genera su propio archivo.
4. Las cartas de doble cara generan una imagen por cada cara y copia.
5. Se crea un ZIP con las imágenes y un `informe.csv`.

El formato PNG evita compresión adicional, pero no arregla un escaneo de origen
pobre. La aplicación consulta los indicadores de calidad de Scryfall para evitar
imágenes `lowres` cuando el perfil lo permita.

Moxfield puede bloquear las consultas automáticas. En ese caso, exporta el mazo
como texto y pégalo en el campo de respaldo.
"""
    )

left, right = st.columns([3, 2])

with left:
    moxfield_url = st.text_input(
        "Enlace público de Moxfield",
        placeholder="https://www.moxfield.com/decks/xxxxxxxxxxxxxxxxxxxxxx",
    )
    fallback_text = st.text_area(
        "Exportación de texto de respaldo (opcional)",
        height=180,
        placeholder=(
            "Commander:\n1 Mi comandante (SET) 123\n\n"
            "Deck:\n1 Sol Ring (CMM) 396\n8 Mountain (M20) 279"
        ),
        help="También puedes utilizar la aplicación únicamente con una lista pegada.",
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
            help=(
                "Actívalo solo si necesitas controlar por separado la edición, "
                "el idioma y la aceptación de imágenes low-res."
            ),
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
                "español e inglés"
                if allow_english
                else "solo español"
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


def load_cards() -> tuple[str, list[DeckCard], str]:
    link_error: str | None = None

    if moxfield_url.strip():
        try:
            deck_data = fetch_deck(moxfield_url)
            name, cards = parse_deck(
                deck_data,
                include_sideboard=include_sideboard,
                include_maybeboard=include_maybeboard,
            )
            return name, cards, "Moxfield"
        except (MoxfieldError, ValueError) as exc:
            link_error = str(exc)

    if fallback_text.strip():
        cards = parse_exported_decklist(fallback_text)
        if not include_sideboard:
            cards = [card for card in cards if card.zone != "sideboard"]
        if not include_maybeboard:
            cards = [card for card in cards if card.zone != "maybeboard"]
        if not cards:
            raise ValueError(
                "No se ha podido interpretar ninguna carta de la lista pegada."
            )

        source_message = "Lista pegada"
        if link_error:
            source_message += f" — la lectura del enlace falló: {link_error}"
        return "Mazo exportado", cards, source_message

    if link_error:
        raise ValueError(link_error)
    raise ValueError("Introduce un enlace de Moxfield o pega una lista.")


if st.button("Preparar ZIP", type="primary", use_container_width=True):
    st.session_state.pop("zip_data", None)
    st.session_state.pop("zip_name", None)
    st.session_state.pop("report", None)

    try:
        deck_name, cards, source = load_cards()
        total_copies = sum(card.quantity for card in cards)
        st.info(
            f"Origen: {source}. Se han detectado {len(cards)} cartas distintas "
            f"y {total_copies} contando copias."
        )

        progress = st.progress(0.0)
        status = st.empty()
        resolved = []

        cache_dir = Path(tempfile.gettempdir()) / "moxfield_cartas_es_cache"
        with ScryfallClient(cache_dir, image_quality=image_quality) as client:
            for index, card in enumerate(cards, start=1):
                status.write(
                    f"Buscando {index}/{len(cards)}: **{card.name}**"
                )
                resolved.append(
                    client.resolve(
                        card,
                        allow_english_fallback=allow_english,
                        resolution_mode=resolution_mode,
                        quality_mode=quality_mode,
                    )
                )
                progress.progress(index / max(len(cards), 1) * 0.65)

            def update_zip(current: int, total: int, name: str) -> None:
                status.write(
                    f"Añadiendo imágenes {current}/{total}: **{name}**"
                )
                progress.progress(
                    0.65 + (current / max(total, 1) * 0.35)
                )

            zip_data, report = build_zip(
                resolved,
                client,
                duplicate_copies=True,
                progress_callback=update_zip,
            )

        progress.progress(1.0)
        status.success("ZIP preparado correctamente.")

        safe_name = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in deck_name
        ).strip("_")

        st.session_state["zip_data"] = zip_data
        st.session_state["zip_name"] = (
            f"{safe_name or 'mazo'}_cartas_es.zip"
        )
        st.session_state["report"] = report

    except (ValueError, MoxfieldError, ScryfallError, OSError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Se produjo un error inesperado: {exc}")


if st.session_state.get("report") is not None:
    report = st.session_state["report"]

    st.subheader("Resultado")
    st.caption(
        "El informe indica la edición elegida, el idioma y el estado de calidad "
        "de cada imagen."
    )
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
