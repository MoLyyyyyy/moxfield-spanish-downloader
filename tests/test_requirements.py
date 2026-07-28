from pathlib import Path


def test_streamlit_supports_deferred_downloads() -> None:
    requirements = (
        Path(__file__).resolve().parents[1] / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "streamlit>=1.54,<2" in requirements
