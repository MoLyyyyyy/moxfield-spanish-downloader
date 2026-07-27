from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

CARD_WIDTH_MM = 63.0
CARD_HEIGHT_MM = 88.0
BLEED_EDGE_MM = 3.048

CARD_ASPECT_RATIO = CARD_WIDTH_MM / CARD_HEIGHT_MM
BLEED_ASPECT_RATIO = (
    (CARD_WIDTH_MM + (2 * BLEED_EDGE_MM))
    / (CARD_HEIGHT_MM + (2 * BLEED_EDGE_MM))
)

CROP_AUTO = "auto"
CROP_NONE = "none"
CROP_FORCE = "force"
VALID_CROP_MODES = {CROP_AUTO, CROP_NONE, CROP_FORCE}


class ImageProcessingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes
    cropped: bool
    original_size: tuple[int, int]
    final_size: tuple[int, int]


def should_crop_mpc_image(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False

    ratio = width / height
    target_distance = abs(ratio - CARD_ASPECT_RATIO)
    bleed_distance = abs(ratio - BLEED_ASPECT_RATIO)

    # Un escaneo ya recortado suele estar muy cerca de 63:88.
    if target_distance <= 0.008:
        return False

    # Las imágenes preparadas para MPC suelen aproximarse a
    # (63 + 2*3.048):(88 + 2*3.048).
    return bleed_distance <= 0.018 and bleed_distance < target_distance


def mpc_crop_box(
    width: int,
    height: int,
    *,
    crop_shift_x: int = 0,
    crop_shift_y: int = 0,
) -> tuple[int, int, int, int]:
    horizontal_fraction = BLEED_EDGE_MM / (
        CARD_WIDTH_MM + (2 * BLEED_EDGE_MM)
    )
    vertical_fraction = BLEED_EDGE_MM / (
        CARD_HEIGHT_MM + (2 * BLEED_EDGE_MM)
    )

    crop_x = max(1, round(width * horizontal_fraction))
    crop_y = max(1, round(height * vertical_fraction))

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
        raise ImageProcessingError("La imagen es demasiado pequeña para recortarla.")

    return left, top, right, bottom


def process_mpc_image_bytes(
    data: bytes,
    *,
    crop_mode: str = CROP_AUTO,
    crop_shift_x: int = 0,
    crop_shift_y: int = 0,
    max_preview_size: int | None = None,
) -> ProcessedImage:
    if crop_mode not in VALID_CROP_MODES:
        raise ValueError(f"Modo de recorte desconocido: {crop_mode}")

    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened)
            original_format = (opened.format or "JPEG").upper()
            image.load()
    except Exception as exc:
        raise ImageProcessingError(
            "No se ha podido interpretar la imagen de MPCFill."
        ) from exc

    original_size = image.size
    crop_needed = (
        crop_mode == CROP_FORCE
        or (
            crop_mode == CROP_AUTO
            and should_crop_mpc_image(*original_size)
        )
    )

    if crop_needed:
        image = image.crop(
            mpc_crop_box(
                *image.size,
                crop_shift_x=crop_shift_x,
                crop_shift_y=crop_shift_y,
            )
        )

    if max_preview_size is not None and max(image.size) > max_preview_size:
        image.thumbnail(
            (max_preview_size, max_preview_size),
            Image.Resampling.LANCZOS,
        )

    output = io.BytesIO()
    if original_format in {"JPG", "JPEG"}:
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            if image.mode == "RGBA":
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image.convert("RGB"))
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=95, subsampling=0)
    else:
        if image.mode == "P":
            image = image.convert("RGBA")
        image.save(output, format="PNG", optimize=True)

    return ProcessedImage(
        data=output.getvalue(),
        cropped=crop_needed,
        original_size=original_size,
        final_size=image.size,
    )
