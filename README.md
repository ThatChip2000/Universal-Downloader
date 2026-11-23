# Universal Downloader (`v3.0.3`)

Aplicación de escritorio nativa para Windows con interfaz rápida en **C++ (`PySide6 / Qt6 Widgets`)** para descargar y recortar videos (`MP4`), audios (`MP3`), imágenes y `GIF` animados desde **YouTube**, **TikTok**, **Instagram**, **Facebook** y **Twitter (X)**.

---

## ✨ Características Principales

- **Interfaz Nativa en Qt6 (`PySide6`):** Arranque rápido, bajo consumo de CPU/RAM (`< 0.5%` al redimensionar o desplazar listas largas), soporte de tema **Oscuro / Claro** y vista previa con miniatura asíncrona.
- **Pestaña 1 — Descarga General y Listas de Reproducción:**
  - Selección de formato (`Video MP4`, `Audio MP3`, `Imagen / GIF`) y calidad (`4K`, `2K`, `1080p`, `720p`, `480p`, `360p` o `320 / 256 / 192 / 128 kbps` en MP3).
  - Cálculo de peso real en tiempo real consultando encabezados HTTP (`Content-Length` / `Range`) en paralelo y manejo automático de flujos `HLS (m3u8)` para archivos grandes en X/Twitter (`> 900 MB`).
  - **Checklist interactiva para Listas de Reproducción** con selectores individuales de formato y calidad por fila (permite combinar `MP4` y `MP3` en una misma lista).
- **Pestaña 2 — Recortar Fragmento (`Clip`):**
  - Línea de tiempo dual interactiva (`Inicio` y `Fin`) con topes independientes y descarga parcial directa con corte exacto (`FFmpeg`) en `MP4`, `MP3` o `GIF` animado de alta definición.
- **Auto-Actualizador Integrado:**
  - **`Consultar Actualización`** y **`Actualizar API`** verifican y descargan la última versión oficial de `yt-dlp.exe` en `%LOCALAPPDATA%\UniversalDownloader\bin\yt-dlp.exe` directamente desde la interfaz, sin necesitar Python instalado.

---

## 📦 Descarga Portable (Sin Instalar Python)

Puedes descargar el ejecutable listo para usar desde la sección **[Releases](../../releases)**:
- **`Universal Downloader.exe`**: Ejecutable único 100% portable (incluye `FFmpeg`, `PySide6`, `yt-dlp` y `gallery-dl`).
- **`Universal_Downloader_Portable.zip`**: Paquete comprimido con instrucciones y script `Desbloquear_y_Abrir.bat` para evitar avisos de SmartScreen al compartir.

---

## 🛠️ Ejecución desde Código Fuente

1. Crear o activar un entorno virtual en Python `3.10+`:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Ejecutar la aplicación:
   ```powershell
   python app.py
   ```
3. Para recompilar el ejecutable portable `.exe`:
   ```powershell
   pyinstaller --clean --noconfirm --distpath "." "Universal Downloader.spec"
   ```
