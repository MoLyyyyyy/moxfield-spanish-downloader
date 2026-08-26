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
