@echo off
title Actualizador de Universal Downloader
cd /d "%~dp0"
echo ================================================================
echo Actualizando motores yt-dlp y gallery-dl a la ultima version...
echo ================================================================
".venv\Scripts\python.exe" -m pip install --upgrade yt-dlp gallery-dl
echo.
echo ================================================================
echo Recompilando ejecutable Universal Downloader.exe con metadatos...
echo ================================================================
if exist "Universal Downloader.old.exe" del /f /q "Universal Downloader.old.exe" >nul 2>&1
if exist "Universal Downloader.exe" move /y "Universal Downloader.exe" "Universal Downloader.old.exe" >nul 2>&1
".venv\Scripts\pyinstaller.exe" --clean --noconfirm --distpath "." "Universal Downloader.spec"
if exist "Universal Downloader.old.exe" del /f /q "Universal Downloader.old.exe" >nul 2>&1
echo.
echo ================================================================
echo Actualizando paquete Universal_Downloader_Portable.zip...
echo ================================================================
powershell -NoProfile -Command "Compress-Archive -Force -Path 'Universal Downloader.exe', 'LEEME_ANTES_DE_ABRIR.txt', 'Desbloquear_y_Abrir.bat' -DestinationPath 'Universal_Downloader_Portable.zip'"
echo.
echo ================================================================
echo Proceso completado. Ya puedes abrir "Universal Downloader.exe"
echo o subir "Universal_Downloader_Portable.zip" a Google Drive.
echo ================================================================
pause
