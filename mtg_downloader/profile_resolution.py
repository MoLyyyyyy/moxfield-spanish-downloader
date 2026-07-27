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
    ) -> ResolvedCard:
        ...


def resolve_with_language_fallback(
    client: CardResolver,
    card: DeckCard,
    *,
    allow_english: bool,
    allow_english_if_missing: bool,
    resolution_mode: str,
    quality_mode: str,
) -> ResolvedCard:
    """Resolve a card while remaining compatible with older resolver versions."""
    result = client.resolve(
        card,
        allow_english_fallback=allow_english,
        resolution_mode=resolution_mode,
        quality_mode=quality_mode,
    )

    if (
        allow_english
        or not allow_english_if_missing
        or result.faces
    ):
        return result

    fallback = client.resolve(
        card,
        allow_english_fallback=True,
        resolution_mode=resolution_mode,
        quality_mode=quality_mode,
    )
    if fallback.faces and (fallback.language or "").casefold() == "en":
        fallback.status = (
            f"{fallback.status} · Inglés como último recurso"
        )
    return fallback if fallback.faces else result
