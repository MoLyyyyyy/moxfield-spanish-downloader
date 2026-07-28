from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .card_names import is_multi_face_name
from .models import ResolvedCard
from .selections import effective_variants


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    severity: str
    deck_position: int
    card_index: int | None
    deck_name: str
    card_name: str
    issue: str


def build_preflight_issues(
    cards: list[ResolvedCard],
    summaries: list[dict[str, Any]],
    deck_configs: list[dict[str, Any]],
    reviewed_decks: set[int],
) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    for deck_position, summary in enumerate(summaries):
        deck_name = str(summary.get("name") or f"Mazo {deck_position + 1}")
        if deck_position not in reviewed_decks:
            issues.append(
                PreflightIssue(
                    severity="Aviso",
                    deck_position=deck_position,
                    card_index=None,
                    deck_name=deck_name,
                    card_name="—",
                    issue="El mazo todavía no se ha marcado como revisado.",
                )
            )

        config = deck_configs[deck_position] if deck_position < len(deck_configs) else {}
        preferred_language = str(config.get("preferred_language") or "")
        resolution_mode = str(config.get("resolution_mode") or "exact_first")
        start = int(summary.get("start_index") or 0)
        end = int(summary.get("end_index") or start)
        for index in range(start, min(end, len(cards))):
            card = cards[index]
            variants = effective_variants(card)
            if not variants or any(not variant.faces for variant in variants):
                issues.append(
                    _card_issue(
                        "Error",
                        deck_position,
                        index,
                        deck_name,
                        card,
                        "Falta al menos una imagen.",
                    )
                )
                continue

            if any(
                variant.image_status == "lowres"
                or variant.highres_image is False
                for variant in variants
            ):
                issues.append(
                    _card_issue(
                        "Aviso",
                        deck_position,
                        index,
                        deck_name,
                        card,
                        "La versión seleccionada es de baja resolución.",
                    )
                )

            languages = {
                str(variant.language or "")
                for variant in variants
                if variant.language
            }
            if (
                preferred_language
                and languages
                and any(language != preferred_language for language in languages)
            ):
                issues.append(
                    _card_issue(
                        "Información",
                        deck_position,
                        index,
                        deck_name,
                        card,
                        "Se utilizó el idioma de respaldo.",
                    )
                )

            requested_set = (card.source.set_code or "").casefold()
            official_selected_sets = {
                str(variant.selected_set or "").casefold()
                for variant in variants
                if variant.provider != "mpcfill" and variant.selected_set
            }
            if (
                requested_set
                and official_selected_sets
                and any(
                    selected_set != requested_set
                    for selected_set in official_selected_sets
                )
            ):
                severity = "Error" if resolution_mode == "exact_only" else "Aviso"
                issues.append(
                    _card_issue(
                        severity,
                        deck_position,
                        index,
                        deck_name,
                        card,
                        "La impresión elegida no pertenece a la edición solicitada.",
                    )
                )

            if _expects_multiple_physical_faces(card) and any(
                len(variant.faces) < 2 for variant in variants
            ):
                issues.append(
                    _card_issue(
                        "Error",
                        deck_position,
                        index,
                        deck_name,
                        card,
                        "La carta de doble cara no conserva todas sus caras físicas.",
                    )
                )

            if any(
                face.provider == "mpcfill"
                and (
                    face.crop_mode not in {None, "auto"}
                    or face.crop_shift_x
                    or face.crop_shift_y
                )
                for variant in variants
                for face in variant.faces
            ):
                issues.append(
                    _card_issue(
                        "Información",
                        deck_position,
                        index,
                        deck_name,
                        card,
                        "Tiene un ajuste manual de recorte MPCFill.",
                    )
                )
    return issues


def estimate_pdf_size_bytes(
    cards: list[ResolvedCard],
    deck_configs: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    *,
    include_backs: bool,
) -> int:
    """Conservative, explicitly approximate estimate before image download."""
    total = 0
    for deck_position, summary in enumerate(summaries):
        config = deck_configs[deck_position] if deck_position < len(deck_configs) else {}
        image_quality = str(config.get("image_quality") or "png")
        bytes_per_face = 1_350_000 if image_quality == "png" else 420_000
        start = int(summary.get("start_index") or 0)
        end = int(summary.get("end_index") or start)
        for card in cards[start:end]:
            face_count = max(
                [len(variant.faces) for variant in effective_variants(card)] or [1]
            )
            total += card.source.quantity * bytes_per_face * max(face_count, 1)
            if include_backs and face_count == 1:
                total += card.source.quantity * 45_000
    return int(total * 0.72 + 1_500_000)


def issue_rows(issues: list[PreflightIssue]) -> list[dict[str, Any]]:
    return [
        {
            "Nivel": issue.severity,
            "Mazo": issue.deck_name,
            "Carta": issue.card_name,
            "Incidencia": issue.issue,
        }
        for issue in issues
    ]


def _card_issue(
    severity: str,
    deck_position: int,
    card_index: int,
    deck_name: str,
    card: ResolvedCard,
    issue: str,
) -> PreflightIssue:
    return PreflightIssue(
        severity=severity,
        deck_position=deck_position,
        card_index=card_index,
        deck_name=deck_name,
        card_name=card.source.name,
        issue=issue,
    )


def _expects_multiple_physical_faces(card: ResolvedCard) -> bool:
    metadata = card.scryfall_data or {}
    layout = str(metadata.get("layout") or "")
    if layout in {
        "transform",
        "modal_dfc",
        "reversible_card",
        "double_faced_token",
    }:
        return True
    faces = metadata.get("card_faces")
    if isinstance(faces, list):
        physical_images = sum(
            1
            for face in faces
            if isinstance(face, dict) and isinstance(face.get("image_uris"), dict)
        )
        if physical_images > 1:
            return True
    return is_multi_face_name(card.source.name) and len(card.faces) > 1
