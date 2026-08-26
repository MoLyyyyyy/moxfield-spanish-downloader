from mtg_downloader.backs import neutral_back, standard_magic_back
from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.validation import validate_deck


def test_neutral_back_contains_png() -> None:
    back = neutral_back()
    assert back.embedded_data.startswith(b"\x89PNG")


def test_standard_back_has_scryfall_url() -> None:
    back = standard_magic_back()
    assert back.face is not None
    assert "backs.scryfall.io" in back.face.url


def test_validation_counts_cards_and_backs() -> None:
    card = ResolvedCard(
        source=DeckCard(3, "Forest"),
        status="ok",
        faces=[ImageFace("Forest", "https://x/a.png", ".png")],
    )
    result = validate_deck([card], back_spec=neutral_back())
    assert result.expected_cards == 3
    assert result.expected_back_files == 3
    assert result.can_generate


def test_missing_image_blocks_generation() -> None:
    card = ResolvedCard(source=DeckCard(1, "Missing"), status="Sin imagen")
    result = validate_deck([card])
    assert not result.can_generate


def test_low_resolution_image_blocks_generation() -> None:
    card = ResolvedCard(
        source=DeckCard(1, "Lowres"),
        status="lowres",
        faces=[ImageFace("Lowres", "https://x/lowres.jpg", ".jpg")],
        image_status="lowres",
        highres_image=False,
    )

    result = validate_deck([card])

    assert not result.can_generate
    assert result.lowres_entries == ("Lowres",)



def test_duplicate_warning_can_be_disabled_for_multiple_decks() -> None:
    card_one = ResolvedCard(
        source=DeckCard(1, "Sol Ring"),
        status="ok",
        faces=[ImageFace("Sol Ring", "fake", ".png")],
    )
    card_two = ResolvedCard(
        source=DeckCard(1, "Sol Ring"),
        status="ok",
        faces=[ImageFace("Sol Ring", "fake", ".png")],
    )

    summary = validate_deck(
        [card_one, card_two],
        warn_duplicates=False,
    )

    assert not summary.duplicate_entries
    assert not any("duplicadas" in warning for warning in summary.warnings)
