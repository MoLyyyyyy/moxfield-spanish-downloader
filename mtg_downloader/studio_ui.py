"""Presentation-only Studio components; no provider or project mutations."""
from __future__ import annotations

import streamlit as st


def theme_options() -> dict:
    return {
        "theme.base": "dark",
        "theme.primaryColor": "#c2d69a",
        "theme.backgroundColor": "#141617",
        "theme.secondaryBackgroundColor": "#1b1e20",
        "theme.textColor": "#eeeae3",
        "theme.font": "sans serif",
    }


def apply_studio_theme() -> None:
    st.html("""
<style>
.stApp {background:#141617;color:#eeeae3;font-family:'Segoe UI',sans-serif}
[data-testid="stHeader"] {background:#141617}
[data-testid="stSidebar"] {background:#1b1e20;border-right:1px solid #303538;min-width:220px;max-width:250px}
.stApp [data-testid="stMainBlockContainer"] {padding:2rem;max-width:1600px}
h1,h2,h3 {font-weight:500!important;letter-spacing:-.035em}
h1 {font-size:1.75rem!important}
h2 {font-size:1.4rem!important}
h3 {font-size:1.15rem!important}
h4 {font-size:1rem!important;font-weight:500!important}
[data-testid="stCaptionContainer"] {color:#a7adaa}
button[kind="primary"] {background:#c2d69a;color:#20261a;border-color:#c2d69a}
button[kind="secondary"] {border-color:#39403d;background:#1b1e20}
button[kind="secondary"]:hover {border-color:#a8bd82;color:#d3e4b3}
[data-testid="stExpander"] {border-color:#303538;background:#191c1d}
[data-testid="stTextArea"] textarea,[data-testid="stTextInput"] input {background:#1b1e20;color:#eeeae3}
.st-key-studio_navigation {padding-bottom:.8rem;border-bottom:1px solid #303538;margin-bottom:.5rem}
.st-key-studio_editor {background:#1b1e20;border:1px solid #303538;border-radius:10px;padding:1rem}
.st-key-studio_gallery [data-testid="stImage"] img {border-radius:8px}
.studio-empty {aspect-ratio:63/88;display:flex;align-items:center;justify-content:center;
border:1px dashed #68755f;background:#202522;border-radius:8px;color:#c2d69a;text-align:center;padding:1rem}
.studio-brand {font-weight:500;font-size:1.15rem;letter-spacing:-.04em;margin-bottom:1.5rem}
.studio-brand span {color:#c2d69a}
.st-key-studio_navigation button {min-height:42px}
.st-key-studio_editor [data-testid="stHorizontalBlock"]:has([data-testid="stSelectbox"],[data-testid="stTextInput"]),
.st-key-studio_gallery [data-testid="stExpander"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap}
.st-key-studio_editor [data-testid="stColumn"]:has([data-testid="stSelectbox"],[data-testid="stTextInput"]),
.st-key-studio_gallery [data-testid="stExpander"] [data-testid="stColumn"] {flex:1 1 140px!important;min-width:0!important}
@media(max-width:1100px) {
 .st-key-studio_workspace > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"],
 .st-key-studio_workspace [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-studio_editor)
 {flex-wrap:wrap}
 .st-key-studio_workspace [data-testid="stColumn"]:has(.st-key-studio_gallery),
 .st-key-studio_workspace [data-testid="stColumn"]:has(.st-key-studio_editor) {flex:1 1 100%!important;width:100%!important}
 .stApp [data-testid="stMainBlockContainer"] {padding-left:1rem;padding-right:1rem}
}
</style>
""")


def render_step_navigation(current: int, analysis_ready: bool) -> int:
    requested = current
    with st.container(key="studio_navigation"):
        for step, (column, label) in enumerate(zip(st.columns(3), (
            "1 · Importar", "2 · Revisar", "3 · PDF",
        )), 1):
            with column:
                if st.button(
                    label, key=f"studio_step_{step}", width="stretch",
                    type="primary" if step == current else "secondary",
                    disabled=step != 1 and not analysis_ready,
                ):
                    requested = step
    return requested


def render_generated_preview(download: dict, signature: str) -> None:
    from .pdf_preview import pdf_page_count, preview_pdf_bytes, render_pdf_page

    st.subheader("Vista previa de impresión")
    part = None
    if download["mime"] == "application/zip":
        part = st.selectbox("Parte", download["part_names"], key=f"studio_preview_part_{signature}")
    identity = (signature, part)
    cached = st.session_state.get("studio_pdf_preview", {})
    data = None
    try:
        if cached.get("identity") != identity:
            data = preview_pdf_bytes(download["data"], download["mime"], part)
            cached = {"identity": identity, "count": pdf_page_count(data)}
        count = cached["count"]
        if count < 1:
            raise ValueError("El PDF no contiene páginas.")
        page = st.selectbox(
            "Página", list(range(count)),
            format_func=lambda index: f"Hoja {index // 2 + 1}{' de esta parte' if part else ''} · {'anverso' if index % 2 == 0 else 'reverso'}",
            key=f"studio_preview_page_{signature}_{part}",
        )
        if cached.get("page") != page or "png" not in cached:
            if data is None:
                data = preview_pdf_bytes(download["data"], download["mime"], part)
            cached.update(page=page, png=render_pdf_page(data, page))
        st.session_state["studio_pdf_preview"] = cached
        st.image(cached["png"], width=480)
        st.caption("Vista reducida del PDF generado · impresión a tamaño real.")
    except (ValueError, OSError) as exc:
        st.warning(f"Vista previa no disponible: {exc} El archivo sigue disponible para guardar.")
