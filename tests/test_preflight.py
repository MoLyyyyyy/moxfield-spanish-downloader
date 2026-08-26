from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
from mtg_downloader.preflight import build_preflight_issues, estimate_pdf_size_bytes


def test_preflight_detects_fallback_set_mismatch_and_unreviewed_deck() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(1, "Arcane Signet", set_code="cmm"),
            status="Encontrada",
            language="en",
            selected_set="clb",
            faces=[ImageFace("Arcane Signet", "https://example.com/a.png", ".png")],
            highres_image=False,
            image_status="lowres",
        )
    ]
    summaries = [
        {
            "name": "Deck",
            "start_index": 0,
            "end_index": 1,
        }
    ]
    configs = [
        {
            "preferred_language": "es",
            "resolution_mode": "exact_only",
            "quality_mode": "highres_only",
            "image_quality": "png",
        }
    ]

    issues = build_preflight_issues(cards, summaries, configs, set())
    descriptions = {issue.issue for issue in issues}

    assert "El mazo todavía no se ha marcado como revisado." in descriptions
    assert "Se utilizó el idioma de respaldo." in descriptions
    assert "La versión seleccionada es de baja resolución." in descriptions
    assert any(
        issue.severity == "Error"
        and issue.issue == "La versión seleccionada es de baja resolución."
        for issue in issues
    )
    assert "La impresión elegida no pertenece a la edición solicitada." in descriptions
    assert any(issue.severity == "Error" for issue in issues)


def test_pdf_size_estimate_is_positive_and_depends_on_format() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(10, "Forest"),
            status="ok",
            faces=[ImageFace("Forest", "https://example.com/f.png", ".png")],
        )
    ]
    summaries = [{"start_index": 0, "end_index": 1}]
    png = estimate_pdf_size_bytes(
        cards,
        [{"image_quality": "png"}],
        summaries,
        include_backs=True,
    )
    jpg = estimate_pdf_size_bytes(
        cards,
        [{"image_quality": "large"}],
        summaries,
        include_backs=True,
    )
    assert png > jpg > 0


def test_mpcfill_selection_does_not_trigger_false_official_set_mismatch() -> None:
    cards = [
        ResolvedCard(
            source=DeckCard(1, "Arcane Signet", set_code="cmm"),
            status="Diseño MPCFill",
            provider="mpcfill",
            language="es",
            selected_set="MPCFILL",
            faces=[
                ImageFace(
                    "Arcane Signet",
                    "https://example.com/mpc.jpg",
                    ".jpg",
                    provider="mpcfill",
                    crop_mode="auto",
                )
            ],
            highres_image=True,
        )
    ]
    issues = build_preflight_issues(
        cards,
        [{"name": "Deck", "start_index": 0, "end_index": 1}],
        [{"preferred_language": "es", "resolution_mode": "exact_only"}],
        {0},
    )

    assert not any("edición solicitada" in issue.issue for issue in issues)
