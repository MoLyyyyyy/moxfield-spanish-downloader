from __future__ import annotations

from .card_names import canonical_card_name
from .models import DeckCard, ResolvedCard


def source_printing_key(card: DeckCard) -> tuple[str, str, str, str]:
    """Stable identity for one deck entry/printing."""
    return (
        card.zone.casefold(),
        canonical_card_name(card.name).casefold(),
        (card.set_code or "").casefold(),
        str(card.collector_number or "").casefold(),
    )


def resolved_search_name(card: ResolvedCard) -> str:
    """Prefer a known Oracle/canonical name over a reskin display name."""
    metadata = card.scryfall_data or {}
    canonical = metadata.get("canonical_name")
    if isinstance(canonical, str) and canonical.strip():
        return canonical_card_name(canonical)

    is_scryfall_metadata = (
        card.provider == "scryfall"
        or "oracle_id" in metadata
        or "scryfall_uri" in metadata
        or metadata.get("object") == "card"
    )
    if is_scryfall_metadata:
        for key in ("name", "oracle_name"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return canonical_card_name(value)
    return canonical_card_name(card.source.name)


def candidate_search_name(candidate: dict, fallback: str) -> str:
    value = candidate.get("name") if isinstance(candidate, dict) else None
    if isinstance(value, str) and value.strip():
        return canonical_card_name(value)
    return canonical_card_name(fallback)
