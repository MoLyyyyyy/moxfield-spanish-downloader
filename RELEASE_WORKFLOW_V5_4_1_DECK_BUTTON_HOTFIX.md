# Workflow v5.4.1 deck button hotfix

Corrige `StreamlitAPIException` al pulsar **➕** o **🗑️**.

`deck_config_active` es la clave del `st.radio` de mazos. Streamlit no permite
modificar esa clave después de crear el widget durante la misma ejecución.
Los botones guardan ahora el destino en `deck_config_active_pending`; la clave
del selector se actualiza al principio del siguiente rerun, antes de crear el
widget.
