from mtg_downloader.deck_workflow import (
    deck_configs_from_analysis_config,
    deck_position_for_card,
    deck_settings_label,
    indices_for_deck,
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
