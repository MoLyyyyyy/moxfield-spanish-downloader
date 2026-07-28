from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from mtg_downloader.pdf_split import (
    PdfPart,
    build_pdf_parts_zip,
    format_file_size,
    split_pdf_if_needed,
)


def make_pdf(page_count: int) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    for page in range(1, page_count + 1):
        document.setFont("Helvetica", 28)
        document.drawString(72, 760, f"Page {page}")
        document.showPage()
    document.save()
    return output.getvalue()


def serialised_pages(data: bytes, indices: list[int]) -> bytes:
    reader = PdfReader(BytesIO(data))
    writer = PdfWriter()
    for index in indices:
        writer.add_page(reader.pages[index])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_below_limit_is_not_split() -> None:
    data = make_pdf(2)
    parts = split_pdf_if_needed(
        data,
        "Commander.pdf",
        max_bytes=len(data) + 100,
    )

    assert parts == [PdfPart(data=data, file_name="Commander.pdf")]


def test_split_preserves_front_back_page_pairs() -> None:
    data = make_pdf(6)
    one_pair_size = len(serialised_pages(data, [0, 1]))
    two_pair_size = len(serialised_pages(data, [0, 1, 2, 3]))
    threshold = (one_pair_size + two_pair_size) // 2

    parts = split_pdf_if_needed(
        data,
        "Commander.pdf",
        max_bytes=threshold,
        preserve_page_pairs=True,
    )

    assert len(parts) == 3
    assert [
        len(PdfReader(BytesIO(part.data)).pages)
        for part in parts
    ] == [2, 2, 2]
    assert parts[0].file_name == "Commander - parte 1 de 3.pdf"
    assert parts[2].file_name == "Commander - parte 3 de 3.pdf"
    assert not any(part.exceeds_limit for part in parts)


def test_single_page_pair_can_be_reported_as_oversized() -> None:
    data = make_pdf(2)
    parts = split_pdf_if_needed(
        data,
        "Commander.pdf",
        max_bytes=100,
        preserve_page_pairs=True,
    )

    assert len(parts) == 1
    assert parts[0].exceeds_limit


def test_file_size_formatting() -> None:
    assert format_file_size(1024) == "1.0 KB"
    assert format_file_size(2 * 1024 * 1024) == "2.0 MB"



def test_pdf_parts_can_be_downloaded_as_one_zip() -> None:
    import zipfile

    parts = [
        PdfPart(data=b"first", file_name="Deck - parte 1 de 2.pdf"),
        PdfPart(data=b"second", file_name="Deck - parte 2 de 2.pdf"),
    ]

    data = build_pdf_parts_zip(parts)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        assert archive.namelist() == [
            "Deck - parte 1 de 2.pdf",
            "Deck - parte 2 de 2.pdf",
        ]
        assert archive.read("Deck - parte 1 de 2.pdf") == b"first"
        assert archive.read("Deck - parte 2 de 2.pdf") == b"second"


def test_split_prefers_a_deck_boundary_before_size_overflow() -> None:
    data = make_pdf(12)  # six duplex page pairs
    four_pairs_size = len(serialised_pages(data, list(range(8))))
    five_pairs_size = len(serialised_pages(data, list(range(10))))
    threshold = (four_pairs_size + five_pairs_size) // 2

    parts = split_pdf_if_needed(
        data,
        "Commander.pdf",
        max_bytes=threshold,
        preserve_page_pairs=True,
        preferred_group_breaks={4},
    )

    page_counts = [
        len(PdfReader(BytesIO(part.data)).pages)
        for part in parts
    ]
    assert page_counts[0] == 8
    assert sum(page_counts) == 12
