@echo off
rem Avvia Cheatsheet Viewer nel proprio ambiente virtuale (.venv).
rem Alla prima esecuzione crea .venv e installa le dipendenze.
cd /d "%~dp0"

if not exist "config.json" (
    copy /y "config.example.json" "config.json" >nul
    echo config.json creato da config.example.json: imposta il percorso del tuo vault.
)

if not exist ".venv\Scripts\python.exe" (
    echo Creazione ambiente virtuale...
    python -m venv .venv || goto :errore
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :errore
)

".venv\Scripts\python.exe" cheatsheet.py
if errorlevel 1 goto :errore
exit /b 0

:errore
echo.
echo Si e' verificato un errore. Premi un tasto per chiudere.
pause >nul
exit /b 1
