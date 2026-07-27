from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import asdict

from .backs import BackSpec, no_back
from .models import CardVariant, ImageFace, ResolvedCard
from .physical import physical_cards
from .selections import effective_variants, variant_key
from .scryfall import ScryfallClient

_ZONE_LABELS = {
    "commanders": "01_Comandantes",
    "partners": "01_Comandantes",
    "companions": "02_Companeros",
    "signatureSpells": "02_Hechizos_distintivos",
    "mainboard": "03_Mazo",
    "sideboard": "04_Sideboard",
    "maybeboard": "05_Maybeboard",
}


def build_zip(
    resolved_cards: list[ResolvedCard],
    client: ScryfallClient,
    *,
    duplicate_copies: bool,
    progress_callback: Callable[[int, int, str], None] | None = None,
    back_spec: BackSpec | None = None,
    include_backs: bool = False,
    naming_mode: str = "category",
    package_mode: str = "images",
) -> tuple[bytes, list[dict[str, str | int]]]:
    if naming_mode not in {"category", "sequence"}:
        raise ValueError("Modo de nombres desconocido.")
    if package_mode not in {"images", "mpc"}:
        raise ValueError("Modo de paquete desconocido.")

    selected_back = back_spec or no_back()
    output = io.BytesIO()
    report = _build_report(resolved_cards)
    cards = physical_cards(resolved_cards)
    total = len(cards)
    variant_cache: dict[str, list[tuple[bytes, str]]] = {}
    back_cache: tuple[bytes, str] | None = None

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if duplicate_copies:
            iterable = cards
        else:
            iterable = _one_physical_per_variant(resolved_cards)

        for current, physical in enumerate(iterable, start=1):
            if progress_callback:
                progress_callback(current, len(iterable), physical.source.name)

            variant = physical.variant
            key = variant_key(variant)
            if key not in variant_cache:
                variant_cache[key] = [
                    (client.download_image(face), face.extension)
                    for face in variant.faces
                ]
            downloaded = variant_cache[key]
            if not downloaded:
                continue

            base_name = _physical_base_name(physical, duplicate_copies)
            if package_mode == "mpc":
                front_folder = "Frentes"
            elif naming_mode == "sequence":
                front_folder = "Cartas"
            else:
                front_folder = _ZONE_LABELS.get(
                    physical.source.zone,
                    _safe_filename(physical.source.zone),
                )

            front_faces = downloaded[:1] if package_mode == "mpc" else downloaded
            for face_index, (data, extension) in enumerate(front_faces, start=1):
                suffix = "" if len(front_faces) == 1 else f"_cara-{face_index}"
                archive.writestr(
                    f"{front_folder}/{base_name}{suffix}{extension}",
                    data,
                )

            if include_backs or package_mode == "mpc":
                back_data: bytes | None = None
                back_extension = ".png"
                if len(downloaded) > 1:
                    back_data, back_extension = downloaded[1]
                elif selected_back.mode != "none":
                    if back_cache is None:
                        back_cache = _download_back(selected_back, client)
                    if back_cache is not None:
                        back_data, back_extension = back_cache
                if back_data is not None:
                    archive.writestr(
                        f"Reversos/{base_name}_reverso{back_extension}",
                        back_data,
                    )

        archive.writestr("informe.csv", _report_csv(report))
        archive.writestr(
            "manifest.csv",
            _manifest_csv(resolved_cards, include_backs or package_mode == "mpc"),
        )
        archive.writestr(
            "LEEME.txt",
            _readme_text(
                report,
                duplicate_copies,
                include_backs=include_backs or package_mode == "mpc",
                back_label=selected_back.label,
                package_mode=package_mode,
            ),
        )

    return output.getvalue(), report


def prefetch_cards(
    resolved_cards: list[ResolvedCard],
    client: ScryfallClient,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[int, int]:
    variants = [variant for card in resolved_cards for variant in effective_variants(card)]
    unique: dict[str, CardVariant] = {variant_key(variant): variant for variant in variants}
    total_faces = sum(len(variant.faces) for variant in unique.values())
    downloaded = 0
    current = 0
    for variant in unique.values():
        for face in variant.faces:
            current += 1
            if progress_callback:
                progress_callback(current, total_faces, variant.printed_name or "Carta")
            if not client.is_face_cached(face):
                client.download_image(face)
                downloaded += 1
    return downloaded, total_faces


def cache_stats(
    resolved_cards: list[ResolvedCard],
    client: ScryfallClient,
) -> tuple[int, int]:
    variants = [variant for card in resolved_cards for variant in effective_variants(card)]
    unique_faces: dict[str, ImageFace] = {}
    for variant in variants:
        for face in variant.faces:
            identity = (
                f"{face.url}|{face.provider}|{face.crop_mode}|"
                f"{face.crop_shift_x}|{face.crop_shift_y}"
            )
            unique_faces[identity] = face
    total = len(unique_faces)
    cached = sum(client.is_face_cached(face) for face in unique_faces.values())
    return cached, total


def _download_back(
    back_spec: BackSpec,
    client: ScryfallClient,
) -> tuple[bytes, str] | None:
    if back_spec.embedded_data is not None:
        return back_spec.embedded_data, back_spec.extension
    if back_spec.face is not None:
        return client.download_image(back_spec.face), back_spec.face.extension
    return None


def _one_physical_per_variant(resolved_cards: list[ResolvedCard]):
    result = []
    for physical in physical_cards(resolved_cards):
        if physical.copy_in_allocation == 1:
            result.append(physical)
    return result


def _physical_base_name(physical, duplicate_copies: bool) -> str:
    variant = physical.variant
    printed = _safe_filename(variant.printed_name or physical.source.name)
    printing = ""
    if variant.selected_set:
        printing = (
            f"_{variant.selected_set.upper()}-"
            f"{variant.collector_number or ''}"
        )
    quantity = "" if duplicate_copies else f"_{variant.quantity}x"
    copy_suffix = (
        f"_copia-{physical.copy_in_allocation:02d}"
        if duplicate_copies and variant.quantity > 1
        else ""
    )
    variant_suffix = (
        f"_arte-{physical.allocation_index:02d}"
        if physical.allocation_index > 1
        else ""
    )
    return (
        f"{physical.sequence:03d}_{printed}{printing}"
        f"{quantity}{variant_suffix}{copy_suffix}"
    )


def _build_report(
    resolved_cards: list[ResolvedCard],
) -> list[dict[str, str | int]]:
    report: list[dict[str, str | int]] = []
    for resolved in resolved_cards:
        for variant_index, variant in enumerate(effective_variants(resolved), start=1):
            source = resolved.source
            report.append(
                {
                    "zona": source.zone,
                    "cantidad": variant.quantity,
                    "variante": variant_index,
                    "nombre_moxfield": source.name,
                    "edicion_moxfield": source.set_code or "",
                    "numero_moxfield": source.collector_number or "",
                    "estado": variant.status,
                    "fuente": variant.provider,
                    "idioma": variant.language or "",
                    "nombre_impreso": variant.printed_name or "",
                    "edicion_elegida": variant.selected_set or "",
                    "numero_elegido": variant.collector_number or "",
                    "formato_descarga": variant.downloaded_format or "",
                    "estado_imagen": variant.image_status or "",
                    "alta_resolucion": (
                        "sí" if variant.highres_image is True
                        else "no" if variant.highres_image is False
                        else ""
                    ),
                    "recorte": (
                        variant.faces[0].crop_mode
                        if variant.faces and variant.faces[0].crop_mode
                        else ""
                    ),
                    "ajuste_x": (
                        variant.faces[0].crop_shift_x if variant.faces else 0
                    ),
                    "ajuste_y": (
                        variant.faces[0].crop_shift_y if variant.faces else 0
                    ),
                    "error": variant.error or "",
                }
            )
    return report


def _report_csv(report: list[dict[str, str | int]]) -> bytes:
    buffer = io.StringIO(newline="")
    fieldnames = list(report[0].keys()) if report else ["estado"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    writer.writerows(report)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _manifest_csv(cards: list[ResolvedCard], include_backs: bool) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "secuencia",
            "carta",
            "cantidad",
            "variante",
            "fuente",
            "frente",
            "reverso",
        ]
    )
    for physical in physical_cards(cards):
        variant = physical.variant
        writer.writerow(
            [
                physical.sequence,
                physical.source.name,
                1,
                physical.allocation_index,
                variant.provider,
                variant.faces[0].url if variant.faces else "",
                (
                    variant.faces[1].url
                    if len(variant.faces) > 1
                    else "configurado" if include_backs else ""
                ),
            ]
        )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _readme_text(
    report: list[dict[str, str | int]],
    duplicate_copies: bool,
    *,
    include_backs: bool,
    back_label: str,
    package_mode: str,
) -> str:
    total_cards = sum(int(row["cantidad"]) for row in report)
    spanish = sum(1 for row in report if row["idioma"] == "es")
    english = sum(1 for row in report if row["idioma"] == "en")
    missing = sum(
        1 for row in report if row["estado"] in {"No encontrada", "Sin imagen"}
    )
    return (
        "Moxfield Cartas ES\n"
        "===================\n\n"
        f"Cartas totales de la lista: {total_cards}\n"
        f"Variantes de impresión: {len(report)}\n"
        f"Entradas resueltas en español: {spanish}\n"
        f"Entradas usadas en inglés: {english}\n"
        f"Entradas sin imagen: {missing}\n"
        f"Copias separadas: {'sí' if duplicate_copies else 'no'}\n"
        f"Reversos: {back_label if include_backs else 'no incluidos'}\n"
        f"Tipo de paquete: {package_mode}\n\n"
        "Consulta informe.csv y manifest.csv para revisar el contenido.\n"
        "Las imágenes y marcas de Magic: The Gathering pertenecen "
        "a sus respectivos titulares.\n"
        "Herramienta no oficial para uso personal.\n"
    )


def _safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized[:120] or "carta"
