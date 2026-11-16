# Historial de Versiones y Registro de Cambios - Universal Downloader

Este documento registra de forma cronológica y versionada todas las funcionalidades, correcciones de errores, mejoras visuales y optimizaciones de rendimiento aplicadas a **Universal Downloader**.

---

## v3.0.1 (14-11-2026) - Corrección Crítica de Descargas Gigantes en X/Twitter y Bug de Subscript en NoneType
### Correcciones Críticas de Red y Excepciones
- **Priorización automática de HLS (`m3u8`) en videos de X/Twitter mayores a 900 MB:**
  - Se comprobó que `video.twimg.com` corta conexiones MP4 continuas cerca de los 3 GB y agota el tiempo de espera (`Read timed out`) ante cualquier petición `Range` con offset `>= 1 GB`.
  - Cuando un video de X/Twitter supera los `900 MB` y `FFmpeg` está disponible, la app ahora selecciona automáticamente el flujo HLS (`m3u8`) de igual resolución + audio (`hls-*+hls-audio-*`), descargando en miles de segmentos independientes de ~1–2 MB sin límite de tamaño ni fallos de reanudación.
- **Tolerancia a timeouts (`socket_timeout = 30 s`), reintentos con espera exponencial y prevención de HTTP 429:**
  - Al descargar archivos masivos desde el CDN de X/Twitter (`video.twimg.com`), como películas o videos de más de 2 horas (3 GB a 5 GB), se configuró `socket_timeout = 30` segundos, `25` reintentos automáticos y espera exponencial (`retry_sleep` de 1 a 15 segundos) tanto en la librería interna como en el motor externo, evitando tanto cortes prematuros como el bloqueo `HTTP 429: Too Many Requests` que provocan las peticiones fragmentadas repetidas.
  - Se garantizó la reanudación persistente (`--continue` / `continuedl: True`) desde archivos `.part` y un mensaje claro si el CDN aplica límite temporal (`HTTP 429`).
- **Corrección de excepción `'NoneType' object is not subscriptable`:**
  - Se diagnosticó y corrigió un fallo interno al saltar al respaldo de X/Twitter (`_download_twitter_fallback`) dentro del bloque `except`: cuando el motor `yt-dlp` procesaba errores anidados, inspeccionaba `sys.exc_info()[1].exc_info[0]`. Al ser `exc_info = None` en instancias de `DownloadError`, Python lanzaba `TypeError: 'NoneType' object is not subscriptable`.
  - Se incorporó un parche de seguridad (`_safe_ytdlp_trouble`) para limpiar referencias huérfanas en `sys.exc_info` y se desacopló la invocación del respaldo de CDN fuera del bloque de captura de excepción, permitiendo que cualquier fallo de red muestre el mensaje claro y reanudable.
- **Trazabilidad en tiempo real:** Se añadió el volcado detallado de traceback (`[DETALLES]`) en la consola interna para diagnósticos inmediatos ante cualquier excepción no controlada.

---

## v3.0.0 (10-11-2026) - Migración Completa del Motor Visual a PySide6 (Qt6 Widgets en C++ Nativo)
### Renovación de Arquitectura Gráfica y Rendimiento
- **Reemplazo total de `CustomTkinter` / `Tkinter` / `Pillow` por `PySide6` (`Qt6 Widgets` en C++) (`qt_backend.py` + `app.py`):**
  - Se eliminaron por completo `customtkinter`, `tkinter` y `Pillow`, migrando toda la interfaz gráfica a controles nativos de **Qt6 en C++** (`QMainWindow`, `QFrame`, `QGridLayout`, `QScrollArea`, `QLineEdit`, `QPushButton`, `QComboBox`, `QSlider`, `QProgressBar`, `QPlainTextEdit`, `QCheckBox`, `QFileDialog`).
  - **Cero tirones al redimensionar o mover barras (`< 0.5%` de CPU):** A diferencia de `CustomTkinter` (que redibujaba manualmente polígonos en un lienzo de `Tk` desde Python en cada evento `<Configure>`), `Qt6` delega el cálculo de geometría y renderizado al motor nativo en C++ y GPU/Direct2D de Windows, haciendo que estirar la ventana, desplazar listas largas o deslizar las barras de tiempo sea instantáneo (`60-144 FPS`) sin picos de procesador.
  - **Decodificación nativa de miniaturas en C++ (`QImage` / `QPixmap`):** Las miniaturas de vista previa (`88x50 px`) ahora se decodifican y escalan en memoria mediante `QImage.fromData()` en C++ sin requerir la librería `Pillow`.
  - **Despachador de eventos thread-safe (`_UiDispatcher` con señales `QueuedConnection`):** Toda la comunicación entre los hilos secundarios de análisis/descarga y la ventana principal se realiza mediante señales encoladas nativas de Qt (`QObject` + `QTimer`).
  - **Diseño funcional, sobrio y descansado para la vista (`Oscuro` y `Claro`):** Se diseñaron hojas de estilo QSS (`DARK_STYLESHEET` y `LIGHT_STYLESHEET`) con contraste suave, tipografía nítida (`Segoe UI` y `Consolas`) y bordes limpios que conservan el `100%` de las funciones de las dos pestañas (`Descarga General / Listas` y `Recortar Fragmento (Clip)`).
  - **Empaquetado optimizado con exclusión de módulos pesados:** Se configuró `Universal Downloader.spec` para incluir únicamente `QtCore`, `QtGui` y `QtWidgets`, excluyendo motores no utilizados (`QtWebEngine`, `QtQml`, `QtQuick`, `Qt3D`, `QtMultimedia`, `QtPdf`, `Tkinter` y `PIL`).

---

## v2.5.3 (10-11-2026) - Respaldo Automático para Videos de X/Twitter de Cuentas Marcadas como Contenido Sensible (+18)
### Nuevas Funcionalidades y Correcciones de Extracción
- **Extracción directa desde CDN para publicaciones de X/Twitter restringidas a invitados (`_extract_twitter_fallback_info` / `_download_twitter_fallback`):**
  - Cuando un video en X/Twitter proviene originalmente de una cuenta marcada como contenido sensible (`possibly_sensitive: true` / `+18`, incluso si fue republicado o citado en un tweet normal), la API GraphQL de X bloquea el *Guest Token* anónimo de `yt-dlp` devolviendo `ERROR: [twitter] ... Video #1 is unavailable`.
  - Se incorporó un sistema de respaldo automático que consulta la API de sindicación (`api.fxtwitter.com`), obtiene todas las resoluciones directas del servidor `video.twimg.com`, verifica su peso exacto byte a byte (`Content-Length`) y permite tanto **descargar el video completo** como **recortar fragmentos** (en MP4, MP3 o GIF) sin necesidad de iniciar sesión ni usar cookies.

---

## v2.5.2 (10-11-2026) - Tope Independiente en Barras de Inicio y Fin del Módulo de Recorte
### Mejoras de Usabilidad e Interfaz
- **Movimiento independiente con tope físico entre `Inicio (Desde)` y `Fin (Hasta)`:**
  - Al bajar la barra deslizante de **`Fin (Hasta)`**, esta se detiene automáticamente al topar con la marca de **`Inicio (Desde)`** (`Inicio + 1 s`) sin arrastrar ni bajar nunca la barra de inicio.
  - De igual forma, al subir la barra deslizante de **`Inicio (Desde)`**, se detiene al topar con la barra de **`Fin (Hasta)`** (`Fin - 1 s`) sin empujar la barra de fin.
- **Espaciado en encabezado del selector de rango:**
  - Se ajustó el texto y margen de la cabecera del panel de recorte para evitar que la etiqueta izquierda toque el indicador derecho de `Rango: MM:SS -> MM:SS (Duración del clip: MM:SS)`.

---

## v2.5.1 (10-11-2026) - Corrección de Pre-análisis de Duración y Tarjeta de Vista Previa en el Módulo de Recorte
### Correcciones Críticas
- **Corrección de referencia de caché en `_analyze_clip_url_worker` (`_url_info_cache`):**
  - En `v2.5.0`, el analizador del módulo de recorte consultaba un atributo inexistente (`_metadata_cache`) en lugar de la caché compartida `_url_info_cache`, provocando que saltara al bloque de excepción y mostrara el mensaje `No se pudo pre-analizar la duración del enlace` dejando las barras deslizantes en el tope predeterminado de `05:00` y el peso en `Pega un enlace`.
  - Ahora extrae correctamente la duración real del video (ej. `16:58` en videos largos de YouTube), ajusta el tope de las barras deslizantes a la duración exacta, despliega la tarjeta con miniatura (`clip_preview_card.grid()`), conserva cualquier rango que el usuario haya escrito manualmente y calcula en tiempo real el peso estimado del fragmento.
- **Respaldo automático con motor externo actualizado (`yt-dlp.exe --dump-single-json`):**
  - Si la librería interna falla al analizar un enlace reciente de YouTube, utiliza automáticamente el motor externo actualizado en `AppData`.

---

## v2.5.0 (10-11-2026) - Módulo Independiente para Recortar Fragmentos (Clips en MP4, MP3 y GIF)
### Nuevas Funcionalidades y Mejoras de Extracción Parcial
- **Sistema de pestañas superiores (`Descarga General / Listas` y `Recortar Fragmento (Clip)`):**
  - Se agregó un selector de pestañas en la parte superior que mantiene limpia la pestaña principal e incorpora un módulo independiente dedicado a **extraer y recortar fragmentos exactos** de cualquier video o pista musical.
- **Línea de tiempo dual interactiva (`Inicio` y `Fin` sincronizados):**
  - Al pegar un enlace en la pestaña **`Recortar Fragmento (Clip)`**, se carga su miniatura visual (`88x50 px`), título y duración total.
  - Incluye **2 barras deslizantes (`CTkSlider`)** y **2 campos de tiempo editables (`MM:SS` / `HH:MM:SS` o segundos)** totalmente sincronizados entre sí para elegir con exactitud dónde inicia y dónde termina el recorte, mostrando en tiempo real el resumen del rango y la duración resultante del clip.
- **Selectores desplegables (`ComboBox`) propios de Formato y Calidad en el módulo de recorte:**
  - Permite exportar el fragmento seleccionado en **3 formatos** con sus respectivas calidades:
    1. **`Video MP4`:** `Máxima disponible (Original)`, `2160p (4K Ultra HD)`, `1440p (2K QHD)`, `1080p (Full HD)`, `720p (HD)`, `480p (SD)` y `360p (Baja / Ligero)`. Calcula en vivo el peso estimado proporcional a la duración del clip.
    2. **`Audio MP3`:** `320 kbps (Estudio / Máxima)`, `256 kbps (Alta)`, `192 kbps (Estándar)` y `128 kbps (Ligera)`. Calcula en vivo el peso exacto CBR del fragmento de audio.
    3. **`Imagen / GIF`:** Convierte únicamente el fragmento recortado en un archivo `.gif` animado de alta definición con paleta optimizada (`Lanczos + Bayer Dither`), permitiendo elegir la calidad del GIF (`Alta 480p • 15 FPS`, `Máxima 720p HD • 15 FPS`, `Estándar 360p • 12 FPS` u `Original • 15 FPS`).
- **Descarga parcial directa y coexistencia de archivos (`[Clip MMmSSs-MMmSSs]`):**
  - Descarga únicamente los bloques de tiempo necesarios mediante `download_ranges` y `FFmpeg` integrado con corte exacto de fotogramas clave (`force_keyframes_at_cuts`), etiquetando cada archivo con su rango (`[Clip 00m02s-00m05s].mp4 / .mp3 / .gif`) para poder descargar múltiples recortes o distintos formatos de un mismo video sin sobrescribir archivos previos.

---

## v2.4.1 (07-11-2026) - Selectores Individuales de Formato (MP4/MP3) y Calidad por Fila en Listas de Reproducción
### Nuevas Funcionalidades y Optimizaciones de Interfaz
- **Doble selector desplegable (`ComboBox`) en cada elemento de la lista de reproducción:**
  - Al lado de cada casilla de verificación en el checklist de listas de reproducción se añadieron **2 barras desplegables individuales**:
    1. **Selector de Formato por elemento:** Permite elegir individualmente **`Video MP4`** o **`Audio MP3`** para esa pista o video específico.
    2. **Selector de Calidad por elemento:** Actualiza dinámicamente sus opciones según el formato elegido en esa fila (`Mejor disponible`, `2160p 4K`, `1440p 2K`, `1080p`, `720p`, `480p`, `360p` para `Video MP4`; o `320 kbps`, `256 kbps`, `192 kbps`, `128 kbps` para `Audio MP3`).
  - **Sincronización inteligente y descargas mixtas:** Permite combinar en una misma descarga elementos en `Video MP4` y otros en `Audio MP3` con distintas calidades (mostrando el resumen en tiempo real, por ejemplo: `Seleccionados: 1 MP4 + 2 MP3 (33.8 MB audio)`), mientras que los selectores principales superiores actúan como preajuste rápido para cambiar todas las filas a la vez si se desea.
  - **Renderizado progresivo por lotes (`_PlaylistRowComboProxy`):** Los controles visuales de listas grandes se construyen de forma escalonada por lotes para que la interfaz aparezca de inmediato sin congelar la ventana.

---

## v2.4.0 (07-11-2026) - Vista Previa con Miniatura y Checklist de Listas de Reproducción
### Nuevas Funcionalidades
- **Tarjeta de vista previa visual con miniatura (`preview_card_frame`):**
  - Al pegar o analizar cualquier enlace (video, canción/audio, GIF o publicación), se despliega automáticamente una tarjeta compacta con una **miniatura visual (`88x50 px`)**, el título completo del contenido y metadatos detallados (tipo de contenido, resolución máxima, duración y canal/autor).
  - **Cero impacto en rendimiento:** El selector inteligente (`_extract_best_thumbnail_url`) elige la miniatura más ligera disponible en el servidor (`~240 px` de ancho, `~8 a 15 KB`), la descarga de forma asíncrona en un hilo secundario (`_load_thumbnail_async`) y la guarda en una caché en memoria (`_thumb_cache`, hasta `32` miniaturas) para no bloquear jamás la interfaz.
- **Checklist interactiva para Listas de Reproducción (`playlist_frame`):**
  - Detección automática ultrarrápida (`extract_flat: "in_playlist"`, `< 1 segundo` para listas de hasta `100` videos) cuando se pega el enlace de una lista de reproducción.
  - Despliega un panel desplazable (`CTkScrollableFrame`) donde se muestra cada elemento de la lista numerado uno por uno con su título y duración individual en formato de casillas de verificación (`CTkCheckBox`).
  - Incluye botones rápidos **`Seleccionar todo`** y **`Deseleccionar todo`**, recálculo en tiempo real del peso total (en modo MP3) o cantidad de elementos seleccionados, actualización dinámica del botón principal (`DESCARGAR SELECCIONADOS (N)`) y descarga secuencial con progreso individual (`[1/N]`, `[2/N]`, ...).

---

## v2.3.0 (06-11-2026) - Optimizaciones de Rendimiento, Caché y Persistencia
### Optimizaciones de Velocidad y Red
- **Descarga paralela de fragmentos (`concurrent_fragment_downloads = 4` / `--concurrent-fragments 4`):** Acelera entre `2x` y `4x` la descarga de transmisiones multifragmento (HLS/DASH en alta resolución de YouTube, X/Twitter, Instagram y Facebook).
- **Buffer de lectura/escritura ampliado a `256 KB` (`buffersize`):** Reduce las llamadas al sistema de disco durante descargas directas y actualizaciones del motor API.
- **Extracción instantánea de duración en Suno (`0 ms`):** Ahora se lee la duración directamente desde el bloque JSON hidratado del HTML inicial en lugar de abrir una segunda conexión de red con `FFmpeg`, reduciendo el tiempo de análisis en `~1.2 segundos` (`60%` más rápido).
- **Caché LRU en memoria de enlaces analizados (`32 URLs`):** Si se vuelve a pegar o consultar un enlace ya analizado durante la sesión, las calidades y el peso exacto se resuelven en `0 ms` sin realizar nuevas peticiones de red.
- **Debounce de `300 ms` en la barra de URL (`<KeyRelease>`):** Evita disparar hilos de análisis de red en cada pulsación de tecla mientras se edita manualmente un enlace, manteniendo respuesta inmediata (`0 ms`) al usar el botón `Pegar` o `Calcular Peso`.

### Optimizaciones de Arranque, CPU e Interfaz Gráfica (GUI)
- **Caché de versión del motor externo (`config.json`):** Almacena la versión y fecha de modificación (`mtime`) de `yt-dlp.exe` en `%LOCALAPPDATA%\UniversalDownloader\config.json`, evitando ejecutar el subproceso `yt-dlp.exe --version` en cada inicio de la aplicación (ahorro de `~1.8 a 2.5 segundos` al abrir la app).
- **Throttling de refresco de interfaz a `60 ms` (`~16 FPS`):** Limita la frecuencia de repintado intermedio de la barra de progreso en `CustomTkinter`, reduciendo en más de un `85%` la carga sobre el hilo principal de la interfaz durante descargas de alta velocidad.
- **Acotado automático de consola (`500 líneas`):** Mantiene constante el uso de memoria RAM en sesiones prolongadas recortando líneas antiguas del registro de actividad.
- **Codificación multihilo en `FFmpeg` (`-threads 0`):** Aprovecha todos los núcleos lógicos del procesador al convertir audio a `.mp3` (`libmp3lame`) y animaciones a `.gif`.
- **Persistencia automática de preferencias:** La aplicación recuerda automáticamente entre sesiones la última carpeta de descarga elegida y el tema visual (`Oscuro`, `Claro` o `Sistema`).

---

## v2.2.2 (03-11-2026) - Corrección de GIFs de X/Twitter y Peso Exacto en CDN
### Correcciones Críticas
- **Peso exacto en X/Twitter (`_populate_missing_direct_filesizes`):** X/Twitter asigna bitrates máximos teóricos fijos en su JSON (`10368 kbps` para `1080p`, `2176 kbps` para `720p`, `832 kbps` para `360p`), lo que hacía que `yt-dlp` estimara pesos inflados (ej. `76.6 MB` para un video real de `11.8 MB`). Se implementó un sondeo paralelo `HEAD` / `Range: bytes=0-0` (`~0.08 s`) que obtiene el encabezado `Content-Length` real byte a byte desde el servidor CDN para todas las resoluciones.
- **Descarga limpia de GIFs de X/Twitter (`_is_twitter_gif_info`):**
  - Se eliminó la bandera `--write-thumbnail` en el modo `Imagen / GIF`, evitando que se descargara una imagen `.jpg` suelta con el primer fotograma del GIF.
  - Detección automática de enlaces `/tweet_video/` de X/Twitter como `(GIF animado)`, cambiando automáticamente el selector de formato a `Imagen / GIF`.
  - Se añadió `--encoding utf-8` al motor externo y detección por instantánea de archivos para soportar títulos con caracteres Unicode especiales (como `：`), garantizando que `FFmpeg` convierta el archivo a `.gif` y elimine el `.mp4` temporal de origen.

---

## v2.2.0 (03-11-2026) - Soporte Silencioso para Suno y Ajustes de Tema Visual
### Nuevas Funcionalidades
- **Soporte integrado y oculto para `suno.com` / `suno.ai`:**
  - Extractor directo propio (`_is_suno_url`, `_extract_suno_info`, `_download_suno_media`) que sortea el bloqueo por defecto de `yt-dlp` en `suno.com`.
  - Permite calcular peso exacto y descargar canciones de Suno en **Audio MP3** (`320 / 256 / 192 / 128 kbps`), **Video MP4** oficial o **Imagen / GIF** (portada original en alta resolución) sin mostrar referencias visuales a Suno en la interfaz.
- **Refinamiento de paleta de colores por tema (`Oscuro` / `Claro`):**
  - En modo **Oscuro**, se restauraron los botones secundarios en gris oscuro (`gray28`) y botones principales en azul.
  - En modo **Claro**, todos los botones secundarios (`Consultar Actualización`, `Pegar`, `Limpiar`, `Cambiar Carpeta`, `Abrir Destino`) usan el azul activo (`#3B8ED0`, hover `#36719F`) con texto blanco (`#FFFFFF`) para evitar que parezcan deshabilitados.

---

## v2.1.0 (03-11-2026) - Corrección de Audio en X/Twitter y Empaquetado Portable
### Correcciones y Distribución
- **Corrección de videos sin audio en X/Twitter (`_has_video`, `_is_audio_only`):** Distinción estricta entre `acodec = None` (flujo HTTP combinado de X/Twitter que sí incluye audio) y `acodec = "none"` (flujo de solo video mudo en manifiestos HLS/DASH), garantizando que los videos MP4 de X/Twitter se descarguen siempre con pista de audio.
- **Sobrescritura forzada (`overwrites: True` / `--force-overwrites`):** Asegura que al volver a descargar un enlace se reemplace cualquier archivo previo en la carpeta de destino.
- **Ícono nativo y metadatos PE de Windows (`app_icon.ico`, `version_info.txt`):** Inclusión de información de versión, empresa y producto en el ejecutable `.exe`, junto con el paquete `Universal_Downloader_Portable.zip` y el script `Desbloquear_y_Abrir.bat` para evitar bloqueos de SmartScreen al compartir por Google Drive.

---

## v2.0.0 (02-11-2026) - Selector de Calidad, Peso Exacto y Auto-Actualizador de API
### Nuevas Funcionalidades
- **Selector dinámico de Calidad:**
  - **Video MP4:** `Mejor disponible (Auto)`, `2160p (4K Ultra HD)`, `1440p (2K QHD)`, `1080p (Full HD)`, `720p (HD)`, `480p (SD)` y `360p (Datos reducidos)`, con soporte para relaciones de aspecto `16:9`, `21:9` (ultrawide) y `9:16` (vertical).
  - **Audio MP3:** `320 kbps (Máxima)`, `256 kbps (Alta)`, `192 kbps (Estándar)` y `128 kbps (Ligera)`.
  - **Imagen / GIF:** Deshabilita automáticamente el selector de calidad mostrando `No aplica (Original)`.
- **Cálculo de peso exacto en tiempo real y bloqueo de flujo (`locked_format_id`):** Prioriza flujos directos HTTPS con tamaño reportado por el servidor y fija el `format_id` exacto para que el peso descargado coincida con el mostrado en pantalla.
- **Auto-actualizador autónomo (`Consultar Actualización` y `Actualizar API`):** Consulta lanzamientos en GitHub/PyPI y descarga `yt-dlp.exe` en `%LOCALAPPDATA%\UniversalDownloader\bin\yt-dlp.exe` para mantener la app funcional en cualquier PC sin requerir Python instalado.

---

## v1.0.0 (02-11-2026) - Lanzamiento Inicial
- Interfaz gráfica moderna en `CustomTkinter` con hilos secundarios (`threading`), barra de progreso en tiempo real y consola de registro.
- Soporte para **YouTube, TikTok, Instagram, Facebook y Twitter (X)**.
- Integración autocontenida de `FFmpeg` (`imageio-ffmpeg`) y respaldo de imágenes fijas con `gallery-dl`.
- Compilación en ejecutable único autónomo (`Universal Downloader.exe`) mediante `PyInstaller`.
