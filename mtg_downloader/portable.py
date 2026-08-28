"""Storage shared by the web application and the optional portable launcher."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def data_dir() -> Path | None:
    value = os.environ.get('PROXY_MAKER_DATA_DIR')
    return Path(value).resolve() if value else None


def image_cache_dir(provider: str) -> Path:
    root = data_dir()
    if root is not None:
        return root / 'cache' / provider
    name = 'moxfield_cartas_es_mpcfill_cache' if provider == 'mpcfill' else 'moxfield_cartas_es_cache'
    return Path(tempfile.gettempdir()) / name


def save_output(data: bytes, filename: str, category: str) -> Path:
    root = data_dir()
    if root is None:
        raise RuntimeError('El modo portable no está activo.')
    if category not in {'Proyectos', 'Exportaciones'}:
        raise ValueError('Carpeta de salida no válida.')
    folder = root / category
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename.replace('\\', '/').rsplit('/', 1)[-1]).strip(' .')
    name = name or 'archivo'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + name
    original = Path(name)
    for number in range(100000):
        target = folder / (name if number == 0 else f'{original.stem} ({number}){original.suffix}')
        try:
            with target.open('xb') as output:
                output.write(data)
            return target
        except FileExistsError:
            continue
    raise OSError('Demasiados archivos con el mismo nombre.')


def render_save_button(label: str, data: bytes, filename: str, category: str, *, primary: bool = False) -> None:
    import streamlit as st
    if st.button(label, type='primary' if primary else 'secondary', width='stretch'):
        try:
            path = save_output(data, filename, category)
            st.success(f'Guardado en: {path}')
        except OSError as exc:
            st.error(f'No se pudo guardar el archivo: {exc}')
