from io import BytesIO

from pypdf import PdfReader

from mtg_downloader.print_map import (
    build_print_map,
    preferred_page_pair_breaks,
    print_map_csv,
    print_map_pdf,
)


def summaries():
    return [
        {"index": 1, "name": "Deck A", "copies": 100},
        {"index": 2, "name": "Deck B", "copies": 8},
        {"index": 3, "name": "Deck C", "copies": 9},
    ]


def test_print_map_tracks_cross_deck_sheet_positions() -> None:
    rows = build_print_map(summaries())

    assert rows[0].start_label == "Hoja 1, posición 1"
    assert rows[0].end_label == "Hoja 12, posición 1"
    assert rows[1].start_label == "Hoja 12, posición 2"
    assert rows[1].end_label == "Hoja 12, posición 9"
    assert rows[2].start_label == "Hoja 13, posición 1"


def test_preferred_breaks_only_include_exact_sheet_endings() -> None:
    assert preferred_page_pair_breaks(summaries()) == {12}


def test_map_can_be_downloaded_as_csv_and_pdf() -> None:
    rows = build_print_map(summaries())
    csv_data = print_map_csv(rows)
    pdf_data = print_map_pdf(rows)

    assert "Deck A" in csv_data.decode("utf-8-sig")
    assert len(PdfReader(BytesIO(pdf_data)).pages) == 1
