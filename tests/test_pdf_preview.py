from io import BytesIO
from zipfile import ZipFile

from PIL import Image
import pytest
from reportlab.pdfgen import canvas


def two_page_pdf():
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(200, 300))
    for color in ("#ff0000", "#0000ff"):
        pdf.setFillColor(color)
        pdf.rect(0, 0, 200, 300, fill=True, stroke=False)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_renders_actual_front_and_back_without_changing_pdf():
    from mtg_downloader.pdf_preview import render_pdf_page, pdf_page_count
    data = two_page_pdf()
    assert pdf_page_count(data) == 2
    with Image.open(BytesIO(render_pdf_page(data, 0))) as front:
        assert front.size == (200, 300)
        assert front.convert("RGB").getpixel((100, 150)) == (255, 0, 0)
    with Image.open(BytesIO(render_pdf_page(data, 1))) as back:
        assert back.convert("RGB").getpixel((100, 150)) == (0, 0, 255)
    assert data.startswith(b"%PDF")


@pytest.mark.parametrize("page", [-1, 2, 300])
def test_rejects_page_outside_pdf(page):
    from mtg_downloader.pdf_preview import render_pdf_page
    with pytest.raises(ValueError):
        render_pdf_page(two_page_pdf(), page)


def test_invalid_pdf_does_not_crash_native_renderer():
    from mtg_downloader.pdf_preview import render_pdf_page
    with pytest.raises(ValueError):
        render_pdf_page(b"not a PDF", 0)


def test_only_selected_zip_part_is_used():
    from mtg_downloader.pdf_preview import preview_pdf_bytes
    output = BytesIO()
    pdf = two_page_pdf()
    with ZipFile(output, "w") as archive:
        archive.writestr("one.pdf", b"unused")
        archive.writestr("two.pdf", pdf)
    assert preview_pdf_bytes(output.getvalue(), "application/zip", "two.pdf") == pdf
    assert preview_pdf_bytes(pdf, "application/pdf", None) is pdf


def test_preview_ui_changes_pages_and_invalidates_cached_image():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from mtg_downloader.studio_ui import render_generated_preview
render_generated_preview(st.session_state["download"], st.session_state["signature"])
''')
    app.session_state["download"] = {"data": two_page_pdf(), "mime": "application/pdf"}
    app.session_state["signature"] = "first"
    app.run()
    assert not app.exception
    front = app.session_state["studio_pdf_preview"]["png"]
    app.selectbox[0].select(1).run()
    assert not app.exception
    assert app.session_state["studio_pdf_preview"]["png"] != front
    app.session_state["signature"] = "second"
    app.run()
    assert app.session_state["studio_pdf_preview"]["identity"] == ("second", None)
    assert app.session_state["studio_pdf_preview"]["png"] == front


def test_preview_ui_handles_broken_data_without_blocking_download():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from mtg_downloader.studio_ui import render_generated_preview
render_generated_preview({"data": b"broken", "mime": "application/pdf"}, "bad")
st.button("Guardar PDF")
''').run()
    assert not app.exception
    assert "Vista previa no disponible" in app.warning[0].value
    assert app.button[0].label == "Guardar PDF"


def test_multipart_preview_labels_sheet_numbers_as_local_to_part():
    from streamlit.testing.v1 import AppTest
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("first.pdf", two_page_pdf())
        archive.writestr("second.pdf", two_page_pdf())
    app = AppTest.from_string('''
import streamlit as st
from mtg_downloader.studio_ui import render_generated_preview
render_generated_preview(st.session_state["download"], "zip")
''')
    app.session_state["download"] = {"data": output.getvalue(), "mime": "application/zip", "part_names": ["first.pdf", "second.pdf"]}
    app.run()
    app.selectbox[0].select("second.pdf").run()
    assert not app.exception
    assert app.selectbox[1].options == ["Hoja 1 de esta parte · anverso", "Hoja 1 de esta parte · reverso"]
    assert app.session_state["studio_pdf_preview"]["identity"] == ("zip", "second.pdf")
