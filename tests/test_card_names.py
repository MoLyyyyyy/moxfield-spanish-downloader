from mtg_downloader.card_names import (
    canonical_card_name,
    card_face_names,
    front_card_name,
    is_multi_face_name,
    normalised_card_name,
)


def test_single_and_double_slash_are_equivalent() -> None:
    assert canonical_card_name("Fire / Ice") == "Fire // Ice"
    assert canonical_card_name("Fire // Ice") == "Fire // Ice"
    assert normalised_card_name("Fire / Ice") == "fire // ice"


def test_more_than_two_faces_are_preserved() -> None:
    value = "Who / What / When / Where / Why"
    assert card_face_names(value) == (
        "Who",
        "What",
        "When",
        "Where",
        "Why",
    )
    assert is_multi_face_name(value)
    assert front_card_name(value) == "Who"


def test_normal_card_name_is_unchanged() -> None:
    assert canonical_card_name("Rampant Growth") == "Rampant Growth"
    assert not is_multi_face_name("Rampant Growth")
