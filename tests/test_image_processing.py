import io

from PIL import Image

from mtg_downloader.image_processing import (
    CARD_ASPECT_RATIO,
    CROP_AUTO,
    CROP_FORCE,
    CROP_NONE,
    process_mpc_image_bytes,
    should_crop_mpc_image,
)


def image_bytes(size=(690, 941), image_format="JPEG"):
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def test_auto_detects_standard_mpc_bleed_ratio() -> None:
    assert should_crop_mpc_image(690, 941)


def test_auto_does_not_crop_card_ratio() -> None:
    assert not should_crop_mpc_image(630, 880)


def test_force_crop_removes_bleed_on_all_sides() -> None:
    processed = process_mpc_image_bytes(
        image_bytes(),
        crop_mode=CROP_FORCE,
    )
    assert processed.cropped
    assert processed.final_size[0] < processed.original_size[0]
    assert processed.final_size[1] < processed.original_size[1]
    ratio = processed.final_size[0] / processed.final_size[1]
    assert abs(ratio - CARD_ASPECT_RATIO) < 0.005


def test_none_preserves_dimensions() -> None:
    processed = process_mpc_image_bytes(
        image_bytes(),
        crop_mode=CROP_NONE,
    )
    assert not processed.cropped
    assert processed.final_size == processed.original_size


def test_auto_crops_bleed_image() -> None:
    processed = process_mpc_image_bytes(
        image_bytes(),
        crop_mode=CROP_AUTO,
    )
    assert processed.cropped


def test_crop_shift_preserves_final_dimensions() -> None:
    centered = process_mpc_image_bytes(
        image_bytes(),
        crop_mode=CROP_FORCE,
    )
    shifted = process_mpc_image_bytes(
        image_bytes(),
        crop_mode=CROP_FORCE,
        crop_shift_x=100,
        crop_shift_y=-100,
    )
    assert shifted.final_size == centered.final_size
