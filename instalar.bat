@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo No se ha encontrado Python. Instala Python 3.11 o superior.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :error
pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Instalacion completada.
pause
exit /b 0

:error
echo.
echo La instalacion ha fallado. Revisa los mensajes anteriores.
pause
exit /b 1
