# Workflow v5.2 project state fix

Corrige un fallo por el que el botón **Guardar proyecto completo** podía
mantener los datos anteriores a la última selección manual.

La causa era el uso de fragmentos de Streamlit: la edición de cartas actualizaba
el fragmento, pero no volvía a calcular el JSON situado en la parte superior.

La v5.2 fuerza una actualización completa después de cualquier cambio de
versión, reparto o recorte. El archivo incluye además una huella SHA-256 de
todas las selecciones y la valida al cargarlo.
