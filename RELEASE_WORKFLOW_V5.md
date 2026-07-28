# Proxy Maker workflow v5

Esta versión agrupa las mejoras de seguridad, revisión y preimpresión.

## Proyectos completos

La aplicación puede guardar un JSON con las listas, la configuración de cada
mazo, las versiones seleccionadas, los repartos entre ilustraciones, los
recortes MPCFill, los mazos revisados, la carta abierta y los ajustes del PDF.
El archivo puede cargarse posteriormente sin repetir las búsquedas.

## Reanálisis individual

Desde el paso de revisión se puede cambiar la fuente, idioma, política de
edición, calidad y formato de imagen del mazo activo. Se puede reintentar solo
lo pendiente o reanalizar todo ese mazo, conservando opcionalmente las
selecciones y recortes manuales. Los demás mazos no se modifican.

## Preimpresión

El paso final muestra incidencias por mazo y carta: imágenes ausentes, baja
resolución, idioma de respaldo, edición distinta, cartas dobles incompletas,
recortes manuales y mazos no revisados. Las incidencias de carta incluyen un
acceso directo a su editor.

## Mapas y división

Se genera un mapa de hoja y posición para cada mazo, descargable en CSV y PDF.
Al dividir archivos superiores a 200 MB se mantienen las parejas dúplex y se
priorizan los finales de mazo que coinciden exactamente con el final de una
hoja.

## Selector Scryfall

Además de idioma y calidad, permite filtrar por edición, año, artista y
tratamiento, limitarse a la edición solicitada y ordenar por fecha ascendente,
fecha descendente o alta resolución.
