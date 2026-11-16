@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -Path '%~dp0Universal Downloader.exe' -ErrorAction SilentlyContinue"
start "" "%~dp0Universal Downloader.exe"
