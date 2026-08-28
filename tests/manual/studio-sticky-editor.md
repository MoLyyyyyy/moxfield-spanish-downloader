# Panel de carta seleccionado: comprobación de scroll

Usar la aplicación real con un mazo cuya galería supere la altura de la
ventana y una carta seleccionada. No basta con comprobar el texto del CSS.

1. A 1280×850, desplazar la página desde la galería 250 px hacia abajo.
   El editor debe permanecer visible bajo la cabecera, sin tapar la galería.
   Antes del cambio su borde superior salía de la ventana (reproducido).
2. Seguir desplazando la galería mientras quede contenido por debajo:
   el panel acompaña el desplazamiento, limitado al espacio de revisión.
3. Situar el puntero sobre el editor y desplazar hacia abajo: se deben poder
   alcanzar las fuentes y el control de subida sin mover la galería.
4. A 960×640, los paneles deben seguir apilados y desplazarse normalmente;
   el editor no debe quedar fijado sobre las cartas ni limitar su altura.

Resultado 2026-08-28: comprobación visual correcta en ambos tamaños, con
modelos reales e imágenes locales de prueba. Suite Python: 268 passed.
