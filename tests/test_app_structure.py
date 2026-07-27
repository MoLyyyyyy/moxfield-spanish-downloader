from pathlib import Path


def test_app_has_no_file_uploader() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "st.file_uploader" not in app
    assert "uploaded_list" not in app
    assert "uploaded_text" not in app
    assert "Subir exportación del mazo" not in app


def test_app_has_visual_review_flow() -> None:
    app = Path("app.py").read_text(encoding="utf-8")
    assert "Analizar mazo" in app
    assert "Revisar impresiones" in app
    assert "Buscar impresiones alternativas" in app
    assert "Elegir esta versión" in app
    assert "Generar ZIP con la selección actual" in app
