# Workflow v5.4.5 reskin search hotfix

Generaliza la resolución de nombres alternativos. Para cartas con edición y número de coleccionista, Scryfall se usa para recuperar el nombre Oracle y los nombres de presentación de esa impresión. MPCFill prueba esos nombres en orden y Scryfall usa el nombre Oracle para mostrar reimpresiones.

Caso de regresión principal: `Fangorn Forest (LTC) 377` se reconoce como la impresión temática de `Yavimaya, Cradle of Growth`, sin perder el nombre Fangorn Forest como alias de búsqueda.
