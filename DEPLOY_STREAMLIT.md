# Despliegue en Streamlit Community Cloud

Repositorio:

`https://github.com/MoLyyyyyy/moxfield-spanish-downloader`

## 1. Subir el proyecto al repositorio

El contenido de este paquete debe quedar directamente en la raíz del
repositorio. La estructura principal debe verse así:

```text
moxfield-spanish-downloader/
├── .github/
│   └── workflows/
│       └── tests.yml
├── .streamlit/
│   └── config.toml
├── mtg_downloader/
├── tests/
├── app.py
├── requirements.txt
└── README.md
```

### Opción con Git

Clona el repositorio:

```powershell
git clone https://github.com/MoLyyyyyy/moxfield-spanish-downloader.git
cd moxfield-spanish-downloader
```

Copia dentro de esa carpeta todos los archivos de este paquete y ejecuta:

```powershell
git add .
git commit -m "Añadir aplicación Streamlit"
git push origin main
```

### Opción desde la web de GitHub

1. Abre el repositorio.
2. Pulsa **Add file**.
3. Pulsa **Upload files**.
4. Sube el contenido del paquete conservando las carpetas.
5. Confirma el commit en la rama `main`.

Para conservar correctamente carpetas ocultas como `.streamlit` y `.github`,
es más fiable utilizar Git desde el ordenador.

## 2. Desplegar en Streamlit

1. Entra en `https://share.streamlit.io`.
2. Inicia sesión con GitHub.
3. Pulsa **Create app**.
4. Selecciona **Yup, I have an app**.
5. Configura:
   - Repository: `MoLyyyyyy/moxfield-spanish-downloader`
   - Branch: `main`
   - Main file path: `app.py`
6. En **Advanced settings**, selecciona Python `3.12`.
7. No hace falta configurar secretos.
8. Pulsa **Deploy**.

## 3. Actualizaciones

Después del despliegue, Streamlit vigilará el repositorio. Los cambios enviados
a `main` se aplicarán automáticamente.

## Notas

- Moxfield utiliza una API interna y puede bloquear peticiones procedentes de
  servidores en la nube. La aplicación mantiene el campo para pegar una
  exportación de texto como alternativa.
- Generar un mazo completo en PNG puede consumir bastante memoria. Si el
  despliegue se queda sin recursos, prueba temporalmente con JPG grande.
- Los archivos temporales y la caché del servidor no deben considerarse
  permanentes.
