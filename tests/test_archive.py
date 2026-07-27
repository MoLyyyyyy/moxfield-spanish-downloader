from mtg_downloader.archive import build_zip
from mtg_downloader.models import DeckCard, ImageFace, ResolvedCard
import zipfile
import io


class FakeClient:
    def download_image(self, face: ImageFace) -> bytes:
        return b"imagen"


def test_build_zip_creates_every_copy() -> None:
    resolved = ResolvedCard(
        source=DeckCard(quantity=8, name="Mountain"),
        status="Otra impresión en español",
        language="es",
        printed_name="Montaña",
        selected_set="fdn",
        collector_number="279",
        faces=[ImageFace(label="Montaña", url="fake", extension=".jpg")],
    )

    data, report = build_zip(
        [resolved],
        FakeClient(),
        duplicate_copies=True,
    )

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        images = [name for name in archive.namelist() if name.endswith(".jpg")]

    assert len(images) == 8
    assert report[0]["cantidad"] == 8


def test_double_faced_card_creates_two_images_per_copy() -> None:
    resolved = ResolvedCard(
        source=DeckCard(quantity=2, name="Fable of the Mirror-Breaker"),
        status="Otra impresión en español",
        language="es",
        printed_name="Fábula del rompeespejos",
        selected_set="neo",
        collector_number="141",
        faces=[
            ImageFace(label="Frontal", url="front", extension=".jpg"),
            ImageFace(label="Trasera", url="back", extension=".jpg"),
        ],
    )

    data, _ = build_zip(
        [resolved],
        FakeClient(),
        duplicate_copies=True,
    )

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        images = [name for name in archive.namelist() if name.endswith(".jpg")]

    assert len(images) == 4


def test_report_contains_download_format() -> None:
    resolved = ResolvedCard(
        source=DeckCard(quantity=1, name="Sol Ring"),
        status="Misma impresión en español",
        language="es",
        printed_name="Anillo Solar",
        selected_set="cmm",
        collector_number="396",
        faces=[ImageFace(label="Anillo Solar", url="fake", extension=".png")],
        downloaded_format="PNG",
    )

    _, report = build_zip(
        [resolved],
        FakeClient(),
        duplicate_copies=True,
    )

    assert report[0]["formato_descarga"] == "PNG"


def test_zip_supports_multiple_art_allocations() -> None:
    from mtg_downloader.selections import add_variant

    resolved = ResolvedCard(
        source=DeckCard(quantity=4, name="Forest"),
        status="Manual",
        printed_name="Forest A",
        selected_set="a",
        collector_number="1",
        faces=[ImageFace("A", "a", ".jpg")],
    )
    other = ResolvedCard(
        source=DeckCard(quantity=4, name="Forest"),
        status="Manual",
        printed_name="Forest B",
        selected_set="b",
        collector_number="2",
        faces=[ImageFace("B", "b", ".jpg")],
    )
    add_variant(resolved, other)
    data, report = build_zip([resolved], FakeClient(), duplicate_copies=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        images = [name for name in archive.namelist() if name.endswith(".jpg")]
    assert len(images) == 4
    assert len(report) == 2
    assert sum(row["cantidad"] for row in report) == 4


def test_mpc_package_places_second_face_only_in_backs() -> None:
    resolved = ResolvedCard(
        source=DeckCard(quantity=1, name="DFC"),
        status="ok",
        faces=[
            ImageFace("Front", "front", ".jpg"),
            ImageFace("Back", "back", ".jpg"),
        ],
    )
    data, _ = build_zip(
        [resolved],
        FakeClient(),
        duplicate_copies=True,
        package_mode="mpc",
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        fronts = [name for name in archive.namelist() if name.startswith("Frentes/")]
        backs = [name for name in archive.namelist() if name.startswith("Reversos/")]
    assert len(fronts) == 1
    assert len(backs) == 1
