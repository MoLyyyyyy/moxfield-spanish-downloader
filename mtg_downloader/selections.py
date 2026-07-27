from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from typing import Iterable

from .models import CardVariant, DeckCard, ImageFace, ResolvedCard


class AllocationError(ValueError):
    pass


def variant_from_resolved(
    card: ResolvedCard,
    *,
    quantity: int | None = None,
) -> CardVariant:
    return CardVariant(
        quantity=card.source.quantity if quantity is None else quantity,
        status=card.status,
        provider=card.provider,
        type_line=card.type_line,
        language=card.language,
        printed_name=card.printed_name,
        selected_set=card.selected_set,
        collector_number=card.collector_number,
        faces=copy.deepcopy(card.faces),
        metadata=copy.deepcopy(card.scryfall_data),
        error=card.error,
        downloaded_format=card.downloaded_format,
        image_status=card.image_status,
        highres_image=card.highres_image,
    )


def effective_variants(card: ResolvedCard) -> list[CardVariant]:
    if card.allocations:
        return [copy.deepcopy(variant) for variant in card.allocations]
    return [variant_from_resolved(card)]


def variant_key(variant: CardVariant) -> str:
    face_payload = [
        {
            "url": face.url,
            "provider": face.provider,
            "crop_mode": face.crop_mode,
            "crop_shift_x": face.crop_shift_x,
            "crop_shift_y": face.crop_shift_y,
        }
        for face in variant.faces
    ]
    payload = {
        "provider": variant.provider,
        "set": variant.selected_set,
        "collector": variant.collector_number,
        "printed_name": variant.printed_name,
        "faces": face_payload,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def primary_variant(card: ResolvedCard) -> CardVariant:
    variants = effective_variants(card)
    return variants[0]


def apply_primary_variant(card: ResolvedCard, variant: CardVariant) -> ResolvedCard:
    card.status = variant.status
    card.provider = variant.provider
    card.type_line = variant.type_line or card.type_line
    card.language = variant.language
    card.printed_name = variant.printed_name
    card.selected_set = variant.selected_set
    card.collector_number = variant.collector_number
    card.faces = copy.deepcopy(variant.faces)
    card.scryfall_data = copy.deepcopy(variant.metadata)
    card.error = variant.error
    card.downloaded_format = variant.downloaded_format
    card.image_status = variant.image_status
    card.highres_image = variant.highres_image
    return card


def replace_all_copies(
    source_card: ResolvedCard,
    selection: ResolvedCard,
) -> ResolvedCard:
    selection.source = copy.deepcopy(source_card.source)
    selection.type_line = selection.type_line or source_card.type_line
    selection.allocations = []
    return selection


def add_variant(
    card: ResolvedCard,
    selection: ResolvedCard,
    *,
    quantity: int = 1,
) -> ResolvedCard:
    if card.source.quantity <= 1:
        return replace_all_copies(card, selection)
    if quantity < 1 or quantity > card.source.quantity:
        raise AllocationError("La cantidad de la variante no es válida.")

    allocations = effective_variants(card)
    incoming = variant_from_resolved(selection, quantity=quantity)
    incoming.type_line = incoming.type_line or card.type_line
    incoming_key = variant_key(incoming)

    existing = next(
        (variant for variant in allocations if variant_key(variant) == incoming_key),
        None,
    )
    if existing is not None:
        existing.quantity += quantity
    else:
        allocations.append(incoming)

    excess = sum(variant.quantity for variant in allocations) - card.source.quantity
    for variant in allocations:
        if excess <= 0:
            break
        if variant_key(variant) == incoming_key:
            continue
        removable = min(excess, max(0, variant.quantity - 1))
        variant.quantity -= removable
        excess -= removable

    if excess > 0:
        incoming.quantity -= excess

    allocations = [variant for variant in allocations if variant.quantity > 0]
    validate_allocations(card.source.quantity, allocations)
    card.allocations = allocations
    apply_primary_variant(card, allocations[0])
    return card


def set_allocation_quantities(
    card: ResolvedCard,
    quantities: Iterable[int],
) -> ResolvedCard:
    allocations = effective_variants(card)
    values = list(quantities)
    if len(values) != len(allocations):
        raise AllocationError("El número de cantidades no coincide con el reparto.")
    for allocation, quantity in zip(allocations, values):
        allocation.quantity = int(quantity)
    allocations = [allocation for allocation in allocations if allocation.quantity > 0]
    validate_allocations(card.source.quantity, allocations)
    card.allocations = allocations if len(allocations) > 1 else []
    apply_primary_variant(card, allocations[0])
    return card


def remove_variant(card: ResolvedCard, index: int) -> ResolvedCard:
    allocations = effective_variants(card)
    if len(allocations) <= 1:
        raise AllocationError("No se puede eliminar la única versión.")
    if index < 0 or index >= len(allocations):
        raise AllocationError("La variante no existe.")
    removed = allocations.pop(index)
    allocations[0].quantity += removed.quantity
    validate_allocations(card.source.quantity, allocations)
    card.allocations = allocations if len(allocations) > 1 else []
    apply_primary_variant(card, allocations[0])
    return card


def clone_selection_for_card(
    selection: ResolvedCard,
    target: ResolvedCard,
) -> ResolvedCard:
    clone = copy.deepcopy(selection)
    clone.source = copy.deepcopy(target.source)
    clone.type_line = target.type_line or clone.type_line
    clone.allocations = []
    return clone


def validate_allocations(total_quantity: int, allocations: list[CardVariant]) -> None:
    if not allocations:
        raise AllocationError("Debe existir al menos una versión.")
    if any(allocation.quantity <= 0 for allocation in allocations):
        raise AllocationError("Todas las cantidades deben ser mayores que cero.")
    total = sum(allocation.quantity for allocation in allocations)
    if total != total_quantity:
        raise AllocationError(
            f"El reparto suma {total}, pero la carta tiene {total_quantity} copias."
        )


def card_has_multiple_arts(card: ResolvedCard) -> bool:
    return len(effective_variants(card)) > 1


def selection_status(card: ResolvedCard) -> str:
    if card.allocations:
        return f"{len(card.allocations)} ilustraciones"
    if card.provider == "mpcfill":
        return "MPCFill"
    if card.status == "Selección manual":
        return "Manual"
    return "Automática"
