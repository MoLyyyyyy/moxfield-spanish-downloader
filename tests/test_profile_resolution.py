from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.profile_resolution import resolve_with_language_fallback


class LegacyResolver:
    def __init__(self, *, spanish_available: bool) -> None:
        self.spanish_available = spanish_available
        self.calls: list[bool] = []

    def resolve(
        self,
        card,
        allow_english_fallback=True,
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
    ):
        self.calls.append(allow_english_fallback)
        if self.spanish_available:
            return ResolvedCard(
                source=card,
                status="Otra impresión en español",
                language="es",
                faces=[ImageFace("ES", "https://example.com/es.jpg", ".jpg")],
            )
        if allow_english_fallback:
            return ResolvedCard(
                source=card,
                status="Otra impresión en inglés",
                language="en",
                faces=[ImageFace("EN", "https://example.com/en.jpg", ".jpg")],
            )
        return ResolvedCard(
            source=card,
            status="No encontrada",
            error="No existe imagen en español.",
        )


def test_fallback_works_with_legacy_resolver_signature() -> None:
    client = LegacyResolver(spanish_available=False)
    result = resolve_with_language_fallback(
        client,
        DeckCard(1, "Test Card"),
        allow_english=False,
        allow_english_if_missing=True,
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
    )

    assert result.language == "en"
    assert client.calls == [False, True]
    assert "último recurso" in result.status


def test_fallback_is_not_used_when_spanish_exists() -> None:
    client = LegacyResolver(spanish_available=True)
    result = resolve_with_language_fallback(
        client,
        DeckCard(1, "Test Card"),
        allow_english=False,
        allow_english_if_missing=True,
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
    )

    assert result.language == "es"
    assert client.calls == [False]
