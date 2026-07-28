from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.profile_resolution import resolve_with_language_fallback


class ModernResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def resolve(
        self,
        card,
        preferred_language=None,
        allow_language_fallback=None,
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
        **kwargs,
    ):
        self.calls.append(
            (preferred_language, bool(allow_language_fallback))
        )
        return ResolvedCard(
            source=card,
            status="Idioma elegido",
            language=preferred_language,
            faces=[
                ImageFace(
                    preferred_language.upper(),
                    "https://example.com/card.jpg",
                    ".jpg",
                )
            ],
        )


def test_explicit_language_is_forwarded() -> None:
    client = ModernResolver()
    result = resolve_with_language_fallback(
        client,
        DeckCard(1, "Test Card"),
        preferred_language="en",
        allow_language_fallback=True,
        resolution_mode="exact_first",
        quality_mode="prefer_highres",
    )

    assert result.language == "en"
    assert client.calls == [("en", True)]
