from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.review import (
    candidate_label,
    is_problematic,
    preview_urls,
    problem_reasons,
    review_row,
)


def resolved(**overrides):
    values = {
        "source": DeckCard(
            quantity=1,
            name="Arcane Signet",
            set_code="tmc",
            collector_number="57",
        ),
        "status": "Misma impresión en español",
        "language": "es",
        "printed_name": "Sello Arcano",
        "selected_set": "tmc",
        "collector_number": "57",
        "faces": [ImageFace("Sello Arcano", "https://x/card.png", ".png")],
        "image_status": "highres_scan",
        "highres_image": True,
    }
    values.update(overrides)
    return ResolvedCard(**values)


def test_good_card_is_not_problematic() -> None:
    assert not is_problematic(resolved())


def test_problem_reasons_ignore_language_and_detect_real_issues() -> None:
    card = resolved(
        language="en",
        selected_set="cmm",
        collector_number="396",
        image_status="lowres",
        highres_image=False,
    )
    assert problem_reasons(card) == [
        "baja resolución",
        "cambió de edición",
    ]


def test_english_card_alone_is_not_problematic() -> None:
    card = resolved(language="en")
    assert not is_problematic(card)


def test_preview_urls_supports_double_faced_cards() -> None:
    data = {
        "card_faces": [
            {"image_uris": {"normal": "https://x/front.jpg"}},
            {"image_uris": {"normal": "https://x/back.jpg"}},
        ]
    }
    assert preview_urls(data) == [
        "https://x/front.jpg",
        "https://x/back.jpg",
    ]


def test_candidate_label_contains_printing_language_and_quality() -> None:
    label = candidate_label(
        {
            "printed_name": "Sello Arcano",
            "set": "cmm",
            "collector_number": "396",
            "lang": "es",
            "image_status": "highres_scan",
            "highres_image": True,
            "released_at": "2026-07-01",
        }
    )
    assert "CMM 396" in label
    assert "ES" in label
    assert "alta resolución" in label
    assert "2026-07-01" in label


def test_review_row_marks_correct_card() -> None:
    row = review_row(3, resolved())
    assert row["índice"] == 3
    assert row["revisión"] == "correcta"


def test_scryfall_filters_preserve_ranked_order() -> None:
    from mtg_downloader.review import filter_scryfall_alternatives

    candidates = [
        {
            "id": "new-borderless",
            "set": "ltr",
            "released_at": "2026-01-01",
            "artist": "John Howe",
            "border_color": "borderless",
        },
        {
            "id": "old-normal",
            "set": "ltr",
            "released_at": "2024-01-01",
            "artist": "Alan Lee",
            "border_color": "black",
        },
        {
            "id": "other-set",
            "set": "cmm",
            "released_at": "2025-01-01",
            "artist": "John Howe",
            "border_color": "black",
        },
    ]

    assert [
        item["id"]
        for item in filter_scryfall_alternatives(
            candidates,
            set_code="LTR",
        )
    ] == ["new-borderless", "old-normal"]
    assert [
        item["id"]
        for item in filter_scryfall_alternatives(
            candidates,
            artist="howe",
            treatment="borderless",
        )
    ] == ["new-borderless"]
    assert [
        item["id"]
        for item in filter_scryfall_alternatives(
            candidates,
            year="2024",
            treatment="normal",
        )
    ] == ["old-normal"]
