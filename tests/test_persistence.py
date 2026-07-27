from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.persistence import export_selection_config, import_selection_config
from mtg_downloader.selections import add_variant


def card(url="https://x/a.png"):
    return ResolvedCard(
        source=DeckCard(3, "Forest", set_code="m20", collector_number="279"),
        status="Selección manual",
        provider="scryfall",
        type_line="Basic Land — Forest",
        language="es",
        printed_name="Bosque",
        selected_set="m20",
        collector_number="279",
        faces=[ImageFace("Bosque", url, ".png")],
    )


def test_config_roundtrip_preserves_selection_and_allocations() -> None:
    selected = card()
    add_variant(selected, card("https://x/b.png"))
    payload = export_selection_config([selected], deck_signature="abc")
    restored, warnings = import_selection_config(payload.decode(), [card()])
    assert not warnings
    assert len(restored[0].allocations) == 2
    assert sum(item.quantity for item in restored[0].allocations) == 3


def test_unmatched_entries_are_reported() -> None:
    payload = export_selection_config([card()], deck_signature="abc")
    other = ResolvedCard(source=DeckCard(1, "Island"), status="ok")
    _, warnings = import_selection_config(payload.decode(), [other])
    assert warnings
