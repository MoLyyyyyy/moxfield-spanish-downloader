from mtg_downloader.deck_workflow import (
    AUTOMATIC_MPCFILL_MINIMUM_DPI,
    bulk_scryfall_settings,
    deck_configs_from_analysis_config,
    deck_position_for_card,
    deck_settings_label,
    indices_for_deck,
    normalise_deck_active_index,
    normalise_deck_config,
)


def test_old_global_config_is_migrated_to_each_deck() -> None:
    configs = deck_configs_from_analysis_config(
        {
            "decklists": ["1 Card A", "1 Card B"],
            "preferred_image_source": "mpcfill",
            "preferred_language": "en",
        }
    )

    assert len(configs) == 2
    assert all(config["preferred_image_source"] == "mpcfill" for config in configs)
    assert all(config["preferred_language"] == "en" for config in configs)


def test_new_deck_configs_keep_independent_settings() -> None:
    configs = deck_configs_from_analysis_config(
        {
            "decks": [
                {
                    "decklist": "1 Card A",
                    "preferred_language": "es",
                },
                {
                    "decklist": "1 Card B",
                    "preferred_language": "en",
                    "preferred_image_source": "mpcfill",
                },
            ]
        }
    )

    assert configs[0]["preferred_language"] == "es"
    assert configs[0]["preferred_image_source"] == "scryfall"
    assert configs[1]["preferred_language"] == "en"
    assert configs[1]["preferred_image_source"] == "mpcfill"


def test_card_indices_are_scoped_to_their_deck() -> None:
    summaries = [
        {"start_index": 0, "end_index": 3},
        {"start_index": 3, "end_index": 5},
    ]

    assert indices_for_deck(0, summaries) == [0, 1, 2]
    assert indices_for_deck(1, summaries) == [3, 4]
    assert deck_position_for_card(4, summaries) == 1


def test_settings_label_describes_one_deck() -> None:
    assert deck_settings_label(
        {
            "preferred_image_source": "mpcfill",
            "preferred_language": "en",
            "allow_language_fallback": False,
        }
    ) == "MPCFill · inglés · sin respaldo"



def test_normalise_deck_active_index_migrates_legacy_labels() -> None:
    assert normalise_deck_active_index("Mazo 1", 4) == 0
    assert normalise_deck_active_index("Mazo 3 · Sauron", 4) == 2
    assert normalise_deck_active_index("2", 4) == 2
    assert normalise_deck_active_index(3, 4) == 3


def test_normalise_deck_active_index_clamps_invalid_values() -> None:
    assert normalise_deck_active_index("desconocido", 3) == 0
    assert normalise_deck_active_index(99, 3) == 2
    assert normalise_deck_active_index(-4, 3) == 0
    assert normalise_deck_active_index("Mazo 1", 0) == 0


def test_automatic_search_always_requires_high_resolution() -> None:
    config = normalise_deck_config({"quality_mode": "allow_lowres"})

    assert config["quality_mode"] == "highres_only"


def test_spanish_search_always_falls_back_to_english() -> None:
    config = normalise_deck_config(
        {
            "preferred_language": "es",
            "allow_language_fallback": False,
        }
    )

    assert config["allow_language_fallback"] is True


def test_english_search_does_not_fall_back_to_spanish() -> None:
    config = normalise_deck_config(
        {
            "preferred_language": "en",
            "allow_language_fallback": True,
        }
    )

    assert config["allow_language_fallback"] is False


def test_every_bulk_search_requires_high_resolution() -> None:
    assert bulk_scryfall_settings("Español y después inglés") == (
        True,
        "flexible",
        "highres_only",
    )
    assert bulk_scryfall_settings("Máxima calidad disponible") == (
        True,
        "flexible",
        "highres_only",
    )
    assert bulk_scryfall_settings("Respetar impresión exacta") == (
        True,
        "exact_only",
        "highres_only",
    )
    assert AUTOMATIC_MPCFILL_MINIMUM_DPI == 800
