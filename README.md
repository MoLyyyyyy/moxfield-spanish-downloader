# Proxy Maker

Proxy Maker convierte una lista de Magic: The Gathering exportada desde
Moxfield en un PDF A4 listo para imprimir.

## Cómo funciona

1. Pega una o varias listas de mazo.
2. Elige la fuente principal, el idioma y cómo tratar la edición indicada.
3. Revisa las versiones seleccionadas y corrige las cartas pendientes.
4. Genera y descarga el PDF.

La aplicación respeta cantidades, ediciones, números de coleccionista,
sideboard, maybeboard y cartas de dos caras.

## Imágenes

La selección automática exige siempre alta resolución:

- Con español como idioma principal, busca primero una imagen española y
  después una inglesa.
- Con inglés como idioma principal, busca únicamente en inglés.
- Nunca acepta automáticamente una imagen `lowres`.
- Si no encuentra una imagen válida, marca la carta como pendiente.

Durante la revisión puedes sustituir cualquier carta pendiente por un diseño
de MPCFill o por una imagen propia.

Scryfall proporciona las impresiones oficiales. MPCFill proporciona diseños
de la comunidad y prioriza, cuando están disponibles, a MrTeferi, PsilosX,
Chilli_Axe, CompC y Hathwellcrisping.

## Modos de edición

- **Edición indicada primero**: intenta la edición y el número de coleccionista
  de la lista antes de buscar otra impresión.
- **Solo la edición indicada**: marca la carta como pendiente si esa impresión
  no tiene una imagen válida.
- **Cualquier edición**: busca la mejor impresión compatible sin dar prioridad
  a la edición de la lista.

## PDF

El paso final muestra únicamente las incidencias bloqueantes, el número de
hojas, los huecos de la última hoja y la acción de generar o descargar.

El PDF utiliza automáticamente el perfil recomendado:

- A4 vertical con 3 × 3 cartas por página;
- cartas de 63,5 × 88,9 mm;
- sangrado espejo de 1 mm;
- reverso estándar de Magic;
- código automático y único de tres letras en cada reverso estándar;
- marcas cortas de corte y marcas de imprenta;
- páginas dúplex intercaladas como `1/1B`, `2/2B`, etc.

Los archivos superiores a 200 MB se dividen automáticamente sin separar las
parejas de páginas dúplex. Si la última hoja queda incompleta, la aplicación
indica cuántos huecos quedan y cuántas cartas se pueden añadir para llenarla.
Las segundas caras jugables nunca reciben el código del mazo.

## Instalación en Windows

### Portable (ventana independiente)

Descomprime todo `ProxyMaker-Windows-portable.zip` y abre `ProxyMaker.exe`.
No necesita Python ni un servidor externo. Requiere Windows 10/11 x64,
.NET Framework 4.8 y Microsoft Edge WebView2 Runtime.

Las imágenes se guardan en `Datos/cache`; los botones de guardar escriben
proyectos en `Datos/Proyectos` y PDF/ZIP en `Datos/Exportaciones`, sin
sobrescribir archivos existentes. Guarda tu proyecto antes de cerrar.
Para mover la aplicación, copia toda la carpeta, incluida `Datos`.
Las búsquedas y descargas siguen necesitando Internet.

Para compilar en Windows:

```powershell
python -m pip install -r requirements-desktop.txt
python build_portable.py
```

El resultado aparece en `dist/ProxyMaker-Windows-portable.zip`.
La versión web y el arranque con Python siguen disponibles.

### Generar una release con GitHub Actions

Primero sube a `main` los archivos del portable y el workflow
`.github/workflows/release.yml`. Después crea y sube una etiqueta nueva:

```bash
git tag v1.0.0-beta.1
git push origin v1.0.0-beta.1
```

Usa una versión distinta en cada entrega (`v1.0.0`, `v1.0.1`, etc.).
La etiqueta debe apuntar al commit que quieras distribuir, con todos los
archivos del portable incluidos.

El workflow **Windows portable release** ejecuta las pruebas, compila en
Windows x64, comprueba el servidor del EXE extraído y crea una **release
en borrador** con el ZIP. Las etiquetas con sufijo, como `-beta.1`, se marcan
como preliminares. No publica automáticamente ni sobrescribe releases.

También puedes ir a **Actions → Windows portable release → Run workflow**
e indicar una etiqueta que ya exista. El botón aparece cuando el workflow
está en la rama predeterminada. Siempre se compila la etiqueta indicada,
no la rama seleccionada en el formulario.

Al terminar, abre **Releases**, revisa el borrador, descarga y prueba la
ventana y la exportación de un PDF, y pulsa **Publish release**. El test
automático del servidor no valida visualmente WebView2.

No necesitas añadir un token personal: se utiliza `GITHUB_TOKEN`, con
permiso de escritura solo en el trabajo que crea el borrador. Si las políticas
del repositorio u organización bloquean Actions o ese permiso, habrá que
habilitarlos. Si la release ya existe, el workflow falla sin modificarla;
el ZIP queda disponible en los artefactos de la ejecución durante 14 días.

### Desde el código fuente

1. Instala Python 3.11 o superior.
2. Descarga o clona el repositorio.
3. Ejecuta `instalar.bat` una vez.
4. Ejecuta `iniciar.bat`.
5. Si el navegador no se abre, entra en `http://localhost:8501`.

## Desarrollo

Instala las dependencias y ejecuta las pruebas:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## Despliegue

La aplicación está preparada para Streamlit Community Cloud:

- rama: `main`;
- archivo principal: `app.py`;
- Python recomendado: 3.12.

Consulta [`DEPLOY_STREAMLIT.md`](DEPLOY_STREAMLIT.md) para los detalles.

Herramienta no oficial para uso personal. Las imágenes y marcas de
Magic: The Gathering pertenecen a sus respectivos titulares.
