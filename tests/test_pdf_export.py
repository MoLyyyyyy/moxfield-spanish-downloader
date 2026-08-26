import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from mtg_downloader.backs import neutral_back
from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.pdf_export import (
    CARD_HEIGHT,
    CARD_WIDTH,
    CUT_STYLE_FULL,
    GAP_X,
    GAP_Y,
    MARGIN_X,
    MARGIN_Y,
    MIRROR_BLEED,
    _mpc_trim_box,
    _prepare_print_image,
    build_a4_pdf,
)


def image_bytes(
    size=(635, 889),
    *,
    image_format="PNG",
    color="white",
):
    image = Image.new("RGB", size, color)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


class FakeClient:
    def download_image(self, face):
        return image_bytes()


def test_pdf_contains_interleaved_front_and_back_pages() -> None:
    card = ResolvedCard(
        source=DeckCard(10, "Forest"),
        status="ok",
        faces=[ImageFace("Forest", "fake", ".png")],
    )
    result = build_a4_pdf(
        [card],
        FakeClient(),
        back_spec=neutral_back(),
        include_backs=True,
    )
    assert result.data.startswith(b"%PDF")
    assert result.cards == 10
    assert result.pages == 4
    assert result.back_pages == 2
    assert result.page_pairs == 2


def test_standard_backs_show_the_deck_code_but_fronts_do_not() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(2, "Forest"),
            status="ok",
            faces=[ImageFace("Forest", "fake", ".png")],
        ),
        ResolvedCard(
            source=DeckCard(1, "Island"),
            status="ok",
            faces=[ImageFace("Island", "fake", ".png")],
        ),
    ]

    result = build_a4_pdf(
        cards,
        FakeClient(),
        back_spec=neutral_back(),
        include_backs=True,
        deck_codes=["ATR", "BRE"],
        printer_marks=False,
    )
    pages = PdfReader(io.BytesIO(result.data)).pages

    assert "ATR" not in (pages[0].extract_text() or "")
    assert "BRE" not in (pages[0].extract_text() or "")
    assert "ATR" in (pages[1].extract_text() or "")
    assert "BRE" in (pages[1].extract_text() or "")
    positions: list[tuple[str, float]] = []

    def collect_position(text, _cm, tm, _font, _size) -> None:
        value = text.strip()
        if value in {"ATR", "BRE"}:
            positions.append((value, float(tm[4])))

    pages[1].extract_text(visitor_text=collect_position)
    atr_positions = [x for code, x in positions if code == "ATR"]
    bre_positions = [x for code, x in positions if code == "BRE"]

    assert len(atr_positions) == 2
    assert len(bre_positions) == 1
    assert bre_positions[0] < min(atr_positions)


def test_double_faced_card_does_not_cover_its_playable_back_with_a_code() -> None:
    card = ResolvedCard(
        source=DeckCard(1, "Delver of Secrets"),
        status="ok",
        faces=[
            ImageFace("Delver", "front", ".png"),
            ImageFace("Insectile Aberration", "back", ".png"),
        ],
    )

    result = build_a4_pdf(
        [card],
        FakeClient(),
        back_spec=neutral_back(),
        include_backs=True,
        deck_codes=["DEL"],
        printer_marks=False,
    )
    back_text = PdfReader(io.BytesIO(result.data)).pages[1].extract_text() or ""

    assert "DEL" not in back_text


def test_mpcfilltopdf_layout_measurements() -> None:
    from reportlab.lib.units import mm

    assert abs((CARD_WIDTH / mm) - 63.5) < 0.001
    assert abs((CARD_HEIGHT / mm) - 88.9) < 0.001
    assert abs((MIRROR_BLEED / mm) - 1.0) < 0.001
    assert abs((MARGIN_X / mm) - 5.75) < 0.001
    assert abs((MARGIN_Y / mm) - 11.15) < 0.001
    assert abs((GAP_X / mm) - 4.0) < 0.001
    assert abs((GAP_Y / mm) - 4.0) < 0.001


def test_print_image_adds_one_mm_mirror_bleed() -> None:
    prepared = _prepare_print_image(
        image_bytes(),
        provider="scryfall",
    )
    with Image.open(io.BytesIO(prepared)) as image:
        assert image.size == (655, 909)


def test_mpc_crop_uses_repository_fractions() -> None:
    box = _mpc_trim_box(750, 1050)
    assert box == (32, 33, 718, 1017)


def test_full_cut_line_style_is_supported() -> None:
    card = ResolvedCard(
        source=DeckCard(1, "Forest"),
        status="ok",
        faces=[ImageFace("Forest", "fake", ".png")],
    )
    result = build_a4_pdf(
        [card],
        FakeClient(),
        cut_line_style=CUT_STYLE_FULL,
        printer_marks=False,
    )
    assert result.data.startswith(b"%PDF")
    assert result.pages == 1



def test_original_printer_assets_are_embedded() -> None:
    import hashlib

    from mtg_downloader.pdf_export import (
        COLOR_BAR_PATH,
        CORNER_MARK_PATH,
    )

    assert CORNER_MARK_PATH.exists()
    assert COLOR_BAR_PATH.exists()
    assert hashlib.sha256(CORNER_MARK_PATH.read_bytes()).hexdigest() == (
        "5bb528c488fc4190de3a70933c7620131f182c92c0f6102acf21011e445a044d"
    )
    assert hashlib.sha256(COLOR_BAR_PATH.read_bytes()).hexdigest() == (
        "b4085ae738978b0a3084590397552808d231249ba2e5d72a387d72029c457693"
    )



def test_mpc_pdf_crop_is_always_exact() -> None:
    # Exact MPCFillToPDF behavior: 4.2% horizontal and 3.1% vertical.
    assert _mpc_trim_box(1000, 1000) == (42, 31, 958, 969)



def test_exact_page_label_coordinates() -> None:
    source = Path(
        __file__
    ).parents[1] / "mtg_downloader" / "pdf_export.py"
    text = source.read_text(encoding="utf-8")
    assert 'document.drawString(295.4, 15.3, page_label)' in text



def test_pdf_reports_detailed_progress() -> None:
    events = []
    card = ResolvedCard(
        source=DeckCard(2, "Forest"),
        status="ok",
        faces=[ImageFace("Forest", "fake", ".png")],
    )
    result = build_a4_pdf(
        [card],
        FakeClient(),
        progress_callback=events.append,
    )

    assert result.pages == 1
    assert events
    assert events[0].phase == "front"
    assert events[0].label == "Forest"
    assert any(event.phase == "page" for event in events)
    assert any(event.phase == "finalizing" for event in events)
    assert events[-1].phase == "done"
    assert events[-1].current == events[-1].total
