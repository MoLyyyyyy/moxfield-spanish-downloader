from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.selections import (
    AllocationError,
    add_variant,
    effective_variants,
    remove_variant,
    set_allocation_quantities,
)


def resolved(name="Forest", quantity=4, url="https://x/a.png"):
    return ResolvedCard(
        source=DeckCard(quantity, name),
        status="Automática",
        provider="scryfall",
        type_line="Basic Land — Forest",
        printed_name=name,
        selected_set="m20",
        collector_number="279",
        faces=[ImageFace(name, url, ".png")],
    )


def test_add_variant_preserves_total_quantity() -> None:
    card = resolved()
    other = resolved(url="https://x/b.png")
    add_variant(card, other)
    variants = effective_variants(card)
    assert [variant.quantity for variant in variants] == [3, 1]


def test_allocation_quantities_can_be_changed() -> None:
    card = resolved()
    add_variant(card, resolved(url="https://x/b.png"))
    set_allocation_quantities(card, [2, 2])
    assert [variant.quantity for variant in effective_variants(card)] == [2, 2]


def test_invalid_allocation_sum_is_rejected() -> None:
    card = resolved()
    add_variant(card, resolved(url="https://x/b.png"))
    try:
        set_allocation_quantities(card, [1, 1])
    except AllocationError as exc:
        assert "suma" in str(exc)
    else:
        raise AssertionError("Expected AllocationError")


def test_remove_variant_returns_copies_to_primary() -> None:
    card = resolved()
    add_variant(card, resolved(url="https://x/b.png"))
    remove_variant(card, 1)
    variants = effective_variants(card)
    assert len(variants) == 1
    assert variants[0].quantity == 4
