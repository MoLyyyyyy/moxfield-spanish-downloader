from __future__ import annotations

from typing import Any

from .models import ResolvedCard


def problem_reasons(card: ResolvedCard) -> list[str]:
    from .selections import effective_variants

    reasons: list[str] = []
    variants = effective_variants(card)

    if any(not variant.faces for variant in variants):
        reasons.append("sin imagen")
    if any(
        variant.image_status == "lowres" or variant.highres_image is False
        for variant in variants
    ):
        reasons.append("baja resolución")

    source_set = (card.source.set_code or "").casefold()
    source_number = str(card.source.collector_number or "").casefold()
    primary = variants[0]
    selected_set = (primary.selected_set or "").casefold()
    selected_number = str(primary.collector_number or "").casefold()

    if (
        primary.provider != "mpcfill"
        and primary.status != "Selección manual"
        and source_set
        and source_number
        and selected_set
        and selected_number
        and (source_set != selected_set or source_number != selected_number)
    ):
        reasons.append("cambió de edición")

    return reasons


def is_problematic(card: ResolvedCard) -> bool:
    return bool(problem_reasons(card))


def candidate_key(candidate: dict[str, Any]) -> str:
    value = candidate.get("id")
    if value:
        return str(value)

    return "|".join(
        [
            str(candidate.get("lang") or ""),
            str(candidate.get("set") or ""),
            str(candidate.get("collector_number") or ""),
            str(candidate.get("name") or ""),
        ]
    )


def candidate_label(candidate: dict[str, Any]) -> str:
    name = (
        candidate.get("printed_name")
        or candidate.get("name")
        or "Carta sin nombre"
    )
    set_code = str(candidate.get("set") or "?").upper()
    collector = str(candidate.get("collector_number") or "?")
    language = str(candidate.get("lang") or "?").upper()
    quality = (
        "alta resolución"
        if candidate.get("image_status") == "highres_scan"
        or candidate.get("highres_image") is True
        else str(candidate.get("image_status") or "calidad desconocida")
    )
    released_at = str(candidate.get("released_at") or "").strip()
    release_label = (
        f" · {released_at}"
        if released_at
        else ""
    )
    return (
        f"{name} · {set_code} {collector} · {language}"
        f"{release_label} · {quality}"
    )



def filter_scryfall_alternatives(
    candidates: list[dict[str, Any]],
    *,
    set_code: str = "",
    year: str = "",
    artist: str = "",
    treatment: str = "all",
) -> list[dict[str, Any]]:
    """Filter already-ranked Scryfall candidates without changing their order."""
    expected_set = set_code.strip().casefold()
    expected_year = year.strip()
    expected_artist = artist.strip().casefold()
    if treatment not in {"all", "normal", "borderless", "showcase", "retro"}:
        raise ValueError(f"Tratamiento desconocido: {treatment}")

    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        if expected_set and str(candidate.get("set") or "").casefold() != expected_set:
            continue
        released_at = str(candidate.get("released_at") or "")
        if expected_year and not released_at.startswith(f"{expected_year}-"):
            continue
        if expected_artist and expected_artist not in str(
            candidate.get("artist") or ""
        ).casefold():
            continue
        if treatment != "all" and _candidate_treatment(candidate) != treatment:
            continue
        filtered.append(candidate)
    return filtered


def _candidate_treatment(candidate: dict[str, Any]) -> str:
    frame_effects = {
        str(value).casefold()
        for value in candidate.get("frame_effects") or []
    }
    promo_types = {
        str(value).casefold()
        for value in candidate.get("promo_types") or []
    }
    if (
        candidate.get("border_color") == "borderless"
        or candidate.get("full_art") is True
        or "extendedart" in frame_effects
    ):
        return "borderless"
    if "showcase" in frame_effects or "showcase" in promo_types:
        return "showcase"
    if (
        "retro" in frame_effects
        or "oldframe" in frame_effects
        or str(candidate.get("frame") or "") in {"1993", "1997"}
    ):
        return "retro"
    return "normal"

def preview_urls(candidate: dict[str, Any] | None) -> list[str]:
    if not isinstance(candidate, dict):
        return []

    urls: list[str] = []
    image_uris = candidate.get("image_uris")
    if isinstance(image_uris, dict):
        url = _first_image_url(image_uris)
        if url:
            urls.append(url)
        return urls

    faces = candidate.get("card_faces")
    if isinstance(faces, list):
        for face in faces:
            if not isinstance(face, dict):
                continue
            face_uris = face.get("image_uris")
            if not isinstance(face_uris, dict):
                continue
            url = _first_image_url(face_uris)
            if url:
                urls.append(url)

    return urls


def review_row(index: int, card: ResolvedCard) -> dict[str, str | int]:
    reasons = problem_reasons(card)
    return {
        "índice": index,
        "cantidad": card.source.quantity,
        "carta": card.source.name,
        "impresión solicitada": _printing(
            card.source.set_code,
            card.source.collector_number,
        ),
        "impresión elegida": _printing(
            card.selected_set,
            card.collector_number,
        ),
        "idioma": card.language or "",
        "calidad": card.image_status or "",
        "estado": card.status,
        "revisión": ", ".join(reasons) if reasons else "correcta",
    }


def _first_image_url(image_uris: dict[str, Any]) -> str | None:
    for key in ("normal", "large", "png", "small"):
        value = image_uris.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _printing(set_code: str | None, collector: str | None) -> str:
    if not set_code and not collector:
        return ""
    return f"{(set_code or '?').upper()} {collector or '?'}"
