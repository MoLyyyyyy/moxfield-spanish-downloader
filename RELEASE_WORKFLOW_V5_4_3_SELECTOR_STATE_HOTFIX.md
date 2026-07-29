# Workflow v5.4.3 selector state hotfix

Corrige el error `ValueError: invalid literal for int() with base 10: 'Mazo 1'`.

La sesión podía conservar la etiqueta visible del selector anterior. La nueva versión migra etiquetas como `Mazo 1` o `Mazo 2 · Nombre` a índices internos, utiliza una clave de widget nueva y mantiene separado el índice activo.
