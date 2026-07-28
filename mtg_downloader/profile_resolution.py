from __future__ import annotations

from typing import Protocol

from .models import DeckCard, ResolvedCard


class CardResolver(Protocol):
    def resolve(
        self,
        card: DeckCard,
        allow_english_fallback: bool = True,
        resolution_mode: str = "exact_first",
        quality_mode: str = "prefer_highres",
        **kwargs: object,
    ) -> ResolvedCard:
        ...


def resolve_with_language_fallback(
    client: CardResolver,
    card: DeckCard,
    *,
    preferred_language: str,
    allow_language_fallback: bool,
    resolution_mode: str,
    quality_mode: str,
) -> ResolvedCard:
    """Resolve using an explicit primary language and optional fallback."""
    try:
        return client.resolve(
            card,
            preferred_language=preferred_language,
            allow_language_fallback=allow_language_fallback,
            resolution_mode=resolution_mode,
            quality_mode=quality_mode,
        )
    except TypeError as exc:
        if "preferred_language" not in str(exc):
            raise

    # Compatibility for a stale resolver during a Streamlit rolling restart.
    # Older clients only support Spanish-first resolution.
    if preferred_language == "es":
        return client.resolve(
            card,
            allow_english_fallback=allow_language_fallback,
            resolution_mode=resolution_mode,
            quality_mode=quality_mode,
        )

    fallback = client.resolve(
        card,
        allow_english_fallback=True,
        resolution_mode=resolution_mode,
        quality_mode=quality_mode,
    )
    return fallback
