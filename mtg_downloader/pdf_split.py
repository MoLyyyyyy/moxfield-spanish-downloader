from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

PDF_SPLIT_LIMIT_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PdfPart:
    data: bytes
    file_name: str
    exceeds_limit: bool = False


def format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def split_pdf_if_needed(
    data: bytes,
    file_name: str,
    *,
    max_bytes: int = PDF_SPLIT_LIMIT_BYTES,
    preserve_page_pairs: bool = True,
) -> list[PdfPart]:
    """Split a PDF into size-limited parts while preserving duplex pairs."""
    if max_bytes < 1:
        raise ValueError("El límite del PDF debe ser mayor que cero.")

    if len(data) <= max_bytes:
        return [PdfPart(data=data, file_name=file_name)]

    reader = PdfReader(io.BytesIO(data))
    page_count = len(reader.pages)
    if page_count == 0:
        return [PdfPart(data=data, file_name=file_name)]

    group_size = 2 if preserve_page_pairs and page_count > 1 else 1
    page_groups = [
        list(range(start, min(start + group_size, page_count)))
        for start in range(0, page_count, group_size)
    ]

    raw_parts: list[tuple[bytes, bool]] = []
    current_pages: list[int] = []
    current_data = b""

    for group in page_groups:
        candidate_pages = current_pages + group
        candidate_data = _write_pages(reader, candidate_pages)

        if current_pages and len(candidate_data) > max_bytes:
            raw_parts.append(
                (current_data, len(current_data) > max_bytes)
            )
            current_pages = list(group)
            current_data = _write_pages(reader, current_pages)
        else:
            current_pages = candidate_pages
            current_data = candidate_data

    if current_pages:
        raw_parts.append((current_data, len(current_data) > max_bytes))

    if len(raw_parts) == 1:
        part_data, exceeds_limit = raw_parts[0]
        return [
            PdfPart(
                data=part_data,
                file_name=file_name,
                exceeds_limit=exceeds_limit,
            )
        ]

    path = Path(file_name)
    suffix = path.suffix or ".pdf"
    stem = path.stem or "proxy-maker"
    total = len(raw_parts)
    return [
        PdfPart(
            data=part_data,
            file_name=f"{stem} - parte {index} de {total}{suffix}",
            exceeds_limit=exceeds_limit,
        )
        for index, (part_data, exceeds_limit) in enumerate(
            raw_parts,
            start=1,
        )
    ]



def build_pdf_parts_zip(parts: list[PdfPart]) -> bytes:
    """Package every generated PDF part into one downloadable ZIP."""
    if not parts:
        raise ValueError("No hay partes PDF para empaquetar.")

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_STORED,
    ) as archive:
        for part in parts:
            archive.writestr(part.file_name, part.data)
    return output.getvalue()


def _write_pages(
    reader: PdfReader,
    page_indices: list[int],
) -> bytes:
    writer = PdfWriter()
    for page_index in page_indices:
        writer.add_page(reader.pages[page_index])

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
