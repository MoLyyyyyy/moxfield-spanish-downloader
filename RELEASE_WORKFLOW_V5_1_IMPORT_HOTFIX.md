# Workflow v5.1 import hotfix

Corrige el error de arranque:

`ImportError: cannot import name 'filter_scryfall_alternatives'`

La causa era un despliegue parcial con `app.py` de workflow-v5 y un
`mtg_downloader/review.py` anterior. El filtro de versiones se define ahora
directamente en `app.py`, eliminando ese punto frágil de importación.
