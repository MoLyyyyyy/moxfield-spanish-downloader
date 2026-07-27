from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Callable

from .models import ResolvedCard
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
) -> tuple[bytes, list[dict[str, str | int]]]:
    output = io.BytesIO()
    report: list[dict[str, str | int]] = []
    sequence = 1
    total = len(resolved_cards)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, resolved in enumerate(resolved_cards, start=1):
            source = resolved.source
            if progress_callback:
                progress_callback(index, total, source.name)

            row: dict[str, str | int] = {
                "zona": source.zone,
                "cantidad": source.quantity,
                "nombre_moxfield": source.name,
                "edicion_moxfield": source.set_code or "",
                "numero_moxfield": source.collector_number or "",
                "estado": resolved.status,
                "idioma": resolved.language or "",
                "nombre_impreso": resolved.printed_name or "",
                "edicion_elegida": resolved.selected_set or "",
                "numero_elegido": resolved.collector_number or "",
                "formato_descarga": resolved.downloaded_format or "",
                "estado_imagen": resolved.image_status or "",
                "alta_resolucion": (
                    "sí" if resolved.highres_image is True
                    else "no" if resolved.highres_image is False
                    else ""
                ),
                "error": resolved.error or "",
            }
            report.append(row)

            if not resolved.faces:
                continue

            folder = _ZONE_LABELS.get(source.zone, _safe_filename(source.zone))
            copies = source.quantity if duplicate_copies else 1
            quantity_label = "" if duplicate_copies else f"_{source.quantity}x"

            downloaded_faces: list[tuple[bytes, str, str]] = []
            for face_index, face in enumerate(resolved.faces, start=1):
                data = client.download_image(face)
                suffix = "" if len(resolved.faces) == 1 else f"_cara-{face_index}"
                downloaded_faces.append((data, face.extension, suffix))

            for copy_number in range(1, copies + 1):
                copy_suffix = f"_copia-{copy_number:02d}" if copies > 1 else ""
                base_name = _safe_filename(resolved.printed_name or source.name)
                printing = ""
                if resolved.selected_set:
                    printing = (
                        f"_{resolved.selected_set.upper()}-"
                        f"{resolved.collector_number or ''}"
                    )
                for data, extension, face_suffix in downloaded_faces:
                    filename = (
                        f"{folder}/{sequence:03d}_{base_name}{printing}"
                        f"{quantity_label}{copy_suffix}{face_suffix}{extension}"
                    )
                    archive.writestr(filename, data)
                sequence += 1

        archive.writestr("informe.csv", _report_csv(report))
        archive.writestr("LEEME.txt", _readme_text(report, duplicate_copies))

    return output.getvalue(), report


def _report_csv(report: list[dict[str, str | int]]) -> bytes:
    buffer = io.StringIO(newline="")
    fieldnames = list(report[0].keys()) if report else ["estado"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    writer.writerows(report)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _readme_text(
    report: list[dict[str, str | int]], duplicate_copies: bool
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
        f"Entradas resueltas en español: {spanish}\n"
        f"Entradas usadas en inglés: {english}\n"
        f"Entradas sin imagen: {missing}\n"
        f"Copias separadas: {'sí' if duplicate_copies else 'no'}\n\n"
        "Consulta informe.csv para ver la impresión elegida.\n"
        "Las imágenes y marcas de Magic: The Gathering pertenecen "
        "a sus respectivos titulares.\n"
        "Herramienta no oficial para uso personal.\n"
    )


def _safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized[:120] or "carta"
