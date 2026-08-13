# Workflow v5.4.4 printing identity hotfix

Corrige dos problemas de identidad/búsqueda de cartas:

- Las entradas con el mismo nombre pero distinta edición o número de coleccionista se mantienen independientes durante parser, análisis y revisión. Caso de regresión: los nueve `Nazgûl (LTR)` 100/332-339 permanecen como nueve entradas.
- El fallback del endpoint legacy de MPCFill ya no agrupa consultas con el mismo nombre cuando tienen collector distinto.
- Las acciones masivas de unificación solo afectan ahora a duplicados exactos (nombre + set + collector).
- El selector de revisión muestra set y collector para distinguir visualmente impresiones homónimas.
- Las búsquedas manuales usan el nombre canónico/Oracle devuelto por Scryfall cuando la lista usa un nombre alternativo o reskin. Ejemplo: `Paths of the Dead (LTC) 362` busca diseños como `Cavern of Souls`.
- Si el análisis automático con MPCFill no encuentra un reskin, se consulta su impresión exacta en Scryfall y se reintenta MPCFill con el nombre canónico.
- Se incrementa `ANALYSIS_ENGINE_VERSION` para impedir reutilizar análisis antiguos con la identidad anterior.
