# Workflow v5.4.2 deck controls hotfix

Corrige el `NameError: deck_count is not defined` al añadir un mazo y volver a
renderizar el paso 1.

También sincroniza los valores actuales del editor antes de añadir o eliminar
un mazo, evitando perder cambios que todavía solo estaban en el estado de los
widgets de Streamlit.
