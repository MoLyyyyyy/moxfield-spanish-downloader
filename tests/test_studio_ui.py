from streamlit.testing.v1 import AppTest


def navigation_app(ready):
    return AppTest.from_string(f"""
import streamlit as st
from mtg_downloader.studio_ui import render_step_navigation
st.session_state.setdefault("step", 1)
st.session_state["step"] = render_step_navigation(st.session_state["step"], {ready})
st.write("step=" + str(st.session_state["step"]))
""").run()


def test_navigation_blocks_unanalysed_deck():
    app = navigation_app(False)
    assert not app.exception
    assert app.button(key="studio_step_2").disabled
    assert app.button(key="studio_step_3").disabled


def test_navigation_switches_steps_without_changing_project():
    app = navigation_app(True)
    assert not app.exception
    app.session_state["project_revision"] = 7
    app.button(key="studio_step_2").click().run()
    assert app.session_state["step"] == 2
    app.button(key="studio_step_3").click().run()
    assert app.session_state["step"] == 3
    app.button(key="studio_step_1").click().run()
    assert app.session_state["step"] == 1
    assert app.session_state["project_revision"] == 7


def test_initial_app_has_no_fake_decks_and_analysis_is_required():
    from pathlib import Path
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
    assert not app.exception
    assert app.button(key="studio_step_2").disabled
    assert app.text_area(key="decklist_input_0").value == ""
