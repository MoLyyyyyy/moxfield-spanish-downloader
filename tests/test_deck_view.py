from mtg_downloader.deck_view import (
    category_key,
    gallery_printing_label,
    group_deck,
)
from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard


def resolved(
    name: str,
    type_line: str | None,
    *,
    zone: str = "mainboard",
    quantity: int = 1,
    provider: str = "scryfall",
) -> ResolvedCard:
    return ResolvedCard(
        source=DeckCard(quantity, name, zone=zone),
        status="ok",
        provider=provider,
        type_line=type_line,
        selected_set="abc",
        collector_number="12",
        language="es",
    )


def test_category_uses_zone_before_type() -> None:
    card = resolved(
        "Commander",
        "Legendary Creature — Human",
        zone="commanders",
    )
    assert category_key(card) == "commanders"


def test_artifact_creature_is_grouped_as_creature() -> None:
    card = resolved("Robot", "Artifact Creature — Construct")
    assert category_key(card) == "creatures"


def test_group_deck_uses_moxfield_like_order() -> None:
    cards = [
        resolved("Forest", "Basic Land — Forest"),
        resolved("Elf", "Creature — Elf"),
        resolved("Sol Ring", "Artifact"),
        resolved(
            "Commander",
            "Legendary Creature — Human",
            zone="commanders",
        ),
    ]
    assert [group.label for group in group_deck(cards)] == [
        "Comandante",
        "Criaturas",
        "Artefactos",
        "Tierras",
    ]


def test_category_quantity_counts_copies() -> None:
    category = group_deck(
        [
            resolved("Forest", "Basic Land — Forest", quantity=27),
            resolved("Island", "Basic Land — Island", quantity=3),
        ]
    )[0]
    assert category.label == "Tierras"
    assert category.quantity == 30


def test_gallery_label_identifies_mpcfill() -> None:
    card = resolved("Sol Ring", "Artifact", provider="mpcfill")
    assert gallery_printing_label(card).startswith("MPCFill")


def test_group_deck_preserves_external_indices() -> None:
    cards = [resolved("Elf", "Creature — Elf"), resolved("Forest", "Land")]
    groups = group_deck(cards, indices=[5, 9])
    assert groups[0].cards[0][0] == 5


def test_gallery_status_for_mpcfill() -> None:
    from mtg_downloader.deck_view import gallery_status_label
    card = resolved("Sol Ring", "Artifact", provider="mpcfill")
    card.faces = [ImageFace("Sol Ring", "https://x/a.png", ".png")]
    assert "MPCFill" in gallery_status_label(card)



def test_gallery_label_identifies_magiccardsinfo() -> None:
    card = resolved("Sol Ring", "Artifact", provider="magiccardsinfo")
    assert gallery_printing_label(card).startswith("MagicCards.info")
