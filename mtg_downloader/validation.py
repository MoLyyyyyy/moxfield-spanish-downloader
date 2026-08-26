from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .backs import BackSpec
from .models import ResolvedCard
from .physical import physical_cards
from .selections import effective_variants


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    expected_cards: int
    expected_front_files: int
    expected_back_files: int
    entries: int
    variants: int
    missing_entries: tuple[str, ...] = ()
    lowres_entries: tuple[str, ...] = ()
    bleed_retained: tuple[str, ...] = ()
    duplicate_entries: tuple[str, ...] = ()
    minimum_known_dpi: int | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def can_generate(self) -> bool:
        return not self.errors


def validate_deck(
    cards: list[ResolvedCard],
    *,
    back_spec: BackSpec | None = None,
    warn_duplicates: bool = True,
) -> ValidationSummary:
    missing: list[str] = []
    lowres: list[str] = []
    bleed: list[str] = []
    dpi_values: list[int] = []
    variant_count = 0
    front_files = 0

    for card in cards:
        variants = effective_variants(card)
        variant_count += len(variants)
        for variant in variants:
            if not variant.faces:
                missing.append(card.source.name)
                continue
            front_files += variant.quantity * max(1, len(variant.faces))
            if variant.image_status == "lowres" or variant.highres_image is False:
                lowres.append(card.source.name)
            for face in variant.faces:
                if face.provider == "mpcfill" and face.crop_mode not in {None, "auto"}:
                    bleed.append(card.source.name)
            match = re.search(r"(\d+)\s*dpi", variant.image_status or "", re.I)
            if match:
                dpi_values.append(int(match.group(1)))

    keys = [
        "|".join(
            [
                card.source.zone.casefold(),
                card.source.name.casefold(),
                (card.source.set_code or "").casefold(),
                (card.source.collector_number or "").casefold(),
            ]
        )
        for card in cards
    ]
    counts = Counter(keys)
    duplicates = sorted(
        {
            card.source.name
            for card, key in zip(cards, keys)
            if counts[key] > 1
        }
    )

    expected_cards = len(physical_cards(cards))
    expected_backs = 0
    if back_spec and back_spec.mode != "none":
        expected_backs = expected_cards
    else:
        expected_backs = sum(
            variant.quantity
            for card in cards
            for variant in effective_variants(card)
            if len(variant.faces) > 1
        )

    errors = []
    warnings = []
    if missing:
        errors.append(f"Faltan imágenes en {len(set(missing))} entradas.")
    if lowres:
        errors.append(f"Hay {len(set(lowres))} entradas de baja resolución.")
    if bleed:
        warnings.append(f"Hay {len(set(bleed))} entradas MPCFill con un recorte no automático.")
    if duplicates and warn_duplicates:
        warnings.append(f"Hay {len(duplicates)} entradas duplicadas en la lista.")

    return ValidationSummary(
        expected_cards=expected_cards,
        expected_front_files=front_files,
        expected_back_files=expected_backs,
        entries=len(cards),
        variants=variant_count,
        missing_entries=tuple(sorted(set(missing))),
        lowres_entries=tuple(sorted(set(lowres))),
        bleed_retained=tuple(sorted(set(bleed))),
        duplicate_entries=(
            tuple(duplicates) if warn_duplicates else ()
        ),
        minimum_known_dpi=min(dpi_values) if dpi_values else None,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
