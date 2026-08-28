# Studio Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Trasladar la maqueta aprobada a Streamlit sin perder funciones.

**Architecture:** Componentes visuales en `mtg_downloader/studio_ui.py`,
estado y operaciones existentes en `app.py`. Vista previa del PDF real en
un módulo independiente, sin alterar el generador ni el formato impreso.

**Tech Stack:** Python 3.12, Streamlit, Pillow, pytest, AppTest, PDFium para
rasterizar el PDF; comprobar documentación y compatibilidad antes de fijar
la nueva dependencia. PyInstaller para verificar el portable.

**Spec:** `docs/superpowers/specs/2026-08-28-proxy-maker-studio-design.md`

## Registro de ejecución — 28 de agosto

Implementado secuencialmente en `studio-redesign`, con revisión independiente.
La entrega se agrupa en un único commit de implementación. La lista inferior
conserva el plan original; el resultado y el alcance exacto de las pruebas
están en [el informe de verificación](../verification/2026-08-28-studio.md).

- [x] Tema, navegación e importación Studio.
- [x] Galería y editor contextual, con mazos en el lateral.
- [x] Vista previa del PDF real, páginas/partes e invalidación.
- [x] Suite de 268 pruebas y revisión de código independiente.
- [x] Inspección web a 1280×850, 960×640 y 390×844.
- [x] Portable compilado, extraído y probado: arranque, análisis, PDF,
  rasterización con PDFium incluido, guardado y cierre del servidor.
- [ ] Comprobación visual de la ventana nativa WebView2.
- [ ] Integración/publicación: requiere decisión del usuario.

## Global Constraints

- Conservar Streamlit, el servidor local y la ventana portable existentes.
- Búsqueda automática solo en alta resolución; mantener fallback de idioma.
- Sin imagen válida: no encontrada; elección manual de MPCFill o archivo.
- Códigos automáticos únicos de tres letras en traseras estándar, nunca sobre segundas caras jugables.
- Formato de proyectos compatible e imágenes restauradas bajo Datos en portable.
- No modificar dimensiones físicas, recorte ni algoritmos de PDF por estética.
- Sin sobrescritura silenciosa de exportaciones ni nuevos envíos de datos.
- No confundir cerrar la ventana con guardar automáticamente el proyecto.
- No publicar ni crear releases como parte de la aprobación del diseño.

## Preparación

- [ ] Crear aislamiento según using-git-worktrees; conservar la copia original.
- [ ] Ejecutar suite inicial con Python de `.venv`; en Windows los tests heredados
  con `/tmp` requieren el mapeo de unidad de pruebas ya utilizado en este proyecto.
- [ ] Registrar estado de Git y no incorporar modificaciones ajenas.

## Task 1: Tema, navegación e importación

**Files:** crear `mtg_downloader/studio_ui.py`, `tests/test_studio_ui.py`;
modificar `app.py`, `.streamlit/config.toml`, `desktop.py`, `ProxyMaker.spec`.

**Interfaces:** `apply_studio_theme()` aplica CSS de presentación;
`render_step_navigation(current: int, analysis_ready: bool) -> int` devuelve
el paso solicitado. No modifica resultados ni inicia búsquedas.

- [ ] Escribir prueba AppTest: con análisis ausente no se puede pasar a revisión;
  con análisis válido pulsar Revisar devuelve 2; la acción Importar devuelve 1.

```python
def test_navigation_blocks_unanalysed_deck():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from mtg_downloader.studio_ui import render_step_navigation
st.write(render_step_navigation(1, False))
''').run()
    assert not app.exception
    assert next(b for b in app.button if 'Revisar' in b.label).disabled
```

- [ ] Ejecutar `python -m pytest tests/test_studio_ui.py -q`; observar fallo
  por componente ausente antes de implementarlo.
- [ ] Implementar navegación con botones de claves estables `studio_step_1`,
  `studio_step_2`, `studio_step_3`, habilitando los dos últimos solo si el
  análisis es válido. Integrarla donde hoy están `step_columns` y progreso.
- [ ] Aplicar paleta de la especificación, tipografía de sistema y componentes
  de Streamlit; no ocultar errores ni foco. Configurar el tema en web y en las
  opciones del lanzador para que el portable no dependa del directorio de inicio.
- [ ] Mover guardar/cargar a acceso compacto y conservar métodos de importación,
  ajustes por mazo y acción Analizar; retirar únicamente texto redundante.
- [ ] Probar inicio vacío, carga de proyecto, cambio de paso y configuración
  invalidada con AppTest. Actualizar tests estructurales obsoletos sin eliminar
  las comprobaciones de comportamiento que protegían.
- [ ] Ejecutar suite, revisión y commit `feat: add Studio theme and navigation`.

## Task 2: Galería y editor contextual

**Files:** modificar `app.py`, `mtg_downloader/studio_ui.py`;
crear `tests/test_studio_workspace.py`.

**Interfaces:** mantener `set_active_deck`, `set_review_index`,
`save_replacement` y `review_selected_index`. El índice global de carta
permanece estable dentro de un análisis aunque la galería se reordene.
`render_review_panel(*, embedded: bool = False)` permite colocar el editor
en una columna, sin eliminar su variante normal durante la transición.

- [ ] Crear fixtures de dos mazos con objetos reales `ResolvedCard`, una imagen
  local válida y una carta sin imagen; usar los constructores de las pruebas
  existentes. Ejecutar la app con estado preparado, sin acceso a proveedores.
- [ ] Prueba roja de interacción: seleccionar una carta en la galería deja la
  galería visible y muestra el nombre de esa carta en el editor.
- [ ] Prueba roja: cambiar al segundo mazo y volver conserva `selected` y
  `allocations` del primero. Confirmar que seleccionar carta saludable no queda
  bloqueado por `review_only_problematic` del editor anterior.
- [ ] Renderizar selector de mazos en sidebar con nombres, códigos y pendientes.
  Reutilizar `set_active_deck`; mantener reintento de pendientes y ajustes.
- [ ] Sustituir bifurcación de `render_workspace` por columnas de galería/editor.
  En modo embedded, quitar el botón Volver al mazo y el progreso duplicado;
  presentar previsualización y alternativas verticalmente, evitando columnas
  anidadas que compriman los controles.

```python
def render_workspace():
    gallery, editor = st.columns([1.6, 1], gap='large')
    with gallery:
        render_deck_gallery()
    with editor:
        render_review_panel(embedded=True)
```

- [ ] Reducir la rejilla de seis columnas a un número legible en el espacio
  central. Dejar las cartas correctas visibles y pendientes primero. Mantener
  filtros, búsqueda, selección masiva, paginación y todas las fuentes existentes.
- [ ] Agrupar detalles, recorte y reparto bajo opciones avanzadas. Mantener
  selección de Scryfall/MPCFill y subidas como controles reales accesibles.
- [ ] Probar siguiente/anterior, edición de DFC, reparto, subida y conservación
  de selección al resolver el último pendiente. No exigir texto exacto del CSS.
- [ ] Inspeccionar a 1280×850 y 960×640; apilar sin solapamientos en vista estrecha.
- [ ] Ejecutar suite, revisión y commit `feat: add contextual Studio card review`.

## Task 3: Vista previa y validación integrada

**Files:** crear `mtg_downloader/pdf_preview.py`, `tests/test_pdf_preview.py`;
modificar `app.py`, `requirements.txt`, `ProxyMaker.spec`, README y smoke si
las etiquetas de navegación cambian.

**Interfaces:** `render_pdf_page(data: bytes, page_index: int) -> bytes`
devuelve un PNG reducido. Acepta un PDF, nunca un ZIP, valida el índice y
libera página, bitmap y documento incluso ante errores.

- [ ] Crear PDF real de dos páginas con ReportLab y testear que los PNG son
  distintos y de dimensiones acotadas. Probar índice inexistente y bytes inválidos.

```python
def test_preview_rejects_invalid_pdf():
    import pytest
    from mtg_downloader.pdf_preview import render_pdf_page
    with pytest.raises(ValueError):
        render_pdf_page(b'not a PDF', 0)
```

- [ ] Observar RED; verificar documentación de PDFium, añadir dependencia
  compatible y rasterizar una página a escala 1 como máximo. Convertir errores
  de formato a `ValueError`; no ocultar errores de programación.
- [ ] Conservar un PDF de la salida para previsualizar: si hay partes, permitir
  seleccionar parte y página; no intentar rasterizar el ZIP completo. No añadir
  bitmaps de todas las páginas al estado ni duplicar el documento original.
- [ ] Usar `pdf_output_signature` existente para invalidación de salida y vista
  previa. Solo mostrar vista previa cuando la salida siga correspondiendo a la
  selección actual. Antes de generar, mostrar resumen y aviso de huecos.
- [ ] Mantener guardar en Datos/Exportaciones y descarga web, controles de
  bloqueo, pares dúplex y partición. Un error de vista previa debe dejar
  disponible el PDF válido con un aviso local.
- [ ] Verificar proyecto con dos mazos, imagen manual, alternativa inglesa,
  DFC y varias ilustraciones; guardar/restaurar, generar y comparar PDF real.
- [ ] Ejecutar suite completa; compilar portable y smoke del EXE extraído del
  ZIP. Revisar que tema y PDFium están incluidos. Validación visual de WebView2
  separada si vuelve a impedirla el entorno de ejecución.
- [ ] Ejecutar revisión final, documentar uso y commit
  `feat: add generated PDF preview and verify Studio portable`.

## Entrega

- [ ] Mostrar capturas de la interfaz real y resultados de pruebas.
- [ ] Informar de cualquier validación pendiente; no llamar completa a una
  mera capa de estilos ni a una maqueta.
- [ ] Mantener cambios locales hasta autorización de subida/publicación.
