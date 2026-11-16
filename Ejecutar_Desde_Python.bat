@echo off
title Universal Downloader (Modo Python con Auto-Actualizacion)
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app.py"
) else (
    python "app.py"
)
