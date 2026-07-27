from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from .models import ImageFace

STANDARD_MAGIC_BACK_URL = (
    "https://backs.scryfall.io/png/0/a/"
    "0aeebaf5-8c7d-4636-9e82-8c27447861f7.png"
)


@dataclass(frozen=True, slots=True)
class BackSpec:
    mode: str
    label: str
    face: ImageFace | None = None
    embedded_data: bytes | None = None
    extension: str = ".png"


def no_back() -> BackSpec:
    return BackSpec(mode="none", label="Sin reverso")


def standard_magic_back() -> BackSpec:
    return BackSpec(
        mode="standard",
        label="Reverso estándar de Magic",
        face=ImageFace(
            label="Reverso estándar de Magic",
            url=STANDARD_MAGIC_BACK_URL,
            extension=".png",
            provider="scryfall",
        ),
    )


def neutral_back() -> BackSpec:
    return BackSpec(
        mode="neutral",
        label="Reverso neutro",
        embedded_data=generate_neutral_back(),
        extension=".png",
    )


def custom_url_back(url: str) -> BackSpec:
    if not url.startswith(("https://", "http://")):
        raise ValueError("La URL del reverso debe comenzar por http:// o https://.")
    path = urlparse(url).path.casefold()
    extension = next(
        (ext for ext in (".png", ".jpg", ".jpeg", ".webp") if path.endswith(ext)),
        ".jpg",
    )
    if extension == ".jpeg":
        extension = ".jpg"
    return BackSpec(
        mode="custom_url",
        label="Reverso personalizado",
        face=ImageFace(
            label="Reverso personalizado",
            url=url,
            extension=extension,
            provider="custom",
        ),
        extension=extension,
    )


def mpcfill_back(candidate: dict[str, Any], *, crop_mode: str = "auto") -> BackSpec:
    url = candidate.get("download_url") or candidate.get("downloadLink")
    if not isinstance(url, str) or not url:
        raise ValueError("El diseño MPCFill no ofrece una imagen descargable.")
    extension = str(candidate.get("extension") or "jpg").lower().lstrip(".")
    if extension == "jpeg":
        extension = "jpg"
    if extension not in {"png", "jpg", "webp"}:
        extension = "jpg"
    return BackSpec(
        mode="mpcfill",
        label=str(candidate.get("name") or "Reverso MPCFill"),
        face=ImageFace(
            label=str(candidate.get("name") or "Reverso MPCFill"),
            url=url,
            extension=f".{extension}",
            provider="mpcfill",
            crop_mode=crop_mode,
        ),
        extension=f".{extension}",
    )


def generate_neutral_back(width: int = 750, height: int = 1050) -> bytes:
    image = Image.new("RGB", (width, height), (25, 28, 34))
    draw = ImageDraw.Draw(image)
    margin = round(width * 0.055)
    radius = round(width * 0.035)
    draw.rounded_rectangle(
        (margin, margin, width - margin, height - margin),
        radius=radius,
        outline=(205, 210, 220),
        width=max(3, width // 120),
    )
    inner = margin * 2
    draw.rounded_rectangle(
        (inner, inner, width - inner, height - inner),
        radius=radius,
        outline=(90, 98, 115),
        width=max(2, width // 180),
    )
    title = "PLAYTEST"
    subtitle = "CARD BACK"
    font = ImageFont.load_default(size=max(20, width // 12))
    small = ImageFont.load_default(size=max(14, width // 22))
    title_box = draw.textbbox((0, 0), title, font=font)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=small)
    draw.text(
        ((width - (title_box[2] - title_box[0])) / 2, height * 0.43),
        title,
        fill=(230, 232, 238),
        font=font,
    )
    draw.text(
        ((width - (subtitle_box[2] - subtitle_box[0])) / 2, height * 0.54),
        subtitle,
        fill=(150, 158, 175),
        font=small,
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
