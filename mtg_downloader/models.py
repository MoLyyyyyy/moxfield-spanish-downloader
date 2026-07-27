from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DeckCard:
    quantity: int
    name: str
    zone: str = "mainboard"
    set_code: str | None = None
    collector_number: str | None = None


@dataclass(slots=True)
class ImageFace:
    label: str
    url: str
    extension: str


@dataclass(slots=True)
class ResolvedCard:
    source: DeckCard
    status: str
    language: str | None = None
    printed_name: str | None = None
    selected_set: str | None = None
    collector_number: str | None = None
    faces: list[ImageFace] = field(default_factory=list)
    scryfall_data: dict[str, Any] | None = None
    error: str | None = None
    downloaded_format: str | None = None
    image_status: str | None = None
    highres_image: bool | None = None
