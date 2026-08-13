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


from pathlib import Path

from mtg_downloader.persistence import _face_to_dict


def test_upload_face_urls_are_canonicalised(tmp_path: Path) -> None:
    path = tmp_path / "manual.png"
    path.write_bytes(b"manual-bytes")
    face = ImageFace("Manual", str(path), ".png", provider="upload")
    payload = _face_to_dict(face)
    assert payload["url"].startswith("upload://")
    assert payload["embedded_asset_id"] in payload["url"]
