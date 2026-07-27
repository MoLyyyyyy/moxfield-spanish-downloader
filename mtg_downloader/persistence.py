from __future__ import annotations

import copy
import json
from typing import Any

from .models import CardVariant, DeckCard, ImageFace, ResolvedCard

SCHEMA_VERSION = 1


class SelectionConfigError(ValueError):
    pass


def source_key(card: DeckCard) -> str:
    return "|".join(
        [
            card.zone.casefold(),
            card.name.casefold(),
            (card.set_code or "").casefold(),
            (card.collector_number or "").casefold(),
        ]
    )


def export_selection_config(
    cards: list[ResolvedCard],
    *,
    deck_signature: str,
) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "deck_signature": deck_signature,
        "selections": [
            {
                "source_key": source_key(card.source),
                "selection": _resolved_to_dict(card),
            }
            for card in cards
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def import_selection_config(
    text: str,
    current_cards: list[ResolvedCard],
) -> tuple[list[ResolvedCard], list[str]]:
    if len(text.encode("utf-8")) > 5_000_000:
        raise SelectionConfigError("El archivo de elecciones es demasiado grande.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SelectionConfigError("El JSON de elecciones no es válido.") from exc

    if not isinstance(payload, dict):
        raise SelectionConfigError("El JSON debe contener un objeto.")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SelectionConfigError("La versión del archivo no es compatible.")

    rows = payload.get("selections")
    if not isinstance(rows, list):
        raise SelectionConfigError("El archivo no contiene elecciones.")

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("source_key")
        selection = row.get("selection")
        if isinstance(key, str) and isinstance(selection, dict):
            by_key[key] = selection

    restored: list[ResolvedCard] = []
    warnings: list[str] = []
    for current in current_cards:
        data = by_key.get(source_key(current.source))
        if data is None:
            restored.append(copy.deepcopy(current))
            continue
        try:
            restored.append(_resolved_from_dict(current.source, data, current.type_line))
        except SelectionConfigError as exc:
            restored.append(copy.deepcopy(current))
            warnings.append(f"{current.source.name}: {exc}")

    unmatched = set(by_key) - {source_key(card.source) for card in current_cards}
    if unmatched:
        warnings.append(
            f"{len(unmatched)} elecciones no correspondían con el mazo actual."
        )
    return restored, warnings


def _face_to_dict(face: ImageFace) -> dict[str, Any]:
    return {
        "label": face.label,
        "url": face.url,
        "extension": face.extension,
        "provider": face.provider,
        "crop_mode": face.crop_mode,
        "crop_shift_x": face.crop_shift_x,
        "crop_shift_y": face.crop_shift_y,
    }


def _face_from_dict(data: dict[str, Any]) -> ImageFace:
    try:
        url = str(data["url"])
        extension = str(data["extension"])
    except KeyError as exc:
        raise SelectionConfigError("Falta información de imagen.") from exc
    if not url.startswith(("https://", "http://")):
        raise SelectionConfigError("La URL de imagen guardada no es válida.")
    return ImageFace(
        label=str(data.get("label") or "Carta"),
        url=url,
        extension=extension,
        provider=str(data.get("provider") or "scryfall"),
        crop_mode=(
            str(data["crop_mode"])
            if data.get("crop_mode") is not None
            else None
        ),
        crop_shift_x=int(data.get("crop_shift_x") or 0),
        crop_shift_y=int(data.get("crop_shift_y") or 0),
    )


def _variant_to_dict(variant: CardVariant) -> dict[str, Any]:
    return {
        "quantity": variant.quantity,
        "status": variant.status,
        "provider": variant.provider,
        "type_line": variant.type_line,
        "language": variant.language,
        "printed_name": variant.printed_name,
        "selected_set": variant.selected_set,
        "collector_number": variant.collector_number,
        "faces": [_face_to_dict(face) for face in variant.faces],
        "metadata": variant.metadata,
        "error": variant.error,
        "downloaded_format": variant.downloaded_format,
        "image_status": variant.image_status,
        "highres_image": variant.highres_image,
    }


def _variant_from_dict(data: dict[str, Any]) -> CardVariant:
    faces_data = data.get("faces") or []
    if not isinstance(faces_data, list):
        raise SelectionConfigError("Las caras de una variante no son válidas.")
    return CardVariant(
        quantity=int(data.get("quantity") or 0),
        status=str(data.get("status") or "Selección guardada"),
        provider=str(data.get("provider") or "scryfall"),
        type_line=(str(data["type_line"]) if data.get("type_line") else None),
        language=(str(data["language"]) if data.get("language") else None),
        printed_name=(
            str(data["printed_name"]) if data.get("printed_name") else None
        ),
        selected_set=(
            str(data["selected_set"]) if data.get("selected_set") else None
        ),
        collector_number=(
            str(data["collector_number"])
            if data.get("collector_number") is not None
            else None
        ),
        faces=[_face_from_dict(face) for face in faces_data if isinstance(face, dict)],
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
        error=(str(data["error"]) if data.get("error") else None),
        downloaded_format=(
            str(data["downloaded_format"])
            if data.get("downloaded_format")
            else None
        ),
        image_status=(
            str(data["image_status"]) if data.get("image_status") else None
        ),
        highres_image=(
            bool(data["highres_image"])
            if data.get("highres_image") is not None
            else None
        ),
    )


def _resolved_to_dict(card: ResolvedCard) -> dict[str, Any]:
    return {
        "status": card.status,
        "provider": card.provider,
        "type_line": card.type_line,
        "language": card.language,
        "printed_name": card.printed_name,
        "selected_set": card.selected_set,
        "collector_number": card.collector_number,
        "faces": [_face_to_dict(face) for face in card.faces],
        "metadata": card.scryfall_data,
        "error": card.error,
        "downloaded_format": card.downloaded_format,
        "image_status": card.image_status,
        "highres_image": card.highres_image,
        "allocations": [_variant_to_dict(variant) for variant in card.allocations],
    }


def _resolved_from_dict(
    source: DeckCard,
    data: dict[str, Any],
    fallback_type_line: str | None,
) -> ResolvedCard:
    faces_data = data.get("faces") or []
    allocations_data = data.get("allocations") or []
    if not isinstance(faces_data, list) or not isinstance(allocations_data, list):
        raise SelectionConfigError("La estructura de la elección no es válida.")

    allocations = [
        _variant_from_dict(variant)
        for variant in allocations_data
        if isinstance(variant, dict)
    ]
    if allocations and sum(variant.quantity for variant in allocations) != source.quantity:
        raise SelectionConfigError("El reparto guardado no coincide con la cantidad actual.")

    return ResolvedCard(
        source=copy.deepcopy(source),
        status=str(data.get("status") or "Selección guardada"),
        provider=str(data.get("provider") or "scryfall"),
        type_line=(
            str(data["type_line"])
            if data.get("type_line")
            else fallback_type_line
        ),
        language=(str(data["language"]) if data.get("language") else None),
        printed_name=(
            str(data["printed_name"]) if data.get("printed_name") else None
        ),
        selected_set=(
            str(data["selected_set"]) if data.get("selected_set") else None
        ),
        collector_number=(
            str(data["collector_number"])
            if data.get("collector_number") is not None
            else None
        ),
        faces=[_face_from_dict(face) for face in faces_data if isinstance(face, dict)],
        scryfall_data=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
        error=(str(data["error"]) if data.get("error") else None),
        downloaded_format=(
            str(data["downloaded_format"])
            if data.get("downloaded_format")
            else None
        ),
        image_status=(
            str(data["image_status"]) if data.get("image_status") else None
        ),
        highres_image=(
            bool(data["highres_image"])
            if data.get("highres_image") is not None
            else None
        ),
        allocations=allocations,
    )
