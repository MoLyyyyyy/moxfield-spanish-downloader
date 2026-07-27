from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .backs import BackSpec, no_back
from .image_processing import should_crop_mpc_image
from .models import ImageFace
from .physical import PhysicalCard, physical_cards
from .scryfall import ScryfallClient

# Perfil compatible con Diphendara/MPCFillToPDF.
CARD_WIDTH = 63.5 * mm
CARD_HEIGHT = 88.9 * mm
MIRROR_BLEED = 1.0 * mm
IMAGE_WIDTH = CARD_WIDTH + (2 * MIRROR_BLEED)
IMAGE_HEIGHT = CARD_HEIGHT + (2 * MIRROR_BLEED)

COLUMNS = 3
ROWS = 3
PER_PAGE = COLUMNS * ROWS

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 5.75 * mm
MARGIN_Y = 11.15 * mm
GAP_X = (
    PAGE_WIDTH - (2 * MARGIN_X) - (COLUMNS * CARD_WIDTH)
) / (COLUMNS - 1)
GAP_Y = (
    PAGE_HEIGHT - (2 * MARGIN_Y) - (ROWS * CARD_HEIGHT)
) / (ROWS - 1)

MARK_GAP = 3.0
CORNER_MARK_SIZE = 10.0
COLOR_BAR_WIDTH = 200.0
COLOR_BAR_HEIGHT = 15.0
COLOR_BAR_X = 197.64

MPC_BLEED_X_FRACTION = 0.042
MPC_BLEED_Y_FRACTION = 0.031

CUT_STYLE_TICKS = "ticks"
CUT_STYLE_FULL = "full"
VALID_CUT_STYLES = {CUT_STYLE_TICKS, CUT_STYLE_FULL}


@dataclass(frozen=True, slots=True)
class PdfResult:
    data: bytes
    pages: int
    cards: int
    back_pages: int
    page_pairs: int


def build_a4_pdf(
    resolved_cards,
    client: ScryfallClient,
    *,
    back_spec: BackSpec | None = None,
    include_backs: bool = False,
    cut_lines: bool = True,
    cut_line_style: str = CUT_STYLE_TICKS,
    cut_line_width: float = 1.0,
    cut_line_color: str = "#000000",
    cut_line_over_cards: bool = False,
    printer_marks: bool = True,
) -> PdfResult:
    """Generate an A4 3x3 duplex PDF compatible with MPCFillToPDF layout.

    Pages are emitted as front/back pairs: 1, 1B, 2, 2B...
    The back side is mirrored horizontally within each row.
    """
    if cut_line_style not in VALID_CUT_STYLES:
        raise ValueError(f"Estilo de corte desconocido: {cut_line_style}")
    if not 0.1 <= float(cut_line_width) <= 10:
        raise ValueError("El grosor de corte debe estar entre 0,1 y 10 pt.")

    cards = physical_cards(resolved_cards)
    selected_back = back_spec or no_back()
    needs_back_pages = (
        include_backs
        or selected_back.mode != "none"
        or any(len(card.variant.faces) > 1 for card in cards)
    )

    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    processed_cache: dict[str, bytes] = {}
    generic_back_cache: bytes | None = None

    if selected_back.embedded_data is not None:
        generic_back_cache = _prepare_print_image(
            selected_back.embedded_data,
            provider="embedded",
        )
    elif selected_back.face is not None:
        generic_back_cache = _prepare_face(
            selected_back.face,
            client,
            processed_cache,
        )

    front_pages = 0
    back_pages = 0
    page_pairs = 0

    for page_start in range(0, len(cards), PER_PAGE):
        page_pairs += 1
        page_cards: list[PhysicalCard | None] = list(
            cards[page_start : page_start + PER_PAGE]
        )
        page_cards.extend([None] * (PER_PAGE - len(page_cards)))

        _draw_page(
            document,
            page_cards,
            client,
            processed_cache,
            generic_back_cache,
            backs=False,
            page_label=str(page_pairs),
            cut_lines=cut_lines,
            cut_line_style=cut_line_style,
            cut_line_width=cut_line_width,
            cut_line_color=cut_line_color,
            cut_line_over_cards=cut_line_over_cards,
            printer_marks=printer_marks,
        )
        document.showPage()
        front_pages += 1

        if needs_back_pages:
            mirrored: list[PhysicalCard | None] = []
            for row in range(ROWS):
                row_cards = page_cards[row * COLUMNS : (row + 1) * COLUMNS]
                mirrored.extend(reversed(row_cards))

            _draw_page(
                document,
                mirrored,
                client,
                processed_cache,
                generic_back_cache,
                backs=True,
                page_label=f"{page_pairs}B",
                cut_lines=cut_lines,
                cut_line_style=cut_line_style,
                cut_line_width=cut_line_width,
                cut_line_color=cut_line_color,
                cut_line_over_cards=cut_line_over_cards,
                printer_marks=printer_marks,
            )
            document.showPage()
            back_pages += 1

    document.save()
    return PdfResult(
        data=output.getvalue(),
        pages=front_pages + back_pages,
        cards=len(cards),
        back_pages=back_pages,
        page_pairs=page_pairs,
    )


def _trim_origin(column: int, row: int) -> tuple[float, float]:
    x = MARGIN_X + column * (CARD_WIDTH + GAP_X)
    y = (
        PAGE_HEIGHT
        - MARGIN_Y
        - ((row + 1) * CARD_HEIGHT)
        - (row * GAP_Y)
    )
    return x, y


def _draw_page(
    document: canvas.Canvas,
    cards: list[PhysicalCard | None],
    client: ScryfallClient,
    processed_cache: dict[str, bytes],
    generic_back: bytes | None,
    *,
    backs: bool,
    page_label: str,
    cut_lines: bool,
    cut_line_style: str,
    cut_line_width: float,
    cut_line_color: str,
    cut_line_over_cards: bool,
    printer_marks: bool,
) -> None:
    color = _hex_to_rgb(cut_line_color)

    if cut_lines and not cut_line_over_cards:
        _draw_crop_marks(
            document,
            color,
            cut_line_style,
            cut_line_width,
        )

    if printer_marks:
        _draw_printer_marks(document, page_label)

    for position, card in enumerate(cards):
        row = position // COLUMNS
        column = position % COLUMNS
        x, y = _trim_origin(column, row)

        image_data = _card_image(
            card,
            client,
            processed_cache,
            backs=backs,
            generic_back=generic_back,
        )
        if image_data is not None:
            document.drawImage(
                ImageReader(io.BytesIO(image_data)),
                x - MIRROR_BLEED,
                y - MIRROR_BLEED,
                width=IMAGE_WIDTH,
                height=IMAGE_HEIGHT,
                preserveAspectRatio=False,
                mask="auto",
            )

    if cut_lines and cut_line_over_cards:
        _draw_crop_marks(
            document,
            color,
            cut_line_style,
            cut_line_width,
        )


def _card_image(
    card: PhysicalCard | None,
    client: ScryfallClient,
    processed_cache: dict[str, bytes],
    *,
    backs: bool,
    generic_back: bytes | None,
) -> bytes | None:
    if card is None or not card.variant.faces:
        return None

    if not backs:
        return _prepare_face(
            card.variant.faces[0],
            client,
            processed_cache,
        )

    if len(card.variant.faces) > 1:
        return _prepare_face(
            card.variant.faces[1],
            client,
            processed_cache,
        )
    return generic_back


def _prepare_face(
    face: ImageFace,
    client: ScryfallClient,
    cache: dict[str, bytes],
) -> bytes:
    key = "|".join(
        [
            face.url,
            face.provider,
            face.crop_mode or "",
            str(face.crop_shift_x),
            str(face.crop_shift_y),
            "mpcfilltopdf-v1",
        ]
    )
    if key in cache:
        return cache[key]

    raw_download = getattr(client, "download_raw_image", None)
    if callable(raw_download):
        raw = raw_download(face)
    else:
        raw = client.download_image(face)

    prepared = _prepare_print_image(
        raw,
        provider=face.provider,
        crop_shift_x=face.crop_shift_x,
        crop_shift_y=face.crop_shift_y,
    )
    cache[key] = prepared
    return prepared


def _prepare_print_image(
    data: bytes,
    *,
    provider: str,
    crop_shift_x: int = 0,
    crop_shift_y: int = 0,
) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            source_format = (opened.format or "JPEG").upper()
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
    except Exception as exc:
        raise ValueError("No se ha podido procesar una imagen para el PDF.") from exc

    if provider == "mpcfill" and should_crop_mpc_image(*image.size):
        image = image.crop(
            _mpc_trim_box(
                *image.size,
                crop_shift_x=crop_shift_x,
                crop_shift_y=crop_shift_y,
            )
        )
    else:
        image = _fill_rounded_corners(image)

    image = _add_mirror_bleed(image)

    output = io.BytesIO()
    if source_format in {"JPG", "JPEG"}:
        image.save(
            output,
            format="JPEG",
            quality=95,
            subsampling=0,
            optimize=True,
        )
    else:
        image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _mpc_trim_box(
    width: int,
    height: int,
    *,
    crop_shift_x: int = 0,
    crop_shift_y: int = 0,
) -> tuple[int, int, int, int]:
    crop_x = max(1, round(width * MPC_BLEED_X_FRACTION))
    crop_y = max(1, round(height * MPC_BLEED_Y_FRACTION))

    shift_x = round(crop_x * max(-100, min(100, crop_shift_x)) / 100)
    shift_y = round(crop_y * max(-100, min(100, crop_shift_y)) / 100)

    left = crop_x + shift_x
    top = crop_y + shift_y
    right = width - crop_x + shift_x
    bottom = height - crop_y + shift_y

    if left < 0:
        right -= left
        left = 0
    if right > width:
        left -= right - width
        right = width
    if top < 0:
        bottom -= top
        top = 0
    if bottom > height:
        top -= bottom - height
        bottom = height

    if right <= left or bottom <= top:
        raise ValueError("La imagen es demasiado pequeña para recortarla.")
    return left, top, right, bottom


def _add_mirror_bleed(image: Image.Image) -> Image.Image:
    width, height = image.size
    bleed_x = max(1, round(width * 1.0 / 63.5))
    bleed_y = max(1, round(height * 1.0 / 88.9))

    full_width = width + (2 * bleed_x)
    full_height = height + (2 * bleed_y)
    output = Image.new("RGB", (full_width, full_height))
    output.paste(image, (bleed_x, bleed_y))

    output.paste(
        ImageOps.flip(image.crop((0, 0, width, bleed_y))),
        (bleed_x, 0),
    )
    output.paste(
        ImageOps.flip(
            image.crop((0, height - bleed_y, width, height))
        ),
        (bleed_x, full_height - bleed_y),
    )
    output.paste(
        ImageOps.mirror(image.crop((0, 0, bleed_x, height))),
        (0, bleed_y),
    )
    output.paste(
        ImageOps.mirror(
            image.crop((width - bleed_x, 0, width, height))
        ),
        (full_width - bleed_x, bleed_y),
    )

    output.paste(
        image.crop((0, 0, bleed_x, bleed_y)).rotate(180),
        (0, 0),
    )
    output.paste(
        image.crop((width - bleed_x, 0, width, bleed_y)).rotate(180),
        (full_width - bleed_x, 0),
    )
    output.paste(
        image.crop((0, height - bleed_y, bleed_x, height)).rotate(180),
        (0, full_height - bleed_y),
    )
    output.paste(
        image.crop(
            (
                width - bleed_x,
                height - bleed_y,
                width,
                height,
            )
        ).rotate(180),
        (full_width - bleed_x, full_height - bleed_y),
    )
    return output


def _fill_rounded_corners(image: Image.Image) -> Image.Image:
    width, height = image.size
    radius = max(1, round(min(width, height) * 0.04))
    radius_sq = radius * radius
    pixels = image.load()

    definitions = (
        ("tl", 0, 0, 1, 1),
        ("tr", width - 1, 0, -1, 1),
        ("bl", 0, height - 1, 1, -1),
        ("br", width - 1, height - 1, -1, -1),
    )

    for name, origin_x, origin_y, sign_x, sign_y in definitions:
        border = _sample_border_color(image, name, radius)
        border_luma = _luminance(*border)
        for delta_y in range(radius + 1):
            for delta_x in range(radius + 1):
                if (delta_x * delta_x) + (delta_y * delta_y) > radius_sq:
                    continue
                x = origin_x + (delta_x * sign_x)
                y = origin_y + (delta_y * sign_y)
                if not (0 <= x < width and 0 <= y < height):
                    continue
                color = pixels[x, y][:3]
                if abs(_luminance(*color) - border_luma) > 60:
                    pixels[x, y] = border
    return image


def _sample_border_color(
    image: Image.Image,
    corner: str,
    radius: int,
) -> tuple[int, int, int]:
    width, height = image.size
    samples: list[tuple[int, int, int]] = []
    lower = radius
    upper = min(2 * radius, min(width, height) // 2)

    for index in range(lower, upper):
        if corner == "tl":
            points = ((index, 0), (0, index))
        elif corner == "tr":
            points = ((width - 1 - index, 0), (width - 1, index))
        elif corner == "bl":
            points = ((index, height - 1), (0, height - 1 - index))
        else:
            points = (
                (width - 1 - index, height - 1),
                (width - 1, height - 1 - index),
            )

        for x, y in points:
            if 0 <= x < width and 0 <= y < height:
                samples.append(image.getpixel((x, y))[:3])

    if not samples:
        return (0, 0, 0)
    samples.sort(key=lambda color: _luminance(*color))
    return samples[len(samples) // 2]


def _luminance(red: int, green: int, blue: int) -> float:
    return (0.299 * red) + (0.587 * green) + (0.114 * blue)


def _draw_crop_marks(
    document: canvas.Canvas,
    color: tuple[float, float, float],
    style: str,
    line_width: float,
) -> None:
    xs = [
        MARGIN_X + column * (CARD_WIDTH + GAP_X) + delta
        for column in range(COLUMNS)
        for delta in (0.0, CARD_WIDTH)
    ]
    ys = [
        (
            PAGE_HEIGHT
            - MARGIN_Y
            - ((row + 1) * CARD_HEIGHT)
            - (row * GAP_Y)
            + delta
        )
        for row in range(ROWS)
        for delta in (0.0, CARD_HEIGHT)
    ]

    document.saveState()
    document.setLineWidth(line_width)
    document.setStrokeColorRGB(*color)

    if style == CUT_STYLE_FULL:
        for x in xs:
            document.line(x, 0, x, PAGE_HEIGHT)
        for y in ys:
            document.line(0, y, PAGE_WIDTH, y)
    else:
        top_end = PAGE_HEIGHT - MARGIN_Y + MARK_GAP
        bottom_end = MARGIN_Y - MARK_GAP
        for x in xs:
            document.line(x, 0, x, bottom_end)
            document.line(x, top_end, x, PAGE_HEIGHT)

        left_end = MARGIN_X - MARK_GAP
        right_start = PAGE_WIDTH - MARGIN_X + MARK_GAP
        for y in ys:
            document.line(0, y, left_end, y)
            document.line(right_start, y, PAGE_WIDTH, y)

    document.restoreState()


def _draw_printer_marks(
    document: canvas.Canvas,
    page_label: str,
) -> None:
    for x, y in (
        (0, 0),
        (PAGE_WIDTH - CORNER_MARK_SIZE, 0),
        (0, PAGE_HEIGHT - CORNER_MARK_SIZE),
        (
            PAGE_WIDTH - CORNER_MARK_SIZE,
            PAGE_HEIGHT - CORNER_MARK_SIZE,
        ),
    ):
        _draw_registration_target(
            document,
            x + (CORNER_MARK_SIZE / 2),
            y + (CORNER_MARK_SIZE / 2),
            CORNER_MARK_SIZE / 2,
        )

    _draw_color_bar(
        document,
        COLOR_BAR_X,
        PAGE_HEIGHT - COLOR_BAR_HEIGHT,
        COLOR_BAR_WIDTH,
        COLOR_BAR_HEIGHT,
    )

    document.saveState()
    document.setFont("Helvetica", 8)
    document.setFillColorRGB(0, 0, 0)
    document.drawString(295.4, 15.3, page_label)
    document.restoreState()


def _draw_registration_target(
    document: canvas.Canvas,
    center_x: float,
    center_y: float,
    radius: float,
) -> None:
    document.saveState()
    document.setStrokeColorRGB(0, 0, 0)
    document.setFillColorRGB(0, 0, 0)
    document.setLineWidth(0.65)

    document.circle(center_x, center_y, radius * 0.82, stroke=1, fill=0)
    document.circle(center_x, center_y, radius * 0.48, stroke=1, fill=0)
    document.circle(center_x, center_y, radius * 0.14, stroke=0, fill=1)
    document.line(
        center_x - radius,
        center_y,
        center_x + radius,
        center_y,
    )
    document.line(
        center_x,
        center_y - radius,
        center_x,
        center_y + radius,
    )
    document.restoreState()


def _draw_color_bar(
    document: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    document.saveState()
    document.setFillColorRGB(1, 1, 1)
    document.rect(x, y, width, height, stroke=0, fill=1)

    _draw_registration_target(
        document,
        x + 7.2,
        y + (height / 2),
        6.4,
    )

    block_height = height * 0.58
    block_y = y + ((height - block_height) / 2)
    block_width = 6.0
    group_positions = (51.0, 81.0, 111.0, 140.0)

    shades = (1.0, 0.78, 0.55, 0.32)
    for group, start in enumerate(group_positions):
        for index, shade in enumerate(shades):
            if group == 0:
                color = (shade, 0, 0, 0)
            elif group == 1:
                color = (0, shade, 0, 0)
            elif group == 2:
                color = (0, 0, shade, 0)
            else:
                color = (0, 0, 0, shade)
            document.setFillColorCMYK(*color)
            document.rect(
                x + start + (index * block_width),
                block_y,
                block_width,
                block_height,
                stroke=0,
                fill=1,
            )

    register_x = x + 181.0
    register_y = y + 1.5
    register_size = 12.0
    document.setStrokeColorRGB(0, 0, 0)
    document.setLineWidth(1.0)
    document.rect(
        register_x,
        register_y,
        register_size,
        register_size,
        stroke=1,
        fill=0,
    )
    half = register_size / 2
    quadrants = (
        (1, 0, 0, 0),
        (0, 1, 0, 0),
        (0, 0, 1, 0),
        (0, 0, 0, 1),
    )
    positions = (
        (register_x, register_y + half),
        (register_x + half, register_y + half),
        (register_x, register_y),
        (register_x + half, register_y),
    )
    for color, (qx, qy) in zip(quadrants, positions):
        document.setFillColorCMYK(*color)
        document.rect(qx, qy, half, half, stroke=0, fill=1)

    document.setStrokeColorRGB(0, 0, 0)
    document.line(
        register_x - 3,
        register_y + half,
        register_x + register_size + 3,
        register_y + half,
    )
    document.line(
        register_x + half,
        register_y - 2,
        register_x + half,
        register_y + register_size + 2,
    )
    document.restoreState()


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError("El color debe tener formato hexadecimal.")
    try:
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
    except ValueError as exc:
        raise ValueError("El color debe tener formato hexadecimal.") from exc
    return red / 255, green / 255, blue / 255
