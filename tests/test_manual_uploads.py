from pathlib import Path

from mtg_downloader.models import ImageFace
from mtg_downloader.scryfall import ScryfallClient


def test_download_raw_image_supports_local_uploaded_files(tmp_path) -> None:
    image_path = tmp_path / "uploaded.png"
    image_path.write_bytes(b"fake-image-bytes")
    client = ScryfallClient(tmp_path)
    try:
        raw = client.download_raw_image(
            ImageFace(
                label="Manual upload",
                url=str(image_path),
                extension=".png",
                provider="upload",
            )
        )
    finally:
        client.close()

    assert raw == b"fake-image-bytes"
