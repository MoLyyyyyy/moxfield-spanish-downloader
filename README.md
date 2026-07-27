# Moxfield Cartas ES

Aplicación que recibe una exportación de texto de Moxfield y genera un ZIP
con las imágenes de las cartas, priorizando versiones oficiales en español
disponibles en Scryfall.

## Funciones

- Permite pegar una exportación de texto.
- Busca primero la misma edición y número de coleccionista en español.
- Si no existe, busca esa misma edición en inglés.
- Si tampoco existe, busca otra impresión oficial española.
- Y por último otra impresión en inglés.
- Soporta cartas de dos caras.
- Crea siempre una imagen independiente por cada copia del mazo.
- Genera un `informe.csv` dentro del ZIP.
- Utiliza caché local para evitar descargas repetidas.

## Instalación en Windows

1. Instala Python 3.11 o superior.
2. Descomprime este proyecto.
3. Ejecuta `instalar.bat` una vez.
4. Ejecuta `iniciar.bat` para abrir la aplicación.
5. Si no se abre el navegador, entra en `http://localhost:8501`.

## Uso

1. Exporta o copia la lista del mazo desde Moxfield.
2. Elige la calidad y opciones.
3. Pulsa **Preparar ZIP**.
4. Revisa la tabla.
5. Pulsa **Descargar ZIP**.

### Cómo introducir el mazo

1. Abre el mazo en Moxfield.
2. Utiliza una exportación de texto con cantidad y nombre.
3. Pégala en **Lista del mazo**.
4. Pulsa de nuevo **Preparar ZIP**.

Ejemplo:

```text
Commander:
1 Sauron, the Dark Lord (LTR) 224

Deck:
1 Sol Ring (CMM) 396
10 Swamp (FDN) 277
```


## Modos de búsqueda de impresión

La web permite elegir entre tres comportamientos:

### Exacta primero

1. Misma edición y número en español.
2. Misma edición y número en inglés.
3. Otra impresión en español.
4. Otra impresión en inglés.

### Solo exacta

1. Misma edición y número en español.
2. Misma edición y número en inglés.
3. Si no existe, la carta se marca como no encontrada.

Este modo requiere que la lista incluya edición y número de coleccionista.

### Flexible

1. Cualquier impresión oficial en español.
2. Cualquier impresión en inglés.

Este modo ignora la edición indicada en la lista y prioriza únicamente el idioma.

## Orden de selección

1. Misma edición y número en español.
2. Misma edición y número en inglés.
3. Otra impresión oficial en español.
4. Otra impresión inglesa por nombre exacto.

## Avisos

- No todas las cartas tienen una imagen oficial en español.
- Herramienta no oficial para uso personal.

## Cantidades y cartas repetidas

Las cantidades se respetan siempre. Por ejemplo:

- `8 Mountain` genera ocho archivos de imagen.
- `3 Nazgûl` genera tres archivos de imagen.
- Un mazo Commander de 100 cartas genera 100 copias físicas representadas.

Las cartas de doble cara generan una imagen para cada cara de cada copia. Por
tanto, el número de archivos de imagen puede superar 100 aunque el mazo tenga
100 cartas físicas.


## Calidad de imagen

La aplicación ofrece dos modos:

- **PNG — máxima calidad (recomendado)**: intenta descargar la versión PNG de
  Scryfall, que normalmente es la más nítida y uniforme.
- **JPG grande**: ocupa menos espacio, pero puede verse algo peor.

Si ves diferencias de calidad entre cartas, normalmente se debe a una de estas
razones:

1. Se descargó en JPG en vez de PNG.
2. La edición elegida tiene un escaneo antiguo o menos nítido en Scryfall.
3. La carta ha tenido que cambiar de edición para encontrar idioma.

El `informe.csv` incluye ahora una columna `formato_descarga` para que puedas
ver si esa carta se bajó como PNG o JPG.

## Despliegue web

La aplicación está preparada para Streamlit Community Cloud.

- Archivo principal: `app.py`
- Rama recomendada: `main`
- Python recomendado: `3.12`
- Dependencias: `requirements.txt`

Consulta [`DEPLOY_STREAMLIT.md`](DEPLOY_STREAMLIT.md) para ver todos los pasos.


## Control de calidad del escaneo

El formato PNG no mejora por sí solo un escaneo de origen pixelado. La
aplicación consulta los metadatos de Scryfall y permite elegir:

- **Preferir alta resolución**: busca primero candidatos `highres_scan`; solo
  usa una imagen `lowres` cuando no existe ninguna alternativa compatible.
- **Respetar prioridad**: mantiene estrictamente el orden de edición e idioma,
  aunque la primera imagen disponible esté marcada como `lowres`.
- **Solo alta resolución**: no descarga imágenes `lowres`.

El informe incluye las columnas `estado_imagen` y `alta_resolucion`. Ten en
cuenta que priorizar calidad puede hacer que se seleccione otra edición o una
versión inglesa antes que una impresión española de baja resolución.

## Perfiles de descarga

La interfaz principal utiliza perfiles para evitar que el usuario tenga que
combinar manualmente edición, idioma y calidad:

- **Equilibrado — recomendado**: intenta respetar la edición, prioriza alta
  resolución y usa inglés como respaldo. Las imágenes low-res son el último
  recurso.
- **Fidelidad al listado**: solo descarga la edición y número indicados,
  priorizando español y después inglés aunque la imagen sea low-res.
- **Máxima calidad**: ignora la edición y solo acepta imágenes de alta
  resolución, primero en español y después en inglés.
- **Solo español**: nunca utiliza imágenes inglesas; puede cambiar de edición
  para encontrar una impresión española de mejor calidad.

Los controles técnicos siguen disponibles en **Opciones avanzadas**, donde se
pueden personalizar la prioridad de impresión, el idioma, la calidad mínima y
el formato del archivo.

## Entrada del mazo

La aplicación ya no intenta leer enlaces de Moxfield. Esta integración dependía
de una API interna no documentada y podía fallar por cambios o bloqueos de
Cloudflare.

Ahora existen dos formas estables de introducir el mazo:

1. Pegar directamente la exportación de texto.

Se conservan las cantidades, edición, número de coleccionista y marcas como
`*F*`, que se ignoran para seleccionar la imagen.

## Revisión visual y selección manual

El proceso se divide en tres fases:

1. **Analizar mazo**: la aplicación selecciona automáticamente una impresión
   para cada carta.
2. **Revisar impresiones**: se muestra una tabla y un panel de previsualización.
   Puedes filtrar las cartas problemáticas y la aplicación cargará automáticamente
   hasta 18 alternativas. Puedes elegir manualmente otra edición, idioma o
   ilustración. Una carta en inglés no se considera problemática por sí sola.
3. **Generar ZIP**: se descargan las selecciones definitivas respetando todas
   las cantidades.

Las alternativas se consultan bajo demanda para no cargar simultáneamente las
imágenes de las 100 cartas. Las cartas de doble cara muestran sus distintas
caras y conservan ambas al generar el ZIP.


## Revisión fluida sin recargar toda la página

La zona de revisión utiliza `st.fragment`. Al cambiar de carta, mantener una
selección o elegir una impresión alternativa, Streamlit actualiza únicamente
ese panel en lugar de ejecutar visualmente toda la página.

La revisión incluye:

- barra de progreso;
- botones **Anterior** y **Siguiente**;
- botón **Mantener actual y continuar**;
- selección manual mediante **Elegir y continuar**;
- avance automático a la carta siguiente después de guardar una versión.


### Disposición de la revisión

Las alternativas aparecen directamente a la derecha de la versión seleccionada,
de modo que la comparación visual sea más intuitiva. Los detalles compactos de
la carta aparecen justo debajo de su imagen, dentro de la columna izquierda.


## Diseños comunitarios de MPCFill

La revisión permite alternar entre impresiones oficiales de Scryfall y diseños
comunitarios de MPCFill. Para cada diseño se muestran su fuente, idioma y DPI.

Las imágenes de MPCFill pueden incluir el sangrado de impresión. La aplicación
ofrece tres modos:

- **Automático**: detecta la proporción con sangrado y lo elimina.
- **Mantener sangrado**: conserva la imagen original.
- **Forzar recorte MPC**: elimina siempre el margen estándar de 3,048 mm.

La miniatura mostrada y el archivo final del ZIP utilizan el mismo modo de
recorte. Si MPCFill no está disponible, Scryfall continúa funcionando con
normalidad.
