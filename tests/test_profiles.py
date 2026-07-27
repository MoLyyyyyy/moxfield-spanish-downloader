from mtg_downloader.profiles import PROFILES, get_profile


def test_profiles_have_unique_keys() -> None:
    keys = [profile.key for profile in PROFILES]
    assert len(keys) == len(set(keys))


def test_balanced_profile_is_recommended_behavior() -> None:
    profile = get_profile("balanced")
    assert profile.resolution_mode == "exact_first"
    assert profile.quality_mode == "prefer_highres"
    assert profile.allow_english is True


def test_fidelity_profile_never_changes_printing() -> None:
    profile = get_profile("fidelity")
    assert profile.resolution_mode == "exact_only"
    assert profile.quality_mode == "allow_lowres"


def test_maximum_quality_rejects_lowres() -> None:
    profile = get_profile("maximum_quality")
    assert profile.resolution_mode == "flexible"
    assert profile.quality_mode == "highres_only"


def test_spanish_only_disables_english() -> None:
    profile = get_profile("spanish_only")
    assert profile.allow_english is False
    assert profile.allow_english_if_missing is True
