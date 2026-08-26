from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

DEFAULT_DECK_SETTINGS: dict[str, Any] = {
    "decklist": "",
    "deck_name": "",
    "preferred_image_source": "scryfall",
    "preferred_language": "es",
    "allow_language_fallback": True,
    "resolution_mode": "exact_first",
    "quality_mode": "highres_only",
    "image_quality": "png",
    "include_sideboard": False,
    "include_maybeboard": False,
}

AUTOMATIC_MPCFILL_MINIMUM_DPI = 800


def bulk_scryfall_settings(action: str) -> tuple[bool, str, str]:
    return {
        "Español y después inglés": (True, "flexible", "highres_only"),
        "Máxima calidad disponible": (True, "flexible", "highres_only"),
        "Respetar impresión exacta": (True, "exact_only", "highres_only"),
    }[action]


def normalise_deck_config(
    value: Mapping[str, Any] | None,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    config = dict(DEFAULT_DECK_SETTINGS)
    if fallback:
        config.update(dict(fallback))
    if value:
        config.update(dict(value))

    source = str(config.get("preferred_image_source", "scryfall"))
    config["preferred_image_source"] = (
        source if source in {"scryfall", "mpcfill"} else "scryfall"
    )

    language = str(config.get("preferred_language", "es"))
    config["preferred_language"] = (
        language if language in {"es", "en"} else "es"
    )

    resolution = str(config.get("resolution_mode", "exact_first"))
    config["resolution_mode"] = (
        resolution
        if resolution in {"exact_first", "exact_only", "flexible"}
        else "exact_first"
    )

    config["quality_mode"] = "highres_only"

    image_quality = str(config.get("image_quality", "png"))
    config["image_quality"] = (
        image_quality if image_quality in {"png", "large"} else "png"
    )

    config["decklist"] = str(config.get("decklist", ""))
    config["deck_name"] = str(config.get("deck_name", "")).strip()
    config["allow_language_fallback"] = (
        config["preferred_language"] == "es"
    )
    config["include_sideboard"] = bool(
        config.get("include_sideboard", False)
    )
    config["include_maybeboard"] = bool(
        config.get("include_maybeboard", False)
    )
    return config


def normalise_deck_active_index(
    value: Any,
    deck_count: int,
) -> int:
    """Convert legacy selector values such as 'Mazo 1' to an index."""
    if deck_count < 1:
        return 0

    index = 0
    if isinstance(value, bool):
        index = int(value)
    elif isinstance(value, int):
        index = value
    elif isinstance(value, float) and value.is_integer():
        index = int(value)
    elif isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lstrip("-").isdigit():
            index = int(cleaned)
        else:
            match = re.match(
                r"(?i)^mazo\s+(\d+)(?:\s*·.*)?$",
                cleaned,
            )
            if match:
                index = int(match.group(1)) - 1

    return min(max(index, 0), deck_count - 1)


def deck_configs_from_analysis_config(
    analysis_config: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Load the new per-deck format and migrate older global configs."""
    raw = dict(analysis_config or {})
    configured_decks = raw.get("decks")
    if isinstance(configured_decks, list) and configured_decks:
        return [
            normalise_deck_config(
                item if isinstance(item, Mapping) else None
            )
            for item in configured_decks
        ]

    global_fallback = {
        key: raw.get(key, default)
        for key, default in DEFAULT_DECK_SETTINGS.items()
        if key != "decklist"
    }
    decklists = raw.get("decklists")
    if not isinstance(decklists, list) or not decklists:
        decklists = [raw.get("decklist", "")]

    return [
        normalise_deck_config(
            {"decklist": str(decklist)},
            fallback=global_fallback,
        )
        for decklist in decklists
    ]


def public_deck_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    normalised = normalise_deck_config(config)
    return {
        key: normalised[key]
        for key in DEFAULT_DECK_SETTINGS
        if key != "decklist"
    }


def deck_settings_label(config: Mapping[str, Any]) -> str:
    normalised = normalise_deck_config(config)
    source = (
        "MPCFill"
        if normalised["preferred_image_source"] == "mpcfill"
        else "Scryfall"
    )
    language = (
        "español"
        if normalised["preferred_language"] == "es"
        else "inglés"
    )
    fallback = (
        "con respaldo"
        if normalised["allow_language_fallback"]
        else "sin respaldo"
    )
    return f"{source} · {language} · {fallback}"


def deck_position_for_card(
    card_index: int,
    summaries: list[dict[str, Any]],
) -> int:
    for position, summary in enumerate(summaries):
        start = int(summary.get("start_index", 0))
        end = int(summary.get("end_index", start))
        if start <= card_index < end:
            return position
    return 0


def indices_for_deck(
    deck_position: int,
    summaries: list[dict[str, Any]],
) -> list[int]:
    if not summaries:
        return []
    position = min(max(deck_position, 0), len(summaries) - 1)
    summary = summaries[position]
    start = int(summary.get("start_index", 0))
    end = int(summary.get("end_index", start))
    return list(range(start, end))
