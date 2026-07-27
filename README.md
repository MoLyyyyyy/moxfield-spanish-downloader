# Moxfield Cartas ES

Aplicación local que recibe un enlace público de Moxfield y genera un ZIP
con las imágenes de las cartas, priorizando versiones oficiales en español
disponibles en Scryfall.

## Funciones

- Lee un mazo público mediante su enlace de Moxfield.
- Permite pegar una exportación de texto como respaldo.
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

1. Pega el enlace público de Moxfield.
2. Elige la calidad y opciones.
3. Pulsa **Preparar ZIP**.
4. Revisa la tabla.
5. Pulsa **Descargar ZIP**.

### Si Moxfield bloquea la lectura

Moxfield usa un endpoint interno no documentado y puede protegerlo mediante
Cloudflare. En ese caso:

1. Abre el mazo en Moxfield.
2. Utiliza una exportación de texto con cantidad y nombre.
3. Pégala en **Exportación de texto de respaldo**.
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

- La integración de Moxfield puede necesitar ajustes futuros.
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
