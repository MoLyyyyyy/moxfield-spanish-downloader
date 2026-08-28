# Proxy Maker Studio — diseño de interfaz

## Dirección aprobada

Interfaz oscura y sobria, gris carbón con acento verde suave, centrada en
las cartas. Sergio ha aprobado la distribución de la maqueta interactiva:
mazos a la izquierda, galería en el centro y edición a la derecha.
Esta especificación concreta el alcance para revisión antes de implementar.

## Alcance

Rediseñar la presentación de los tres pasos: Importar, Revisar y PDF.
Conservar Streamlit, el servidor local y la ventana portable existentes.
No migrar a otro framework ni introducir servicios externos.
Aplicar el mismo diseño en web y escritorio, con sus respectivos mecanismos
actuales de guardar y descargar. No publicar ni crear releases como parte
de la aprobación del diseño.

## Estructura visual

- Cabecera compacta con identidad de Proxy Maker, navegación de los tres
  pasos y acceso a guardar/cargar proyecto. No duplicar barras de progreso.
- Panel de mazos con nombre, cantidad, código de tres letras y pendientes.
  El mazo activo se distingue por texto y selección, no solo por color.
- Galería con imágenes reales, nombre, copias y estado breve. Mostrar primero
  las cartas pendientes por defecto; conservar filtros y búsqueda existentes.
- Editor contextual al seleccionar una carta. Mantener la galería visible en
  escritorio; en ventanas estrechas apilar el editor sin comprimir controles.
- Fondo #141617, paneles #1b1e20, texto #eeeae3, texto secundario #a7adaa y
  acento #c2d69a. Tipografía de sistema, bordes discretos, foco visible y sin
  emojis decorativos como sustituto de etiquetas.

## Importar

Priorizar lista del mazo y acción de analizar. Conservar los métodos de
entrada ya disponibles, añadir/quitar mazos y configuración por mazo.
Agrupar preferencias secundarias sin eliminar controles funcionales.
Un proyecto vacío debe mostrar una entrada clara; no inventar mazos de ejemplo.
Mostrar progreso real y errores recuperables durante el análisis.

## Revisar

Cambiar de mazo o de carta no pierde correcciones ni repite búsquedas ya
resueltas. La selección se identifica con claves estables, no posiciones en
una lista cuyo orden puede cambiar al resolver pendientes.
Las imágenes ausentes tienen marcador explícito y acceso a MPCFill o subida.
El editor conserva Scryfall, MPCFill, subida, filtros, recorte, reparto de
copias entre ilustraciones y tratamiento independiente de caras jugables.
Las opciones avanzadas se agrupan, no se eliminan. La información de idioma
y calidad debe proceder de los datos reales, nunca de etiquetas decorativas.

## PDF

Priorizar vista previa, resumen mínimo y acción de generar/guardar.
La vista previa procede del PDF realmente generado, a resolución reducida,
con acceso a anverso/reverso; antes de generarlo no mostrar una hoja ficticia
como si fuera el resultado. Cambiar selecciones invalida el PDF y su vista previa.
Conservar el aviso de huecos libres, las validaciones que bloquean una salida
incompleta, los ajustes actuales, las marcas de corte y la división de archivos
sin separar pares dúplex. Los detalles técnicos secundarios quedan recogidos.

## Invariantes funcionales

- Búsqueda automática solo en alta resolución; mantener fallback de idioma.
- Sin imagen válida: no encontrada; elección manual de MPCFill o archivo.
- Códigos automáticos únicos de tres letras en traseras estándar, nunca sobre
  segundas caras jugables.
- Formato de proyectos compatible e imágenes restauradas bajo Datos en portable.
- No modificar dimensiones físicas, recorte ni algoritmos de PDF por estética.
- Sin sobrescritura silenciosa de exportaciones ni nuevos envíos de datos.
- No confundir cerrar la ventana con guardar automáticamente el proyecto.

## Organización técnica

Separar tema y componentes de presentación reutilizables del flujo de app.py.
Reutilizar los módulos de análisis, selección, persistencia y exportación.
Mantener controles interactivos de Streamlit con claves estables; el HTML de
la maqueta no es un frontend de producción ni se inserta como una app paralela.
Incluir los nuevos recursos de interfaz en el empaquetado portable.

## Criterios de aceptación

1. Importar, revisar dos mazos, cambiar ilustración, subir imagen, guardar y
   restaurar proyecto, y generar PDF sin perder correcciones.
2. Comprobar imágenes ausentes, alternativas inglesas, cartas de dos caras,
   varias ilustraciones, nombres largos y listas extensas.
3. Verificar vista previa y PDF con códigos y huecos correctos.
4. Inspeccionar visualmente a 1280×850 y 960×640; en web estrecha, sin controles
   ocultos ni solapados. Navegación por teclado y foco distinguible.
5. Suite de regresión, pruebas de interacción y smoke del portable. Validar
   la ventana nativa por separado cuando el entorno permita WebView2.

## Fuera de alcance

Nuevo motor de búsqueda, rediseño del formato impreso, sincronización en nube,
autoguardado, actualización automática y firma del ejecutable.
