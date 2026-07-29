from __future__ import annotations

import base64
import copy
import hashlib
import json
import binascii
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import DeckCard, ResolvedCard
from .persistence import _face_to_dict, _resolved_from_dict, _resolved_to_dict

PROJECT_SCHEMA_VERSION = 3
SUPPORTED_PROJECT_SCHEMA_VERSIONS = {1, 2, 3}
MAX_PROJECT_BYTES = 150_000_000


class ProjectFileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedProject:
    analysis_config: dict[str, Any]
    analysis_signature: str
    cards: list[DeckCard]
    resolved_cards: list[ResolvedCard]
    deck_summaries: list[dict[str, Any]]
    multi_deck_stats: dict[str, Any]
    deck_analysis_stats: list[dict[str, Any]]
    reviewed_decks: list[int]
    active_review_deck: int
    review_selected_index: int
    workspace_mode: str
    review_only_problematic: bool
    pdf_settings: dict[str, Any]
    project_revision: int
    saved_at: str | None
    selection_summary: dict[str, int]
    embedded_upload_count: int = 0




def _project_uploads_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "moxfield_cartas_es_cache" / "user_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _upload_asset_id_from_face(face: Any) -> str | None:
    if getattr(face, "provider", None) != "upload":
        return None
    face_data = _face_to_dict(face)
    asset_id = face_data.get("embedded_asset_id")
    if isinstance(asset_id, str) and asset_id:
        return asset_id
    url = face_data.get("url")
    if isinstance(url, str) and url.startswith("upload://"):
        parsed = urlparse(url)
        token = parsed.netloc + parsed.path
        return token or None
    return None


def _collect_embedded_upload_assets(
    resolved_cards: list[ResolvedCard],
) -> list[dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for card in resolved_cards:
        variants = [card, *card.allocations]
        for variant in variants:
            for face in variant.faces:
                asset_id = _upload_asset_id_from_face(face)
                if not asset_id:
                    continue
                path_text = face.url[7:] if face.url.startswith("file://") else face.url
                path = Path(path_text)
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    raise ProjectFileError(
                        f"No se puede leer la imagen subida '{path}'."
                    ) from exc
                assets[asset_id] = {
                    "asset_id": asset_id,
                    "extension": face.extension,
                    "provider": "upload",
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }
    return [assets[key] for key in sorted(assets)]


def _materialise_embedded_upload_assets(
    payload: dict[str, Any],
) -> tuple[dict[str, str], int]:
    raw_assets = payload.get("embedded_upload_assets") or []
    if not isinstance(raw_assets, list):
        raise ProjectFileError(
            "Las imágenes embebidas del proyecto no son válidas."
        )

    materialised: dict[str, str] = {}
    uploads_dir = _project_uploads_dir()
    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise ProjectFileError(
                "Las imágenes embebidas del proyecto no son válidas."
            )
        asset_id = str(asset.get("asset_id") or "").strip()
        extension = str(asset.get("extension") or ".png").strip() or ".png"
        data_base64 = asset.get("data_base64")
        if not asset_id or not isinstance(data_base64, str):
            raise ProjectFileError(
                "Las imágenes embebidas del proyecto no son válidas."
            )
        try:
            data = base64.b64decode(data_base64.encode("ascii"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProjectFileError(
                "Una imagen embebida del proyecto no es válida."
            ) from exc
        if not extension.startswith("."):
            extension = f".{extension}"
        path = uploads_dir / asset_id
        if path.suffix != extension:
            path = uploads_dir / f"{asset_id}{extension}"
        path.write_bytes(data)
        materialised[asset_id] = str(path)
    return materialised, len(materialised)


def _inject_materialised_upload_paths(
    selection_data: dict[str, Any],
    asset_paths: dict[str, str],
) -> dict[str, Any]:
    copied = copy.deepcopy(selection_data)

    def patch_faces(container: dict[str, Any]) -> None:
        faces = container.get("faces")
        if not isinstance(faces, list):
            return
        for face in faces:
            if not isinstance(face, dict):
                continue
            if str(face.get("provider") or "") != "upload":
                continue
            asset_id = face.get("embedded_asset_id")
            if not isinstance(asset_id, str) or not asset_id:
                url = str(face.get("url") or "")
                if url.startswith("upload://"):
                    parsed = urlparse(url)
                    asset_id = parsed.netloc + parsed.path
            if isinstance(asset_id, str) and asset_id in asset_paths:
                face["url"] = asset_paths[asset_id]

    patch_faces(copied)
    allocations = copied.get("allocations")
    if isinstance(allocations, list):
        for allocation in allocations:
            if isinstance(allocation, dict):
                patch_faces(allocation)
    return copied


def analysis_signature_for_config(
    analysis_config: dict[str, Any],
    *,
    engine_version: str,
) -> str:
    payload = {
        "engine_version": engine_version,
        "decks": analysis_config.get("decks", []),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def project_selection_rows(
    resolved_cards: list[ResolvedCard],
) -> list[dict[str, Any]]:
    return [
        {
            "source": _source_to_dict(card.source),
            "selection": _resolved_to_dict(card),
        }
        for card in resolved_cards
    ]


def selection_fingerprint(
    resolved_cards: list[ResolvedCard],
) -> str:
    rows = project_selection_rows(resolved_cards)
    canonical = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def project_selection_summary(
    resolved_cards: list[ResolvedCard],
) -> dict[str, int]:
    manual_entries = 0
    mixed_entries = 0
    crop_adjustments = 0
    selected_faces = 0

    for card in resolved_cards:
        statuses = [card.status] + [
            variant.status for variant in card.allocations
        ]
        if any(
            "manual" in str(status or "").casefold()
            for status in statuses
        ):
            manual_entries += 1
        if card.allocations:
            mixed_entries += 1

        variants = card.allocations or [card]
        for variant in variants:
            selected_faces += len(variant.faces)
            crop_adjustments += sum(
                1
                for face in variant.faces
                if face.crop_shift_x
                or face.crop_shift_y
                or face.crop_mode not in {None, "auto"}
            )

    return {
        "entries": len(resolved_cards),
        "manual_entries": manual_entries,
        "mixed_entries": mixed_entries,
        "crop_adjustments": crop_adjustments,
        "selected_faces": selected_faces,
    }


def export_project(
    *,
    analysis_config: dict[str, Any],
    analysis_signature: str,
    resolved_cards: list[ResolvedCard],
    deck_summaries: list[dict[str, Any]],
    multi_deck_stats: dict[str, Any],
    deck_analysis_stats: list[dict[str, Any]],
    reviewed_decks: list[int],
    active_review_deck: int,
    review_selected_index: int,
    workspace_mode: str,
    review_only_problematic: bool,
    pdf_settings: dict[str, Any],
    build_version: str,
    project_revision: int = 0,
) -> bytes:
    rows = project_selection_rows(resolved_cards)
    embedded_upload_assets = _collect_embedded_upload_assets(resolved_cards)
    payload = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "build_version": build_version,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "project_revision": max(int(project_revision), 0),
        "analysis_config": copy.deepcopy(analysis_config),
        "analysis_signature": analysis_signature,
        "resolved_cards": rows,
        "selection_fingerprint": selection_fingerprint(
            resolved_cards
        ),
        "selection_summary": project_selection_summary(
            resolved_cards
        ),
        "embedded_upload_assets": embedded_upload_assets,
        "deck_summaries": copy.deepcopy(deck_summaries),
        "multi_deck_stats": copy.deepcopy(multi_deck_stats),
        "deck_analysis_stats": copy.deepcopy(deck_analysis_stats),
        "reviewed_decks": [
            int(value) for value in reviewed_decks
        ],
        "active_review_deck": int(active_review_deck),
        "review_selected_index": int(review_selected_index),
        "workspace_mode": str(workspace_mode),
        "review_only_problematic": bool(
            review_only_problematic
        ),
        "pdf_settings": copy.deepcopy(pdf_settings),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def import_project(
    data: bytes | str,
    *,
    engine_version: str,
) -> LoadedProject:
    raw_bytes = (
        data.encode("utf-8")
        if isinstance(data, str)
        else data
    )
    if len(raw_bytes) > MAX_PROJECT_BYTES:
        raise ProjectFileError(
            "El proyecto es demasiado grande."
        )
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ProjectFileError(
            "El archivo de proyecto no es un JSON válido."
        ) from exc

    if not isinstance(payload, dict):
        raise ProjectFileError(
            "El proyecto debe contener un objeto JSON."
        )

    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_PROJECT_SCHEMA_VERSIONS:
        raise ProjectFileError(
            "La versión del proyecto no es compatible."
        )

    analysis_config = payload.get("analysis_config")
    if not isinstance(analysis_config, dict):
        raise ProjectFileError(
            "El proyecto no contiene la configuración de mazos."
        )

    rows = payload.get("resolved_cards")
    if not isinstance(rows, list) or not rows:
        raise ProjectFileError(
            "El proyecto no contiene cartas resueltas."
        )

    asset_paths, embedded_upload_count = _materialise_embedded_upload_assets(payload)

    cards: list[DeckCard] = []
    resolved_cards: list[ResolvedCard] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProjectFileError(
                "Hay una carta de proyecto no válida."
            )
        source_data = row.get("source")
        selection_data = row.get("selection")
        if (
            not isinstance(source_data, dict)
            or not isinstance(selection_data, dict)
        ):
            raise ProjectFileError(
                "Falta información de una carta del proyecto."
            )

        source = _source_from_dict(source_data)
        cards.append(source)
        try:
            restored_selection = _inject_materialised_upload_paths(
                selection_data,
                asset_paths,
            )
            resolved_cards.append(
                _resolved_from_dict(
                    source,
                    restored_selection,
                    fallback_type_line=None,
                )
            )
        except ValueError as exc:
            raise ProjectFileError(str(exc)) from exc

    if schema_version >= 2:
        expected_fingerprint = payload.get(
            "selection_fingerprint"
        )
        if not isinstance(expected_fingerprint, str):
            raise ProjectFileError(
                "El proyecto no contiene la verificación "
                "de versiones seleccionadas."
            )
        actual_fingerprint = selection_fingerprint(
            resolved_cards
        )
        if actual_fingerprint != expected_fingerprint:
            raise ProjectFileError(
                "Las versiones guardadas no superan la "
                "verificación de integridad."
            )

    summaries = payload.get("deck_summaries") or []
    if not isinstance(summaries, list):
        raise ProjectFileError(
            "Los resúmenes de mazo no son válidos."
        )
    _validate_summary_ranges(summaries, len(cards))

    configured_decks = analysis_config.get("decks")
    if (
        not isinstance(configured_decks, list)
        or len(configured_decks) != len(summaries)
    ):
        raise ProjectFileError(
            "La configuración y los resúmenes contienen "
            "un número distinto de mazos."
        )

    signature = analysis_signature_for_config(
        analysis_config,
        engine_version=engine_version,
    )
    calculated_summary = project_selection_summary(
        resolved_cards
    )

    return LoadedProject(
        analysis_config=copy.deepcopy(analysis_config),
        analysis_signature=signature,
        cards=cards,
        resolved_cards=resolved_cards,
        deck_summaries=copy.deepcopy(summaries),
        multi_deck_stats=_dict_value(
            payload.get("multi_deck_stats")
        ),
        deck_analysis_stats=_list_of_dicts(
            payload.get("deck_analysis_stats")
        ),
        reviewed_decks=sorted(
            {
                int(value)
                for value in payload.get(
                    "reviewed_decks",
                    [],
                )
                if (
                    isinstance(value, int)
                    or str(value).isdigit()
                )
                and 0 <= int(value) < len(summaries)
            }
        ),
        active_review_deck=min(
            max(
                int(
                    payload.get(
                        "active_review_deck"
                    )
                    or 0
                ),
                0,
            ),
            max(len(summaries) - 1, 0),
        ),
        review_selected_index=min(
            max(
                int(
                    payload.get(
                        "review_selected_index"
                    )
                    or 0
                ),
                0,
            ),
            max(len(cards) - 1, 0),
        ),
        workspace_mode=(
            str(payload.get("workspace_mode"))
            if payload.get("workspace_mode")
            in {"Vista del mazo", "Editar cartas"}
            else "Vista del mazo"
        ),
        review_only_problematic=bool(
            payload.get(
                "review_only_problematic",
                False,
            )
        ),
        pdf_settings=_dict_value(
            payload.get("pdf_settings")
        ),
        project_revision=max(
            int(payload.get("project_revision") or 0),
            0,
        ),
        saved_at=(
            str(payload["saved_at"])
            if payload.get("saved_at")
            else None
        ),
        selection_summary=calculated_summary,
        embedded_upload_count=embedded_upload_count,
    )


def project_session_state(
    project: LoadedProject,
) -> dict[str, Any]:
    return {
        "analysis_config": copy.deepcopy(
            project.analysis_config
        ),
        "analysis_signature": project.analysis_signature,
        "cards": copy.deepcopy(project.cards),
        "resolved_cards": copy.deepcopy(
            project.resolved_cards
        ),
        "deck_summaries": copy.deepcopy(
            project.deck_summaries
        ),
        "multi_deck_stats": copy.deepcopy(
            project.multi_deck_stats
        ),
        "deck_analysis_stats": copy.deepcopy(
            project.deck_analysis_stats
        ),
        "reviewed_decks": list(
            project.reviewed_decks
        ),
        "active_review_deck": (
            project.active_review_deck
        ),
        "review_selected_index": (
            project.review_selected_index
        ),
        "review_only_problematic": (
            project.review_only_problematic
        ),
        "project_revision": project.project_revision,
        "app_step": 2,
        "workspace_mode": project.workspace_mode,
    }


def _source_to_dict(
    card: DeckCard,
) -> dict[str, Any]:
    return {
        "quantity": card.quantity,
        "name": card.name,
        "zone": card.zone,
        "set_code": card.set_code,
        "collector_number": card.collector_number,
    }


def _source_from_dict(
    data: dict[str, Any],
) -> DeckCard:
    try:
        quantity = int(data["quantity"])
        name = str(data["name"])
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProjectFileError(
            "La carta de origen no es válida."
        ) from exc

    if quantity < 1 or not name.strip():
        raise ProjectFileError(
            "La carta de origen no es válida."
        )

    return DeckCard(
        quantity=quantity,
        name=name,
        zone=str(
            data.get("zone") or "mainboard"
        ),
        set_code=(
            str(data["set_code"])
            if data.get("set_code")
            else None
        ),
        collector_number=(
            str(data["collector_number"])
            if data.get("collector_number")
            is not None
            else None
        ),
    )


def _dict_value(
    value: Any,
) -> dict[str, Any]:
    return (
        copy.deepcopy(value)
        if isinstance(value, dict)
        else {}
    )


def _list_of_dicts(
    value: Any,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        copy.deepcopy(item)
        for item in value
        if isinstance(item, dict)
    ]


def _validate_summary_ranges(
    summaries: list[dict[str, Any]],
    card_count: int,
) -> None:
    previous_end = 0
    for summary in summaries:
        if not isinstance(summary, dict):
            raise ProjectFileError(
                "Hay un resumen de mazo no válido."
            )
        start = int(
            summary.get(
                "start_index",
                previous_end,
            )
        )
        end = int(
            summary.get(
                "end_index",
                start,
            )
        )
        if (
            start != previous_end
            or end < start
            or end > card_count
        ):
            raise ProjectFileError(
                "Los límites de los mazos no son válidos."
            )
        previous_end = end

    if summaries and previous_end != card_count:
        raise ProjectFileError(
            "El proyecto no asigna todas las cartas "
            "a un mazo."
        )
