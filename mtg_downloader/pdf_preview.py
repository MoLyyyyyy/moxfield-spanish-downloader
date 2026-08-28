"""Bounded raster previews of generated PDFs, independent of print output."""
from contextlib import closing
from io import BytesIO
import threading
from zipfile import BadZipFile, ZipFile

import pypdfium2 as pdfium

# PDFium calls must not run concurrently across Streamlit sessions.
_pdfium_lock = threading.RLock()


def preview_pdf_bytes(data: bytes, mime: str, part_name: str | None) -> bytes:
    if mime == "application/pdf":
        return data
    if mime != "application/zip" or not part_name:
        raise ValueError("Selecciona una parte PDF válida.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            return archive.read(part_name)
    except (BadZipFile, KeyError) as exc:
        raise ValueError("No se pudo leer la parte seleccionada.") from exc


def pdf_page_count(data: bytes) -> int:
    try:
        with _pdfium_lock, pdfium.PdfDocument(data) as document:
            return len(document)
    except pdfium.PdfiumError as exc:
        raise ValueError("No se pudo abrir el PDF para la vista previa.") from exc


def render_pdf_page(data: bytes, page_index: int) -> bytes:
    try:
        with _pdfium_lock, pdfium.PdfDocument(data) as document:
            if not 0 <= page_index < len(document):
                raise ValueError("Página fuera del documento.")
            with closing(document[page_index]) as page:
                longest = max(page.get_size())
                if longest <= 0:
                    raise ValueError("La página no tiene dimensiones válidas.")
                with closing(page.render(scale=min(1.0, 1000 / longest))) as bitmap:
                    with bitmap.to_pil() as image:
                        output = BytesIO()
                        image.save(output, format="PNG")
                        return output.getvalue()
    except pdfium.PdfiumError as exc:
        raise ValueError("No se pudo renderizar la vista previa.") from exc
