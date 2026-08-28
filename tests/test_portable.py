import importlib.util
from pathlib import Path

import pytest


def test_portable_module_exists():
    assert importlib.util.find_spec('mtg_downloader.portable') is not None


def test_portable_cache_uses_data_folder(monkeypatch, tmp_path):
    from mtg_downloader.portable import image_cache_dir
    monkeypatch.setenv('PROXY_MAKER_DATA_DIR', str(tmp_path / 'Datos'))
    assert image_cache_dir('scryfall') == tmp_path / 'Datos' / 'cache' / 'scryfall'
    assert image_cache_dir('mpcfill') == tmp_path / 'Datos' / 'cache' / 'mpcfill'


def test_web_cache_keeps_existing_location(monkeypatch):
    import tempfile
    from mtg_downloader.portable import image_cache_dir
    monkeypatch.delenv('PROXY_MAKER_DATA_DIR', raising=False)
    assert image_cache_dir('scryfall') == Path(tempfile.gettempdir()) / 'moxfield_cartas_es_cache'


def test_portable_save_never_overwrites_or_escapes_folder(monkeypatch, tmp_path):
    from mtg_downloader.portable import save_output
    monkeypatch.setenv('PROXY_MAKER_DATA_DIR', str(tmp_path))
    first = save_output(b'first', '../../deck.pdf', 'Exportaciones')
    second = save_output(b'second', '../../deck.pdf', 'Exportaciones')
    assert first.parent == tmp_path / 'Exportaciones'
    assert second.parent == first.parent
    assert first != second
    assert first.read_bytes() == b'first'
    assert second.read_bytes() == b'second'
    with pytest.raises(ValueError):
        save_output(b'data', 'file.pdf', '../outside')


def test_portable_project_can_be_relocated(monkeypatch, tmp_path):
    from mtg_downloader.portable import save_output
    monkeypatch.setenv('PROXY_MAKER_DATA_DIR', str(tmp_path / 'Original'))
    saved = save_output(b'{"project": true}', 'deck.json', 'Proyectos')
    (tmp_path / 'Original').rename(tmp_path / 'Movado')
    assert (tmp_path / 'Movado' / 'Proyectos' / saved.name).read_bytes() == b'{"project": true}'


def test_desktop_server_only_listens_on_loopback():
    from desktop import server_options
    options = server_options(32109)
    assert options['server.address'] == '127.0.0.1'
    assert options['server.port'] == 32109
    assert options['server.headless'] is True
    assert options['browser.gatherUsageStats'] is False
    assert options['server.enableXsrfProtection'] is True


def test_child_process_stops_when_context_exits(tmp_path):
    import subprocess
    import sys
    from desktop import managed_process
    with managed_process([sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path / 'log.txt') as process:
        assert process.poll() is None
    assert process.poll() is not None


def test_child_process_stops_after_startup_error(tmp_path):
    import sys
    from desktop import managed_process
    with pytest.raises(RuntimeError):
        with managed_process([sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path / 'log.txt') as process:
            raise RuntimeError('window failed')
    assert process.poll() is not None


def test_save_button_writes_project_and_reports_location(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PROXY_MAKER_DATA_DIR', str(tmp_path))
    app = AppTest.from_string('''
from mtg_downloader.portable import render_save_button
render_save_button('Guardar proyecto', b'{"cards": []}', 'deck.json', 'Proyectos')
''').run()
    assert not list((tmp_path / 'Proyectos').glob('*'))
    app.button[0].click().run()
    assert not app.exception
    assert (tmp_path / 'Proyectos' / 'deck.json').read_bytes() == b'{"cards": []}'
    assert 'deck.json' in app.success[0].value
