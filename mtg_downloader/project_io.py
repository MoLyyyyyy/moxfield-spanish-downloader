from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import DeckCard, ResolvedCard
from .persistence import _resolved_from_dict, _resolved_to_dict

PROJECT_SCHEMA_VERSION = 2
SUPPORTED_PROJECT_SCHEMA_VERSIONS = {1, 2}
MAX_PROJECT_BYTES = 25_000_000


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
            resolved_cards.append(
                _resolved_from_dict(
                    source,
                    selection_data,
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
