# Contexto Completo del Proyecto - Universal Downloader (`v3.0.1`)

Este documento resume el estado actual, la arquitectura, las funcionalidades implementadas y las decisiones tomadas durante el desarrollo de **Universal Downloader**, para poder continuar el proyecto en una nueva carpeta y conversación de Antigravity sin partir desde cero.

---

## 1. Descripción General y Prioridades del Usuario

**Universal Downloader** es una aplicación de escritorio para Windows orientada a descargar contenido multimedia (video, audio MP3, imágenes y GIFs) desde múltiples plataformas (`YouTube`, `TikTok`, `Instagram`, `Facebook`, `Twitter / X` y `Suno`).

### Requisitos prioritarios definidos por el usuario
1. **Fácil distribución:** Un único ejecutable portable (`Universal Downloader.exe`) que cualquier persona pueda abrir en Windows sin instalar Python ni dependencias.
2. **Arranque rápido y bajo consumo de CPU/RAM:** Sin tirones ni picos de procesador al redimensionar la ventana, mover barras deslizantes o desplazar listas largas.
3. **Diseño funcional y cómodo a la vista:** Interfaz sobria y limpia, sin estridencias visuales, con soporte para tema **Oscuro** y **Claro** (además de recordar preferencias entre sesiones).

---

## 2. Stack Tecnológico Actual (`v3.0.0`)

- **Lenguaje:** Python (`3.10.6` en el entorno virtual `.venv`).
- **Motor Gráfico (GUI):** `PySide6 >= 6.8.0` (**Qt6 Widgets nativo en C++**, instalado `6.12.0`).
  - Reemplazó por completo a `CustomTkinter`, `Tkinter` y `Pillow` (eliminados del proyecto).
- **Motores de Extracción y Descarga:**
  - `yt-dlp >= 2024.10.22` (librería integrada + soporte para motor externo actualizable `yt-dlp.exe` desde la propia app).
  - `gallery-dl >= 1.27.0` (respaldo para extracción de imágenes fijas).
  - Respaldo propio por API (`api.fxtwitter.com`) para publicaciones de X/Twitter restringidas a invitados.
- **Procesamiento Multimedia:** `imageio-ffmpeg >= 0.5.1` (`ffmpeg.exe` integrado para unir flujos HD, convertir a MP3/GIF y recortar fragmentos exactos).
- **Empaquetado:** `pyinstaller >= 6.11.0`.

---

## 3. Archivos Principales del Proyecto

- **`app.py`**: Lógica principal de la aplicación (`UniversalDownloaderApp`), construcción de las 2 pestañas, análisis de enlaces, cálculo de peso exacto desde CDN, descarga de videos/listas/clips, manejo de caché LRU (`32` URLs y `32` miniaturas) y actualización del motor API.
- **`qt_backend.py`**: Capa de compatibilidad y motor gráfico nativo en `PySide6` (`Qt6 Widgets`).
  - Implementa los componentes (`CTk`, `CTkFrame`, `CTkScrollableFrame`, `CTkLabel`, `CTkButton`, `CTkEntry`, `CTkComboBox`, `CTkOptionMenu`, `CTkSegmentedButton`, `CTkSlider`, `CTkProgressBar`, `CTkTextbox`, `CTkCheckBox`, `BooleanVar`) sobre widgets nativos de Qt6 en C++.
  - `decode_thumbnail_bytes_to_ctk_image()`: Decodifica y escala miniaturas (`88x50 px`) directamente en C++ usando `QImage` / `QPixmap` sin `Pillow`.
  - `_UiDispatcher(QObject)`: Despachador thread-safe basado en señales `QueuedConnection` y `QTimer` para actualizar la UI desde hilos secundarios (`after` / `after_cancel`).
  - `DARK_STYLESHEET` y `LIGHT_STYLESHEET`: Hojas de estilo QSS con cambio dinámico completo mediante `set_appearance_mode()`.
- **`requirements.txt`**: Dependencias limpias (`PySide6`, `yt-dlp`, `gallery-dl`, `imageio-ffmpeg`, `requests`, `pyinstaller`).
- **`Universal Downloader.spec`**: Configuración de PyInstaller optimizada para `PySide6`, incluyendo `qt_backend` y excluyendo módulos pesados no utilizados (`QtWebEngine*`, `QtQml`, `QtQuick*`, `Qt3D*`, `QtMultimedia*`, `QtCharts`, `QtPdf`, `QtNetwork`, `QtSql`, `QtTest`, `QtXml`, `tkinter`, `customtkinter`, `PIL`).
- **`version_info.txt`**: Metadatos de versión de Windows configurados en `3.0.1.0`.
- **`HISTORIAL_VERSIONES.md`**: Registro cronológico completo de cambios hasta `v3.0.1`.
- **Artefactos compilados (última compilación verificada):**
  - `Universal Downloader.exe` (`89.8 MB`, verificado que inicia correctamente).
  - `Universal_Downloader_Portable.zip` (`89.3 MB`).

---

## 4. Funcionalidades Implementadas (100% Operativas)

### Pestaña 1: `Descarga General / Listas`
- **Análisis automático con debounce (`300 ms`)** al pegar o escribir un enlace, más botones de `Pegar`, `Calcular Peso` y `Limpiar`.
- **Tarjeta de vista previa con miniatura (`88x50 px`)** descargada de forma asíncrona sin bloquear la UI.
- **Cálculo de peso exacto en tiempo real:** Consulta encabezados HTTP (`HEAD` / `Range`) en paralelo (`_populate_missing_direct_filesizes`) para obtener el tamaño real en bytes desde el CDN (corrigiendo estimaciones infladas de `yt-dlp` en plataformas como X/Twitter).
- **Selectores globales:** `Formato` (`Video MP4`, `Audio MP3`, `Imagen / GIF`) y `Calidad`.
- **Checklist interactiva para Listas de Reproducción:**
  - Detección rápida (`extract_flat: "in_playlist"`).
  - Renderizado progresivo por lotes (`_PlaylistRowComboProxy`) para no congelar la ventana.
  - Cada fila incluye casilla de selección y **2 selectores desplegables individuales** (`Formato: Video MP4 / Audio MP3` y `Calidad`), permitiendo descargas mixtas en una misma lista.
- **Respaldo automático para X/Twitter `+18` (`possibly_sensitive: true`):**
  - `_extract_twitter_fallback_info` y `_download_twitter_fallback` consultan `api.fxtwitter.com` cuando `yt-dlp` falla por bloqueo de Guest Token anónimo.

### Pestaña 2: `Recortar Fragmento (Clip)`
- **Módulo independiente** accesible desde el selector superior de pestañas (`CTkSegmentedButton`).
- **Pre-análisis de duración y vista previa** del enlace (`_analyze_clip_url_worker` usando la caché compartida `_url_info_cache`).
- **Línea de tiempo dual sincronizada:**
  - Dos campos editables (`MM:SS` / `HH:MM:SS`) y dos barras deslizantes (`Inicio (Desde)` y `Fin (Hasta)`).
  - **Tope físico independiente:** Al bajar `Fin`, se detiene al topar con `Inicio` (`Inicio + 1 s`) sin arrastrar ni mover `Inicio`; al subir `Inicio`, se detiene al topar con `Fin` (`Fin - 1 s`).
- **Formatos y calidades propias del recorte:** `Video MP4`, `Audio MP3` y `Imagen / GIF` (con calidades específicas de resolución/FPS para GIF).
- **Descarga parcial directa:** Usa `download_ranges` y `force_keyframes_at_cuts` con `FFmpeg`, guardando los archivos con etiqueta `[Clip MMmSSs-MMmSSs]` para no sobrescribir recortes previos.

### Sistema de Actualización y Persistencia
- Verificación de versión local vs remota de `yt-dlp` (`Consultar Actualización` y `Actualizar API`).
- Caché de versión del motor externo en `%LOCALAPPDATA%\UniversalDownloader\config.json` para evitar demoras al iniciar.
- Persistencia automática de carpeta de descarga y tema (`Oscuro` / `Claro` / `Sistema`).
- Registro de actividad en tiempo real acotado a `500` bloques en C++ (`QPlainTextEdit.document().setMaximumBlockCount(500)`).

---

## 5. Resumen de Decisiones de la Conversación

1. **Rendimiento al redimensionar la ventana:** Se explicó que `CustomTkinter` redibujaba formas sobre un lienzo de `Tkinter` desde Python en cada evento de redimensionamiento, generando ~6% de CPU y tirones. Se evaluaron alternativas (Java, Cobalt, otras UIs) y se decidió mantener la lógica de Python (`yt-dlp` + `FFmpeg`) migrando únicamente la capa visual a **Opción B: `PySide6` (`Qt6 Widgets` en C++)**, logrando `< 0.5%` de CPU al redimensionar y compilación en un solo `.exe`.
2. **Módulo de Clip (`v2.5.0` -> `v2.5.2`):** Se implementó en pestaña separada, se corrigió el pre-análisis (`_url_info_cache`) y se ajustaron los sliders para que `Fin` e `Inicio` no se arrastren entre sí.
3. **Videos de X/Twitter restringidos (`v2.5.3`):** Se diagnosticó el bloqueo de Guest Token en cuentas marcadas como `possibly_sensitive: true` y se añadió el respaldo automático por `api.fxtwitter.com`.
4. **Migración a `PySide6` (`v3.0.0`):** Se implementó `qt_backend.py`, se actualizó `app.py`, se corrigió el refresco de tema dinámico y la alineación de columnas en `QGridLayout`, y se compiló el nuevo `Universal Downloader.exe` (`89.8 MB`).
5. **Nota sobre MEGA:** Se analizó brevemente su viabilidad técnica, pero el usuario indicó expresamente **ignorar el tema de MEGA** para continuar el proyecto.

---

## 6. Guía Rápida para la Nueva Conversación de Antigravity

Al abrir el proyecto en su nueva carpeta, el agente debe:
1. Verificar la ruta actual del directorio de trabajo (`app.py`, `qt_backend.py`, `Universal Downloader.spec`).
2. Considerar que la aplicación ya se encuentra en **`v3.0.0` sobre `PySide6` (`Qt6 Widgets`)** (no `CustomTkinter`).
3. Si se realizan cambios en el código y se necesita recompilar el ejecutable portable, usar el entorno virtual `.venv` con `pyinstaller --clean --noconfirm "Universal Downloader.spec"`.
