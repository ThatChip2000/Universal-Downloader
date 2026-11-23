import io
import os
import re
import sys
import time
import json
import shutil
import threading
import subprocess
import urllib.request
import concurrent.futures
from pathlib import Path
import qt_backend as ctk
import yt_dlp

APP_VERSION = "3.0.3"
YTDLP_JS_RUNTIMES = {"deno": {}, "node": {}, "bun": {}, "quickjs": {}}
YTDLP_REMOTE_COMPONENTS = ["ejs:github"]
YTDLP_CLI_JS_ARGS = [
    "--js-runtimes", "deno",
    "--js-runtimes", "node",
    "--js-runtimes", "bun",
    "--js-runtimes", "quickjs",
    "--remote-components", "ejs:github",
]

# Parche de seguridad para corregir el bug interno de yt-dlp donde exc_info es None
# y al evaluar 'hasattr(e, "exc_info") and e.exc_info[0]' arroja TypeError: 'NoneType' object is not subscriptable.
_orig_ytdlp_trouble = yt_dlp.YoutubeDL.trouble

def _safe_ytdlp_trouble(self, message=None, tb=None, is_error=True):
    cur_exc = sys.exc_info()
    if cur_exc[0] and hasattr(cur_exc[1], "exc_info"):
        val = getattr(cur_exc[1], "exc_info", None)
        if not val or not isinstance(val, (tuple, list)) or len(val) == 0 or val[0] is None:
            try:
                delattr(cur_exc[1], "exc_info")
            except Exception:
                pass
    return _orig_ytdlp_trouble(self, message=message, tb=tb, is_error=is_error)

yt_dlp.YoutubeDL.trouble = _safe_ytdlp_trouble

# Intentar localizar FFmpeg empaquetado (imageio-ffmpeg) o en el PATH del sistema
try:
    import imageio_ffmpeg
    BUNDLED_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    BUNDLED_FFMPEG = None


def get_appdata_bin_dir() -> Path:
    """Carpeta persistente en AppData para almacenar el motor yt-dlp y ffmpeg actualizables en cualquier PC."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    bin_dir = Path(base) / "UniversalDownloader" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return bin_dir


def get_ffmpeg_path() -> str | None:
    """Devuelve la ruta de FFmpeg y asegura 'ffmpeg.exe' en el PATH para que el recorte por tramos de yt-dlp funcione siempre."""
    bin_dir = get_appdata_bin_dir()
    bin_dir_str = str(bin_dir)
    current_path = os.environ.get("PATH", "")
    if bin_dir_str not in current_path.split(os.pathsep):
        os.environ["PATH"] = bin_dir_str + os.pathsep + current_path

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg and os.path.isfile(system_ffmpeg):
        return system_ffmpeg

    if BUNDLED_FFMPEG and os.path.isfile(BUNDLED_FFMPEG):
        standard_ffmpeg = bin_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if not standard_ffmpeg.is_file():
            try:
                shutil.copy2(BUNDLED_FFMPEG, standard_ffmpeg)
            except Exception:
                return BUNDLED_FFMPEG
        return str(standard_ffmpeg)
    return None


def get_appdata_config_path() -> Path:
    """Ruta del archivo de configuración y caché de inicio en AppData."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    cfg_dir = Path(base) / "UniversalDownloader"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "config.json"


def normalize_version(ver_str: str) -> tuple[int, ...]:
    """Convierte cadenas de versión como '2026.10.21' en tuplas comparables."""
    parts = re.findall(r"\d+", ver_str or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def format_bytes(num_bytes: int | float | None, is_exact: bool = False) -> str:
    """Formatea una cantidad de bytes en KB, MB o GB legibles."""
    if not num_bytes or num_bytes <= 0:
        return "No disponible"
    prefix = "" if is_exact else "~ "
    if num_bytes < 1024 * 1024:
        return f"{prefix}{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{prefix}{num_bytes / (1024 * 1024):.1f} MB"
    return f"{prefix}{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: int | float | None) -> str:
    """Convierte segundos a formato MM:SS o HH:MM:SS."""
    if not seconds or seconds <= 0:
        return "--:--"
    total_sec = int(seconds)
    hrs, rem = divmod(total_sec, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_timestamp_input(seconds: float | int | None) -> str:
    """Formatea un valor en segundos (incluyendo 0) a MM:SS o HH:MM:SS para las cajas de recorte."""
    if seconds is None or seconds < 0:
        return "00:00"
    total_sec = int(round(float(seconds)))
    hrs, rem = divmod(total_sec, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def parse_timestamp_input(text: str) -> float | None:
    """Convierte una cadena SS, MM:SS o HH:MM:SS en segundos flotantes."""
    s = (text or "").strip().replace(",", ".")
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 1:
            val = float(parts[0])
        elif len(parts) == 2:
            val = int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            val = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            return None
        return val if val >= 0 else None
    except Exception:
        return None


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CLI_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%\s+of\s+\S+\s+at\s+(?P<speed>\S+)\s+ETA\s+(?P<eta>\S+)"
)


def clean_ansi(text: str) -> str:
    """Elimina secuencias de color ANSI de los mensajes de consola."""
    return ANSI_ESCAPE_RE.sub("", text)


class YtDlpLogger:
    """Logger personalizado para redirigir la salida de yt-dlp a la consola de la GUI."""

    def __init__(self, log_callback):
        self.log_callback = log_callback

    def debug(self, msg: str):
        msg_clean = clean_ansi(msg).strip()
        if not msg_clean:
            return
        if msg_clean.startswith("[download]") and "%" in msg_clean:
            return
        self.log_callback(f"[INFO] {msg_clean}")

    def info(self, msg: str):
        msg_clean = clean_ansi(msg).strip()
        if msg_clean:
            self.log_callback(f"[INFO] {msg_clean}")

    def warning(self, msg: str):
        msg_clean = clean_ansi(msg).strip()
        if msg_clean:
            self.log_callback(f"[AVISO] {msg_clean}")

    def error(self, msg: str):
        msg_clean = clean_ansi(msg).strip()
        if msg_clean:
            self.log_callback(f"[ERROR] {msg_clean}")


class _PlaylistRowComboProxy:
    """Proxy ligero para CTkComboBox que permite renderizado progresivo por lotes sin congelar la interfaz."""

    __slots__ = ("value", "values", "state", "widget")

    def __init__(self, initial_value: str, values: list[str]):
        self.value = initial_value
        self.values = list(values)
        self.state = "readonly"
        self.widget: ctk.CTkComboBox | None = None

    def get(self) -> str:
        return self.widget.get() if self.widget is not None else self.value

    def set(self, val: str):
        self.value = val
        if self.widget is not None:
            self.widget.set(val)

    def configure(self, **kwargs):
        if "values" in kwargs:
            self.values = list(kwargs["values"])
        if "state" in kwargs:
            self.state = kwargs["state"]
        if self.widget is not None:
            self.widget.configure(**kwargs)

    def cget(self, key: str):
        if self.widget is not None:
            return self.widget.cget(key)
        if key == "values":
            return self.values
        if key == "state":
            return self.state
        return None


class UniversalDownloaderApp(ctk.CTk):
    """Aplicación de escritorio nativa para descarga multimedia desde YouTube, TikTok, Instagram, Facebook y X."""

    FORMAT_VIDEO = "Video MP4"
    FORMAT_AUDIO = "Audio MP3"
    FORMAT_IMAGE_GIF = "Imagen / GIF"

    TAB_MAIN = "  Descarga General / Listas  "
    TAB_CLIP = "  Recortar Fragmento (Clip)  "

    # Cada calidad define (alto_estandar, ancho_estandar) para soportar 16:9, 21:9 (ultrawide) y 9:16 (vertical)
    VIDEO_QUALITIES: dict[str, tuple[int, int] | None] = {
        "Mejor disponible (Auto)": None,
        "2160p (4K Ultra HD)": (2160, 3840),
        "1440p (2K QHD)": (1440, 2560),
        "1080p (Full HD)": (1080, 1920),
        "720p (HD)": (720, 1280),
        "480p (SD)": (480, 854),
        "360p (Datos reducidos)": (360, 640),
    }

    AUDIO_QUALITIES = {
        "320 kbps (Máxima)": 320,
        "256 kbps (Alta)": 256,
        "192 kbps (Estándar)": 192,
        "128 kbps (Ligera)": 128,
    }

    # Calidades para recorte en GIF animado: (alto_maximo_px, fotogramas_por_segundo)
    GIF_QUALITIES: dict[str, tuple[int | None, int]] = {
        "Alta (480p • 15 FPS)": (480, 15),
        "Máxima (720p HD • 15 FPS)": (720, 15),
        "Estándar (360p • 12 FPS)": (360, 12),
        "Original (15 FPS)": (None, 15),
    }

    YTDLP_RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
    YTDLP_PYPI_API = "https://pypi.org/pypi/yt-dlp/json"
    YTDLP_EXE_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

    def __init__(self):
        super().__init__()

        # Configuración general de ventana y tema
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Universal Downloader - YouTube | TikTok | Instagram | Facebook | X")
        self.geometry("880x760")
        self.minsize(780, 640)
        self._apply_window_icon()

        # Estado interno y carga de configuración persistente
        self.config_path = get_appdata_config_path()
        self.user_config = self._load_user_config()
        saved_dir = self.user_config.get("download_dir")
        self.download_dir = (
            saved_dir if (saved_dir and os.path.isdir(saved_dir)) else str(Path.home() / "Downloads")
        )
        self.saved_theme = self.user_config.get("theme", "Oscuro")
        if self.saved_theme not in ("Oscuro", "Claro", "Sistema"):
            self.saved_theme = "Oscuro"

        self.is_busy = False
        self.ffmpeg_path = get_ffmpeg_path()
        self.external_ytdlp_path = get_appdata_bin_dir() / "yt-dlp.exe"
        self.current_engine_version = yt_dlp.version.__version__
        self.use_external_engine = False

        # Metadatos en caché (LRU en memoria) del enlace analizado y control de debounce/throttling
        self.analyzed_url: str | None = None
        self.analyzed_info: dict | None = None
        self.locked_format_id: str | None = None
        self._analyze_generation = 0
        self._url_debounce_after_id: str | None = None
        self._cache_lock = threading.Lock()
        self._url_info_cache: dict[str, dict] = {}
        self._thumb_cache: dict[str, ctk.CTkImage] = {}
        self._placeholder_thumb = self._create_placeholder_ctk_image()
        self.playlist_vars: list[tuple[ctk.BooleanVar, dict, _PlaylistRowComboProxy, _PlaylistRowComboProxy]] = []
        self.is_playlist_mode: bool = False
        self._last_progress_ui_time: float = 0.0

        # Estado del Módulo de Recorte de Fragmento (Pestaña 2)
        self.clip_analyzed_url: str | None = None
        self.clip_analyzed_info: dict | None = None
        self.clip_locked_format_id: str | None = None
        self.clip_total_duration: float = 0.0
        self.clip_start_sec: float = 0.0
        self.clip_end_sec: float = 15.0
        self._clip_analyze_generation: int = 0
        self._clip_url_debounce_id: str | None = None
        self._clip_syncing_ui: bool = False

        # Construcción de la interfaz y aplicación inicial del tema
        self._change_appearance_mode(self.saved_theme)
        self._build_ui()

        # Verificar motor local y consultar actualizaciones silenciosamente una vez iniciado el bucle principal
        self.after(
            150,
            lambda: threading.Thread(target=self._init_and_check_updates, args=(True,), daemon=True).start(),
        )

    def _load_user_config(self) -> dict:
        try:
            if self.config_path.is_file():
                return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_user_config(self):
        try:
            self.config_path.write_text(
                json.dumps(self.user_config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # CONSTRUCCIÓN DE LA INTERFAZ GRÁFICA (GUI)
    # -------------------------------------------------------------------------
    def _apply_window_icon(self):
        """Aplica el ícono personalizado a la ventana y a la barra de tareas de Windows."""
        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    f"UniversalMediaTools.UniversalDownloader.{APP_VERSION}"
                )
            base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_dir, "app_icon.ico")
            if os.path.isfile(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

    @staticmethod
    def _create_placeholder_ctk_image() -> ctk.CTkImage:
        """Crea en memoria una miniatura ligera por defecto (88x50) en C++ Qt sin lecturas de disco."""
        return ctk.create_placeholder_pixmap(88, 50)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # 1. Encabezado + Botones de Actualización de API y Tema
        header_frame = ctk.CTkFrame(self, corner_radius=12)
        header_frame.grid(row=0, column=0, padx=20, pady=(14, 6), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=18, pady=10, sticky="w")

        title_label = ctk.CTkLabel(
            title_box,
            text="Universal Downloader",
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        )
        title_label.grid(row=0, column=0, pady=(0, 2), sticky="w")

        subtitle_label = ctk.CTkLabel(
            title_box,
            text="YouTube • TikTok • Instagram • Facebook • Twitter (X)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
            anchor="w",
        )
        subtitle_label.grid(row=1, column=0, sticky="w")

        top_actions_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        top_actions_frame.grid(row=0, column=1, padx=14, pady=10, sticky="e")

        self.check_update_btn = ctk.CTkButton(
            top_actions_frame,
            text="Consultar Actualización",
            width=165,
            height=32,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_check_update_clicked,
        )
        self.check_update_btn.grid(row=0, column=0, padx=(0, 8), pady=4)

        self.update_api_btn = ctk.CTkButton(
            top_actions_frame,
            text="Actualizar API",
            width=125,
            height=32,
            fg_color=("#1f6aa5", "#1f6aa5"),
            hover_color=("#144870", "#144870"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_update_api_clicked,
        )
        self.update_api_btn.grid(row=0, column=1, padx=(0, 8), pady=4)

        self.theme_menu = ctk.CTkOptionMenu(
            top_actions_frame,
            values=["Oscuro", "Claro", "Sistema"],
            width=100,
            height=32,
            command=self._change_appearance_mode,
        )
        self.theme_menu.set(self.saved_theme)
        self.theme_menu.grid(row=0, column=2, pady=4)

        # 1.5 Selector de Pestaña (Módulo Principal vs Módulo de Recorte de Fragmento)
        self.tab_switcher = ctk.CTkSegmentedButton(
            self,
            values=[self.TAB_MAIN, self.TAB_CLIP],
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_tab_switched,
        )
        self.tab_switcher.set(self.TAB_MAIN)
        self.tab_switcher.grid(row=1, column=0, padx=20, pady=(2, 4), sticky="ew")

        # =========================================================================
        # PESTAÑA 1: DESCARGA GENERAL / LISTAS DE REPRODUCCIÓN
        # =========================================================================
        self.main_tab_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_tab_container.grid(row=2, column=0, padx=0, pady=0, sticky="ew")
        self.main_tab_container.grid_columnconfigure(0, weight=1)

        # 2. Panel de entrada de URL, Calidad y Peso Estimado en tiempo real
        controls_frame = ctk.CTkFrame(self.main_tab_container, corner_radius=12)
        controls_frame.grid(row=0, column=0, padx=20, pady=4, sticky="ew")
        controls_frame.grid_columnconfigure(0, weight=1)

        url_label = ctk.CTkLabel(
            controls_frame,
            text="Enlace del contenido (URL):",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        url_label.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        self.media_info_label = ctk.CTkLabel(
            controls_frame,
            text="Pega un enlace para calcular calidades y peso automáticamente",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        self.media_info_label.grid(row=0, column=0, columnspan=4, padx=16, pady=(12, 4), sticky="e")

        self.url_entry = ctk.CTkEntry(
            controls_frame,
            placeholder_text="Pega aquí el enlace de YouTube, TikTok, Instagram, Facebook o X (https://...)",
            height=38,
            font=ctk.CTkFont(size=13),
        )
        self.url_entry.grid(row=1, column=0, padx=(16, 8), pady=(0, 10), sticky="ew")
        self.url_entry.bind("<KeyRelease>", self._on_url_entry_changed)

        paste_btn = ctk.CTkButton(
            controls_frame,
            text="Pegar",
            width=70,
            height=38,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._paste_from_clipboard,
        )
        paste_btn.grid(row=1, column=1, padx=(0, 6), pady=(0, 10))

        self.analyze_btn = ctk.CTkButton(
            controls_frame,
            text="Calcular Peso",
            width=105,
            height=38,
            fg_color=("#2b5797", "#2b5797"),
            hover_color=("#1e3f6f", "#1e3f6f"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._trigger_url_analysis(force=True),
        )
        self.analyze_btn.grid(row=1, column=2, padx=(0, 6), pady=(0, 10))

        clear_btn = ctk.CTkButton(
            controls_frame,
            text="Limpiar",
            width=70,
            height=38,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._clear_url,
        )
        clear_btn.grid(row=1, column=3, padx=(0, 16), pady=(0, 10))

        # Tarjeta compacta de Vista Previa con Miniatura Visual (se muestra al analizar un enlace)
        self.preview_card_frame = ctk.CTkFrame(
            controls_frame,
            corner_radius=8,
            fg_color=("gray88", "gray18"),
        )
        self.preview_card_frame.grid(row=2, column=0, columnspan=4, padx=16, pady=(0, 8), sticky="ew")
        self.preview_card_frame.grid_columnconfigure(1, weight=1)
        self.preview_card_frame.grid_remove()

        self.preview_thumb_label = ctk.CTkLabel(
            self.preview_card_frame,
            text="",
            image=self._placeholder_thumb,
            width=88,
            height=50,
        )
        self.preview_thumb_label.grid(row=0, column=0, rowspan=2, padx=(10, 12), pady=7, sticky="w")

        self.preview_title_label = ctk.CTkLabel(
            self.preview_card_frame,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.preview_title_label.grid(row=0, column=1, padx=(0, 12), pady=(7, 0), sticky="ew")

        self.preview_meta_label = ctk.CTkLabel(
            self.preview_card_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=("gray35", "gray70"),
            anchor="w",
        )
        self.preview_meta_label.grid(row=1, column=1, padx=(0, 12), pady=(0, 7), sticky="ew")

        # Subpanel: Formato + Calidad + Etiqueta de Peso en Tiempo Real
        options_subframe = ctk.CTkFrame(controls_frame, fg_color="transparent")
        options_subframe.grid(row=3, column=0, columnspan=4, padx=16, pady=(2, 10), sticky="ew")
        options_subframe.grid_columnconfigure(4, weight=1)

        format_label = ctk.CTkLabel(
            options_subframe,
            text="Formato:",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        format_label.grid(row=0, column=0, padx=(0, 6), pady=4, sticky="w")

        self.format_combobox = ctk.CTkComboBox(
            options_subframe,
            values=[self.FORMAT_VIDEO, self.FORMAT_AUDIO, self.FORMAT_IMAGE_GIF],
            width=140,
            height=34,
            state="readonly",
            font=ctk.CTkFont(size=13),
            command=self._on_format_changed,
        )
        self.format_combobox.set(self.FORMAT_VIDEO)
        self.format_combobox.grid(row=0, column=1, padx=(0, 14), pady=4, sticky="w")

        quality_label = ctk.CTkLabel(
            options_subframe,
            text="Calidad:",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        quality_label.grid(row=0, column=2, padx=(0, 6), pady=4, sticky="w")

        self.quality_combobox = ctk.CTkComboBox(
            options_subframe,
            values=list(self.VIDEO_QUALITIES.keys()),
            width=190,
            height=34,
            state="readonly",
            font=ctk.CTkFont(size=13),
            command=self._on_quality_changed,
        )
        self.quality_combobox.set("Mejor disponible (Auto)")
        self.quality_combobox.grid(row=0, column=3, padx=(0, 14), pady=4, sticky="w")

        # Etiqueta destacada de Peso Estimado en tiempo real
        size_badge_frame = ctk.CTkFrame(options_subframe, corner_radius=8, fg_color=("gray85", "gray20"))
        size_badge_frame.grid(row=0, column=4, padx=(0, 0), pady=2, sticky="ew")
        size_badge_frame.grid_columnconfigure(0, weight=1)

        self.size_estimate_label = ctk.CTkLabel(
            size_badge_frame,
            text="Peso estimado: Pega un enlace",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1f6aa5", "#5dade2"),
            anchor="w",
        )
        self.size_estimate_label.grid(row=0, column=0, padx=14, pady=5, sticky="ew")

        # Fila inferior: Carpeta de destino y botones de carpeta
        folder_subframe = ctk.CTkFrame(controls_frame, fg_color="transparent")
        folder_subframe.grid(row=4, column=0, columnspan=4, padx=16, pady=(0, 12), sticky="ew")
        folder_subframe.grid_columnconfigure(0, weight=1)

        self.path_label = ctk.CTkLabel(
            folder_subframe,
            text=f"Guardar en: {self.download_dir}",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        self.path_label.grid(row=0, column=0, padx=(0, 10), pady=2, sticky="w")

        self.folder_btn = ctk.CTkButton(
            folder_subframe,
            text="Cambiar Carpeta",
            width=130,
            height=30,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._select_download_folder,
        )
        self.folder_btn.grid(row=0, column=1, padx=(0, 8), pady=2, sticky="e")

        open_folder_btn = ctk.CTkButton(
            folder_subframe,
            text="Abrir Destino",
            width=115,
            height=30,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._open_download_folder,
        )
        open_folder_btn.grid(row=0, column=2, pady=2, sticky="e")

        # 2.5 Panel desplegable de Checklist para Listas de Reproducción (oculto si es enlace individual)
        self.playlist_frame = ctk.CTkFrame(self.main_tab_container, corner_radius=12)
        self.playlist_frame.grid(row=1, column=0, padx=20, pady=(2, 4), sticky="ew")
        self.playlist_frame.grid_columnconfigure(0, weight=1)
        self.playlist_frame.grid_remove()

        pl_header_bar = ctk.CTkFrame(self.playlist_frame, fg_color="transparent")
        pl_header_bar.grid(row=0, column=0, padx=14, pady=(8, 4), sticky="ew")
        pl_header_bar.grid_columnconfigure(0, weight=1)

        self.playlist_header_label = ctk.CTkLabel(
            pl_header_bar,
            text="Lista de reproducción detectada:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.playlist_header_label.grid(row=0, column=0, sticky="w")

        self.select_all_btn = ctk.CTkButton(
            pl_header_bar,
            text="Seleccionar todo",
            width=120,
            height=26,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._set_all_playlist_checks(True),
        )
        self.select_all_btn.grid(row=0, column=1, padx=(6, 6))

        self.deselect_all_btn = ctk.CTkButton(
            pl_header_bar,
            text="Deseleccionar todo",
            width=130,
            height=26,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self._set_all_playlist_checks(False),
        )
        self.deselect_all_btn.grid(row=0, column=2)

        self.playlist_scroll = ctk.CTkScrollableFrame(
            self.playlist_frame,
            height=155,
            corner_radius=8,
            fg_color=("gray90", "gray15"),
        )
        self.playlist_scroll.grid(row=1, column=0, padx=14, pady=(2, 10), sticky="ew")
        self.playlist_scroll.grid_columnconfigure(0, weight=1)

        # 3. Botón principal de descarga (Pestaña 1)
        self.download_btn = ctk.CTkButton(
            self.main_tab_container,
            text="INICIAR DESCARGA",
            height=44,
            corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_download_thread,
        )
        self.download_btn.grid(row=2, column=0, padx=20, pady=4, sticky="ew")

        # =========================================================================
        # PESTAÑA 2: MÓDULO DE RECORTE DE FRAGMENTO (CLIP EN MP4, MP3 O GIF)
        # =========================================================================
        self.clip_tab_container = ctk.CTkFrame(self, fg_color="transparent")
        self.clip_tab_container.grid(row=2, column=0, padx=0, pady=0, sticky="ew")
        self.clip_tab_container.grid_columnconfigure(0, weight=1)
        self.clip_tab_container.grid_remove()

        clip_card = ctk.CTkFrame(self.clip_tab_container, corner_radius=12)
        clip_card.grid(row=0, column=0, padx=20, pady=4, sticky="ew")
        clip_card.grid_columnconfigure(0, weight=1)

        clip_url_lbl = ctk.CTkLabel(
            clip_card,
            text="Enlace del video a recortar (URL):",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        clip_url_lbl.grid(row=0, column=0, padx=16, pady=(10, 4), sticky="w")

        self.clip_media_info_label = ctk.CTkLabel(
            clip_card,
            text="Pega un enlace para cargar la línea de tiempo y elegir el fragmento",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        self.clip_media_info_label.grid(row=0, column=0, columnspan=4, padx=16, pady=(10, 4), sticky="e")

        self.clip_url_entry = ctk.CTkEntry(
            clip_card,
            placeholder_text="Pega aquí el enlace del video o canción que quieres recortar (https://...)",
            height=36,
            font=ctk.CTkFont(size=13),
        )
        self.clip_url_entry.grid(row=1, column=0, padx=(16, 8), pady=(0, 8), sticky="ew")
        self.clip_url_entry.bind("<KeyRelease>", self._on_clip_url_entry_changed)

        clip_paste_btn = ctk.CTkButton(
            clip_card,
            text="Pegar",
            width=70,
            height=36,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._paste_to_clip_url,
        )
        clip_paste_btn.grid(row=1, column=1, padx=(0, 6), pady=(0, 8))

        self.clip_analyze_btn = ctk.CTkButton(
            clip_card,
            text="Cargar Video",
            width=105,
            height=36,
            fg_color=("#2b5797", "#2b5797"),
            hover_color=("#1e3f6f", "#1e3f6f"),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._trigger_clip_url_analysis(force=True),
        )
        self.clip_analyze_btn.grid(row=1, column=2, padx=(0, 6), pady=(0, 8))

        clip_clear_btn = ctk.CTkButton(
            clip_card,
            text="Limpiar",
            width=70,
            height=36,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._clear_clip_url,
        )
        clip_clear_btn.grid(row=1, column=3, padx=(0, 16), pady=(0, 8))

        # Vista previa con miniatura en la pestaña de recorte
        self.clip_preview_card = ctk.CTkFrame(
            clip_card,
            corner_radius=8,
            fg_color=("gray88", "gray18"),
        )
        self.clip_preview_card.grid(row=2, column=0, columnspan=4, padx=16, pady=(0, 8), sticky="ew")
        self.clip_preview_card.grid_columnconfigure(1, weight=1)
        self.clip_preview_card.grid_remove()

        self.clip_thumb_label = ctk.CTkLabel(
            self.clip_preview_card,
            text="",
            image=self._placeholder_thumb,
            width=88,
            height=50,
        )
        self.clip_thumb_label.grid(row=0, column=0, rowspan=2, padx=(10, 12), pady=6, sticky="w")

        self.clip_title_label = ctk.CTkLabel(
            self.clip_preview_card,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.clip_title_label.grid(row=0, column=1, padx=(0, 12), pady=(6, 0), sticky="ew")

        self.clip_meta_label = ctk.CTkLabel(
            self.clip_preview_card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=("gray35", "gray70"),
            anchor="w",
        )
        self.clip_meta_label.grid(row=1, column=1, padx=(0, 12), pady=(0, 6), sticky="ew")

        # Panel de Línea de Tiempo y Selección de Fragmento (Inicio y Fin)
        range_box = ctk.CTkFrame(clip_card, corner_radius=8, fg_color=("gray90", "gray16"))
        range_box.grid(row=3, column=0, columnspan=4, padx=16, pady=(0, 8), sticky="ew")
        range_box.grid_columnconfigure(2, weight=1)

        range_header = ctk.CTkFrame(range_box, fg_color="transparent")
        range_header.grid(row=0, column=0, columnspan=3, padx=12, pady=(6, 2), sticky="ew")
        range_header.grid_columnconfigure(0, weight=1)

        range_title_lbl = ctk.CTkLabel(
            range_header,
            text="Fragmento a recortar (escribe MM:SS o desliza las barras):",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        range_title_lbl.grid(row=0, column=0, padx=(0, 12), sticky="w")

        self.clip_range_summary_label = ctk.CTkLabel(
            range_header,
            text="Rango: 00:00 -> 00:15  (Duración del clip: 00:15)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#1f6aa5", "#5dade2"),
            anchor="e",
        )
        self.clip_range_summary_label.grid(row=0, column=1, sticky="e")

        # Fila 1: Tiempo de Inicio (Desde)
        start_lbl = ctk.CTkLabel(
            range_box,
            text="Inicio (Desde):",
            width=95,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        start_lbl.grid(row=1, column=0, padx=(12, 6), pady=3, sticky="w")

        self.clip_start_entry = ctk.CTkEntry(
            range_box,
            width=78,
            height=28,
            justify="center",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
        )
        self.clip_start_entry.insert(0, "00:00")
        self.clip_start_entry.grid(row=1, column=1, padx=(0, 10), pady=3)
        self.clip_start_entry.bind("<KeyRelease>", self._on_clip_time_entry_edited)
        self.clip_start_entry.bind("<FocusOut>", self._on_clip_time_entry_focus_out)

        self.clip_start_slider = ctk.CTkSlider(
            range_box,
            from_=0.0,
            to=60.0,
            height=16,
            command=self._on_clip_start_slider_moved,
        )
        self.clip_start_slider.set(0.0)
        self.clip_start_slider.grid(row=1, column=2, padx=(0, 12), pady=3, sticky="ew")

        # Fila 2: Tiempo de Fin (Hasta)
        end_lbl = ctk.CTkLabel(
            range_box,
            text="Fin (Hasta):",
            width=95,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        end_lbl.grid(row=2, column=0, padx=(12, 6), pady=(3, 7), sticky="w")

        self.clip_end_entry = ctk.CTkEntry(
            range_box,
            width=78,
            height=28,
            justify="center",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
        )
        self.clip_end_entry.insert(0, "00:15")
        self.clip_end_entry.grid(row=2, column=1, padx=(0, 10), pady=(3, 7))
        self.clip_end_entry.bind("<KeyRelease>", self._on_clip_time_entry_edited)
        self.clip_end_entry.bind("<FocusOut>", self._on_clip_time_entry_focus_out)

        self.clip_end_slider = ctk.CTkSlider(
            range_box,
            from_=0.0,
            to=60.0,
            height=16,
            command=self._on_clip_end_slider_moved,
        )
        self.clip_end_slider.set(15.0)
        self.clip_end_slider.grid(row=2, column=2, padx=(0, 12), pady=(3, 7), sticky="ew")

        # Subpanel Pestaña 2: Las 2 Barras Desplegables (Formato MP4/MP3/GIF + Calidad respectiva) + Peso del Recorte
        clip_opts_subframe = ctk.CTkFrame(clip_card, fg_color="transparent")
        clip_opts_subframe.grid(row=4, column=0, columnspan=4, padx=16, pady=(0, 8), sticky="ew")
        clip_opts_subframe.grid_columnconfigure(4, weight=1)

        clip_fmt_lbl = ctk.CTkLabel(
            clip_opts_subframe,
            text="Formato:",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        clip_fmt_lbl.grid(row=0, column=0, padx=(0, 6), pady=3, sticky="w")

        self.clip_format_combobox = ctk.CTkComboBox(
            clip_opts_subframe,
            values=[self.FORMAT_VIDEO, self.FORMAT_AUDIO, self.FORMAT_IMAGE_GIF],
            width=140,
            height=34,
            state="readonly",
            font=ctk.CTkFont(size=13),
            command=self._on_clip_format_changed,
        )
        self.clip_format_combobox.set(self.FORMAT_VIDEO)
        self.clip_format_combobox.grid(row=0, column=1, padx=(0, 14), pady=3, sticky="w")

        clip_qual_lbl = ctk.CTkLabel(
            clip_opts_subframe,
            text="Calidad:",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        clip_qual_lbl.grid(row=0, column=2, padx=(0, 6), pady=3, sticky="w")

        self.clip_quality_combobox = ctk.CTkComboBox(
            clip_opts_subframe,
            values=list(self.VIDEO_QUALITIES.keys()),
            width=190,
            height=34,
            state="readonly",
            font=ctk.CTkFont(size=13),
            command=self._on_clip_quality_changed,
        )
        self.clip_quality_combobox.set("Mejor disponible (Auto)")
        self.clip_quality_combobox.grid(row=0, column=3, padx=(0, 14), pady=3, sticky="w")

        clip_size_badge = ctk.CTkFrame(clip_opts_subframe, corner_radius=8, fg_color=("gray85", "gray20"))
        clip_size_badge.grid(row=0, column=4, padx=(0, 0), pady=2, sticky="ew")
        clip_size_badge.grid_columnconfigure(0, weight=1)

        self.clip_size_estimate_label = ctk.CTkLabel(
            clip_size_badge,
            text="Peso del fragmento: Pega un enlace",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1f6aa5", "#5dade2"),
            anchor="w",
        )
        self.clip_size_estimate_label.grid(row=0, column=0, padx=14, pady=5, sticky="ew")

        # Fila inferior Pestaña 2: Carpeta de destino
        clip_folder_subframe = ctk.CTkFrame(clip_card, fg_color="transparent")
        clip_folder_subframe.grid(row=5, column=0, columnspan=4, padx=16, pady=(0, 10), sticky="ew")
        clip_folder_subframe.grid_columnconfigure(0, weight=1)

        self.clip_path_label = ctk.CTkLabel(
            clip_folder_subframe,
            text=f"Guardar en: {self.download_dir}",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        self.clip_path_label.grid(row=0, column=0, padx=(0, 10), pady=2, sticky="w")

        self.clip_folder_btn = ctk.CTkButton(
            clip_folder_subframe,
            text="Cambiar Carpeta",
            width=130,
            height=30,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._select_download_folder,
        )
        self.clip_folder_btn.grid(row=0, column=1, padx=(0, 8), pady=2, sticky="e")

        clip_open_folder_btn = ctk.CTkButton(
            clip_folder_subframe,
            text="Abrir Destino",
            width=115,
            height=30,
            fg_color=("#3B8ED0", "gray28"),
            hover_color=("#36719F", "gray35"),
            text_color="#FFFFFF",
            command=self._open_download_folder,
        )
        clip_open_folder_btn.grid(row=0, column=2, pady=2, sticky="e")

        # Botón principal de descarga del fragmento (Pestaña 2)
        self.clip_download_btn = ctk.CTkButton(
            self.clip_tab_container,
            text="RECORTAR Y DESCARGAR FRAGMENTO",
            height=44,
            corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_clip_download_thread,
        )
        self.clip_download_btn.grid(row=1, column=0, padx=20, pady=4, sticky="ew")

        # 4. Barra de progreso y etiqueta de estado interactiva (compartida por ambas pestañas)
        status_frame = ctk.CTkFrame(self, corner_radius=12)
        status_frame.grid(row=3, column=0, padx=20, pady=4, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Estado: Listo para descargar",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.status_label.grid(row=0, column=0, padx=16, pady=(10, 4), sticky="w")

        self.percent_label = ctk.CTkLabel(
            status_frame,
            text="0%",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.percent_label.grid(row=0, column=1, padx=16, pady=(10, 4), sticky="e")

        self.progress_bar = ctk.CTkProgressBar(status_frame, height=14, corner_radius=7)
        self.progress_bar.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="ew")
        self.progress_bar.set(0)

        # 5. Consola / Log desplazable en tiempo real
        log_frame = ctk.CTkFrame(self, corner_radius=12)
        log_frame.grid(row=4, column=0, padx=20, pady=(4, 14), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        log_header = ctk.CTkLabel(
            log_frame,
            text="Registro de actividad en tiempo real:",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        log_header.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        self.log_textbox = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
            state="disabled",
        )
        self.log_textbox.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")

        self._append_log("Universal Downloader iniciado correctamente.")
        self._append_log("Plataformas activas: YouTube, TikTok, Instagram, Facebook y Twitter (X).")
        if self.ffmpeg_path:
            self._append_log(f"Motor FFmpeg integrado listo: {os.path.basename(self.ffmpeg_path)}")
        else:
            self._append_log(
                "[AVISO] No se detectó FFmpeg. Instala 'imageio-ffmpeg' o FFmpeg para unir flujos HD y convertir a MP3/GIF."
            )

    # -------------------------------------------------------------------------
    # SELECTOR DE CALIDAD Y CÁLCULO DE PESO EXACTO EN TIEMPO REAL
    # -------------------------------------------------------------------------
    def _on_format_changed(self, selected_format: str):
        """Actualiza las opciones de calidad según el formato (excluyendo imágenes)."""
        if selected_format == self.FORMAT_VIDEO:
            vals = list(self.VIDEO_QUALITIES.keys())
            self.quality_combobox.configure(state="readonly", values=vals)
            self.quality_combobox.set(vals[0])
        elif selected_format == self.FORMAT_AUDIO:
            vals = list(self.AUDIO_QUALITIES.keys())
            self.quality_combobox.configure(state="readonly", values=vals)
            self.quality_combobox.set(vals[0])
        else:
            vals = ["No aplica (Original)"]
            self.quality_combobox.configure(state="readonly", values=vals)
            self.quality_combobox.set(vals[0])
            self.quality_combobox.configure(state="disabled")

        # Si hay una lista de reproducción abierta, aplicar como preajuste global a todas las filas
        if self.is_playlist_mode and selected_format in (self.FORMAT_VIDEO, self.FORMAT_AUDIO):
            for _var, _entry, fmt_cb, qual_cb in self.playlist_vars:
                fmt_cb.set(selected_format)
                qual_cb.configure(state="readonly", values=vals)
                qual_cb.set(vals[0])

        self._recalculate_realtime_size()

    def _on_quality_changed(self, selected_quality: str):
        """Recalcula instantáneamente el peso y bloquea el format_id correspondiente."""
        if self.is_playlist_mode:
            global_fmt = self.format_combobox.get()
            for _var, _entry, fmt_cb, qual_cb in self.playlist_vars:
                if fmt_cb.get() == global_fmt:
                    qual_cb.set(selected_quality)
        self._recalculate_realtime_size()

    def _on_url_entry_changed(self, _event=None):
        """Aplica debounce de 300 ms al escribir en el campo URL para evitar lanzar hilos por cada tecla."""
        if self._url_debounce_after_id:
            try:
                self.after_cancel(self._url_debounce_after_id)
            except Exception:
                pass
            self._url_debounce_after_id = None

        url = self.url_entry.get().strip()
        if url.startswith(("http://", "https://")) and url != self.analyzed_url:
            self._url_debounce_after_id = self.after(300, lambda: self._trigger_url_analysis(force=False))

    def _paste_from_clipboard(self):
        try:
            clip = self.clipboard_get().strip()
            if clip:
                if self._url_debounce_after_id:
                    try:
                        self.after_cancel(self._url_debounce_after_id)
                    except Exception:
                        pass
                    self._url_debounce_after_id = None
                self.url_entry.delete(0, "end")
                self.url_entry.insert(0, clip)
                if clip.startswith(("http://", "https://")):
                    self._trigger_url_analysis(force=True)
        except Exception:
            pass

    def _clear_url(self):
        if self._url_debounce_after_id:
            try:
                self.after_cancel(self._url_debounce_after_id)
            except Exception:
                pass
            self._url_debounce_after_id = None
        self.url_entry.delete(0, "end")
        self.analyzed_url = None
        self.analyzed_info = None
        self.locked_format_id = None
        self.is_playlist_mode = False
        for child in self.playlist_scroll.winfo_children():
            child.destroy()
        self.playlist_vars.clear()
        self.preview_card_frame.grid_remove()
        self.playlist_frame.grid_remove()
        if not self.is_busy:
            self.download_btn.configure(text="INICIAR DESCARGA")
        self.media_info_label.configure(text="Pega un enlace para calcular calidades y peso automáticamente")
        self.size_estimate_label.configure(text="Peso estimado: Pega un enlace")

    @staticmethod
    def _extract_best_thumbnail_url(info: dict) -> str | None:
        """Elige una miniatura ligera (~240 px de ancho, ~10 KB) para carga instantánea sin impacto en rendimiento."""
        if not info:
            return None
        if info.get("suno_img_url"):
            return str(info["suno_img_url"])

        thumbs = info.get("thumbnails") or []
        valid_thumbs = [
            t for t in thumbs
            if isinstance(t, dict)
            and str(t.get("url") or "").startswith(("http://", "https://"))
            and not str(t.get("url") or "").endswith(".mhtml")
        ]
        if valid_thumbs:
            sized = [t for t in valid_thumbs if (t.get("width") or t.get("height"))]
            if sized:
                sized.sort(key=lambda t: abs((t.get("width") or (t.get("height") or 135) * 16 // 9) - 240))
                return str(sized[0]["url"])
            return str(valid_thumbs[-1]["url"])

        direct_thumb = info.get("thumbnail")
        if direct_thumb and str(direct_thumb).startswith(("http://", "https://")):
            return str(direct_thumb)

        if info.get("_is_playlist") and info.get("entries"):
            first_entry = info["entries"][0]
            if isinstance(first_entry, dict):
                sub = UniversalDownloaderApp._extract_best_thumbnail_url(first_entry)
                if sub:
                    return sub
                vid_id = str(first_entry.get("id") or "")
                if len(vid_id) == 11:
                    return f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"

        vid_id = str(info.get("id") or "")
        if len(vid_id) == 11 and "youtube" in str(info.get("extractor") or info.get("webpage_url") or "").lower():
            return f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"

        return None

    def _load_thumbnail_async(self, info: dict, generation: int, is_clip_tab: bool = False):
        """Descarga y redimensiona la miniatura en segundo plano con caché en memoria (sin bloquear la UI)."""
        target_label = self.clip_thumb_label if is_clip_tab else self.preview_thumb_label
        thumb_url = self._extract_best_thumbnail_url(info)
        if not thumb_url:
            target_label.configure(image=self._placeholder_thumb)
            return

        with self._cache_lock:
            cached_img = self._thumb_cache.get(thumb_url)
        if cached_img is not None:
            target_label.configure(image=cached_img)
            return

        target_label.configure(image=self._placeholder_thumb)

        def _thumb_worker():
            try:
                req = urllib.request.Request(
                    thumb_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                        )
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    raw_bytes = resp.read(3 * 1024 * 1024)
                ctk_img = ctk.decode_thumbnail_bytes_to_ctk_image(raw_bytes, size=(88, 50))
                if not ctk_img:
                    return
                with self._cache_lock:
                    if len(self._thumb_cache) >= 32:
                        oldest = next(iter(self._thumb_cache))
                        self._thumb_cache.pop(oldest, None)
                    self._thumb_cache[thumb_url] = ctk_img
                current_gen = self._clip_analyze_generation if is_clip_tab else self._analyze_generation
                if generation == current_gen:
                    self.after(0, lambda: target_label.configure(image=ctk_img))
            except Exception:
                pass

        threading.Thread(target=_thumb_worker, daemon=True).start()

    def _on_playlist_row_format_changed(
        self, new_fmt: str, fmt_proxy: _PlaylistRowComboProxy, qual_proxy: _PlaylistRowComboProxy
    ):
        """Actualiza el selector de calidad individual de una fila de la playlist al cambiar entre MP4 y MP3."""
        fmt_proxy.set(new_fmt)
        if new_fmt == self.FORMAT_AUDIO:
            q_vals = list(self.AUDIO_QUALITIES.keys())
        else:
            q_vals = list(self.VIDEO_QUALITIES.keys())
        qual_proxy.configure(state="readonly", values=q_vals)
        qual_proxy.set(q_vals[0])
        self._recalculate_realtime_size()

    def _on_playlist_row_quality_changed(self, new_qual: str, qual_proxy: _PlaylistRowComboProxy):
        qual_proxy.set(new_qual)
        self._recalculate_realtime_size()

    def _populate_playlist_checklist(self, entries: list[dict]):
        """
        Construye la lista interactiva con casilla y 2 selectores desplegables (Formato MP4/MP3 + Calidad)
        por cada elemento, usando renderizado progresivo por lotes para no congelar la interfaz.
        """
        for child in self.playlist_scroll.winfo_children():
            child.destroy()
        self.playlist_vars.clear()

        default_fmt = self.format_combobox.get()
        if default_fmt not in (self.FORMAT_VIDEO, self.FORMAT_AUDIO):
            default_fmt = self.FORMAT_VIDEO

        default_q_vals = (
            list(self.VIDEO_QUALITIES.keys())
            if default_fmt == self.FORMAT_VIDEO
            else list(self.AUDIO_QUALITIES.keys())
        )
        current_global_q = self.quality_combobox.get()
        default_qual = current_global_q if current_global_q in default_q_vals else default_q_vals[0]

        # 1. Inicializar en < 1 ms los proxies de estado para todos los elementos de la lista
        for entry in entries:
            var = ctk.BooleanVar(value=True)
            fmt_proxy = _PlaylistRowComboProxy(default_fmt, [self.FORMAT_VIDEO, self.FORMAT_AUDIO])
            qual_proxy = _PlaylistRowComboProxy(default_qual, default_q_vals)
            self.playlist_vars.append((var, entry, fmt_proxy, qual_proxy))

        batch_gen = self._analyze_generation

        def _render_row_slice(start_idx: int, count: int):
            if batch_gen != self._analyze_generation or not self.is_playlist_mode:
                return
            end_idx = min(start_idx + count, len(self.playlist_vars))
            for row_i in range(start_idx, end_idx):
                var, entry, fmt_proxy, qual_proxy = self.playlist_vars[row_i]
                idx = row_i + 1
                raw_title = (entry.get("title") or f"Elemento #{idx}").strip()
                dur = entry.get("duration")
                if dur and dur > 0:
                    item_text = f"{idx:02d}. {raw_title[:46]}  ({format_duration(dur)})"
                else:
                    item_text = f"{idx:02d}. {raw_title[:54]}"

                cb = ctk.CTkCheckBox(
                    self.playlist_scroll,
                    text=item_text,
                    variable=var,
                    font=ctk.CTkFont(size=12),
                    checkbox_width=18,
                    checkbox_height=18,
                    corner_radius=5,
                    command=self._on_playlist_check_toggled,
                )
                cb.grid(row=row_i, column=0, padx=(8, 6), pady=3, sticky="w")

                fmt_combo = ctk.CTkComboBox(
                    self.playlist_scroll,
                    values=fmt_proxy.values,
                    width=118,
                    height=26,
                    state=fmt_proxy.state,
                    font=ctk.CTkFont(size=11),
                )
                fmt_combo.set(fmt_proxy.value)
                fmt_combo.grid(row=row_i, column=1, padx=(4, 4), pady=3, sticky="e")
                fmt_proxy.widget = fmt_combo

                qual_combo = ctk.CTkComboBox(
                    self.playlist_scroll,
                    values=qual_proxy.values,
                    width=178,
                    height=26,
                    state=qual_proxy.state,
                    font=ctk.CTkFont(size=11),
                    command=lambda new_q, qp=qual_proxy: self._on_playlist_row_quality_changed(new_q, qp),
                )
                qual_combo.set(qual_proxy.value)
                qual_combo.grid(row=row_i, column=2, padx=(4, 8), pady=3, sticky="e")
                qual_proxy.widget = qual_combo

                fmt_combo.configure(
                    command=lambda new_f, fp=fmt_proxy, qp=qual_proxy: self._on_playlist_row_format_changed(
                        new_f, fp, qp
                    )
                )

            if end_idx < len(self.playlist_vars):
                self.after(35, lambda: _render_row_slice(end_idx, 8))

        # Renderizar inmediatamente las primeras 6 filas visibles (~90 ms) y el resto en segundo plano
        _render_row_slice(0, 6)

    def _set_all_playlist_checks(self, checked: bool):
        if self.is_busy:
            return
        for var, _entry, _fmt_cb, _qual_cb in self.playlist_vars:
            var.set(checked)
        self._on_playlist_check_toggled()

    def _on_playlist_check_toggled(self):
        self._recalculate_realtime_size()

    def _apply_analyzed_info_to_ui(self, info: dict):
        """Actualiza tarjeta de vista previa, miniatura, checklist de playlist y cálculo de peso."""
        self.analyzed_info = info
        is_playlist = bool(info.get("_is_playlist") and info.get("entries"))
        self.is_playlist_mode = is_playlist

        self.preview_card_frame.grid()
        self._load_thumbnail_async(info, self._analyze_generation)

        if is_playlist:
            entries = info.get("entries") or []
            pl_title = (info.get("title") or "Lista de reproducción").strip()
            total_dur = sum(float(e.get("duration") or 0) for e in entries)
            dur_part = f" • Duración total: {format_duration(total_dur)}" if total_dur > 0 else ""

            self.preview_title_label.configure(text=f"Lista: {pl_title[:64]}")
            self.preview_meta_label.configure(
                text=f"{len(entries)} elementos detectados{dur_part} • Elige cuáles descargar en la lista inferior"
            )
            self.media_info_label.configure(text=f"Lista: {pl_title[:36]} ({len(entries)} elementos)")

            self._populate_playlist_checklist(entries)
            self.playlist_frame.grid()
            self._recalculate_realtime_size()
        else:
            self.playlist_frame.grid_remove()
            self.playlist_vars.clear()
            if not self.is_busy:
                self.download_btn.configure(text="INICIAR DESCARGA")

            raw_title = (info.get("title") or "Contenido multimedia").strip()
            duration = info.get("duration")
            is_tw_gif = self._is_twitter_gif_info(info)
            is_suno = bool(info.get("suno_mp4_url"))
            dur_str = "GIF animado" if is_tw_gif else format_duration(duration)

            if is_tw_gif:
                type_badge = "GIF animado"
            elif is_suno:
                type_badge = "Audio / Canción HD"
            else:
                v_fmts = [f for f in (info.get("formats") or []) if self._has_video(f)]
                if v_fmts:
                    v_fmts.sort(key=lambda f: max(f.get("width") or 0, f.get("height") or 0), reverse=True)
                    type_badge = f"Video ({self._resolution_label(v_fmts[0])})"
                else:
                    type_badge = "Contenido multimedia"

            uploader = (info.get("uploader") or info.get("channel") or "").strip()
            uploader_part = f" • {uploader[:28]}" if uploader else ""

            self.preview_title_label.configure(text=raw_title[:68])
            self.preview_meta_label.configure(text=f"{type_badge} • Duración: {dur_str}{uploader_part}")
            self.media_info_label.configure(text=f"{raw_title[:46]}  ({dur_str})")

            if is_tw_gif and self.format_combobox.get() != self.FORMAT_IMAGE_GIF:
                self.format_combobox.set(self.FORMAT_IMAGE_GIF)
                self._on_format_changed(self.FORMAT_IMAGE_GIF)
            else:
                self._recalculate_realtime_size()

    def _trigger_url_analysis(self, force: bool = False):
        url = self.url_entry.get().strip()
        if not url or not url.startswith(("http://", "https://")):
            return
        if not force and url == self.analyzed_url and self.analyzed_info is not None:
            self._recalculate_realtime_size()
            return

        # Consulta instantánea en caché LRU en memoria (0 ms) si el enlace ya fue analizado en la sesión
        with self._cache_lock:
            cached_info = self._url_info_cache.get(url)
        if not force and cached_info is not None:
            self.analyzed_url = url
            self._apply_analyzed_info_to_ui(cached_info)
            return

        self._analyze_generation += 1
        current_gen = self._analyze_generation
        self.analyzed_url = url
        self.analyzed_info = None
        self.locked_format_id = None

        self.size_estimate_label.configure(text="Peso estimado: Calculando...")
        self.media_info_label.configure(text="Analizando flujos del enlace...")

        threading.Thread(
            target=self._analyze_url_worker,
            args=(url, current_gen),
            daemon=True,
        ).start()

    @staticmethod
    def _is_suno_url(url: str) -> bool:
        """Detecta internamente enlaces de Suno sin mostrarlo en la interfaz."""
        return bool(re.search(r"https?://(?:www\.)?(?:suno\.com|suno\.ai|cdn[0-9]*\.suno\.ai)/", url, re.I))

    def _extract_suno_info(self, url: str) -> dict:
        """Extrae título, duración, tamaño exacto y enlaces CDN desde una URL de Suno."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            final_url = resp.geturl()
            html_text = resp.read().decode("utf-8", errors="ignore")

        m_uuid = re.search(
            r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            final_url + " " + html_text,
        )
        if not m_uuid:
            raise yt_dlp.utils.DownloadError("No se encontró el identificador de la pista en el enlace.")

        song_id = m_uuid.group(1)
        title = f"Suno_{song_id[:8]}"
        for pattern in [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
            r"<title>([^<]+)</title>",
        ]:
            m_title = re.search(pattern, html_text, re.I)
            if m_title and m_title.group(1).strip():
                raw_t = m_title.group(1).strip()
                raw_t = re.sub(r"\s*\|\s*Suno.*$", "", raw_t, flags=re.I)
                if raw_t:
                    title = raw_t
                    break

        mp4_url = f"https://cdn1.suno.ai/{song_id}.mp4"
        img_url = f"https://cdn2.suno.ai/image_large_{song_id}.jpeg"
        m_img = re.search(r"https://cdn[0-9]*\.suno\.ai/image_large_[^\"'\\\s<>]+", html_text)
        if m_img:
            img_url = m_img.group(0)

        # Obtener tamaño exacto en bytes mediante petición parcial Range
        exact_bytes = 0
        try:
            r_range = urllib.request.Request(mp4_url, headers={**headers, "Range": "bytes=0-0"})
            with urllib.request.urlopen(r_range, timeout=8) as r_resp:
                cr = r_resp.headers.get("Content-Range", "")
                if "/" in cr:
                    exact_bytes = int(cr.split("/")[-1].strip())
        except Exception:
            pass

        # Obtener duración directamente del HTML/JSON de Suno (0 ms), con FFmpeg como respaldo
        duration = None
        m_html_dur = re.search(r'\\?"duration\\?"\s*:\s*(\d+(?:\.\d+)?)', html_text)
        if m_html_dur:
            try:
                duration = float(m_html_dur.group(1))
            except Exception:
                duration = None

        if not duration and self.ffmpeg_path:
            try:
                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                pr = subprocess.run(
                    [self.ffmpeg_path, "-i", mp4_url],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    creationflags=creation_flags,
                )
                m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", pr.stderr)
                if m_dur:
                    duration = (
                        int(m_dur.group(1)) * 3600
                        + int(m_dur.group(2)) * 60
                        + float(m_dur.group(3))
                    )
            except Exception:
                pass

        return {
            "id": song_id,
            "title": title,
            "duration": duration,
            "webpage_url": url,
            "suno_mp4_url": mp4_url,
            "suno_img_url": img_url,
            "filesize": exact_bytes,
            "formats": [
                {
                    "format_id": "suno-hd",
                    "ext": "mp4",
                    "protocol": "https",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "width": 824,
                    "height": 1464,
                    "filesize": exact_bytes,
                    "url": mp4_url,
                }
            ],
        }

    @staticmethod
    def _is_twitter_status_url(url: str) -> bool:
        return bool(
            re.search(
                r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/(?:[^/]+/status|i/status|i/web/status)/\d+",
                url,
                re.I,
            )
        )

    def _extract_twitter_fallback_info(self, url: str) -> dict | None:
        """
        Respaldo automático vía API de sindicación (FxTwitter) cuando X/Twitter bloquea el Guest Token
        en cuentas marcadas como contenido sensible (+18 / NSFW) devolviendo 'Video #1 is unavailable'.
        """
        m = re.search(
            r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/(?:[^/]+/status|i/status|i/web/status)/(\d+)(?:/video/(\d+))?",
            url,
            re.I,
        )
        if not m:
            return None

        tweet_id = m.group(1)
        vid_idx = max(0, int(m.group(2)) - 1) if m.group(2) else 0

        api_url = f"https://api.fxtwitter.com/status/{tweet_id}"
        req = urllib.request.Request(api_url, headers={"User-Agent": f"UniversalDownloader/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tweet = data.get("tweet") or {}
        media_block = tweet.get("media") or {}
        videos = media_block.get("videos") or media_block.get("all") or []
        if not videos:
            return None

        vid = videos[min(vid_idx, len(videos) - 1)]
        author_obj = tweet.get("author") or {}
        uploader = author_obj.get("name") or author_obj.get("screen_name") or "X"
        raw_text = (tweet.get("text") or "").strip()
        clean_title = re.sub(r"https?://t\.co/\S+", "", raw_text).strip()
        title = f"{uploader} - {clean_title}" if clean_title else f"{uploader} - Video {tweet_id}"

        duration = float(vid.get("duration") or 0.0)
        thumb_url = vid.get("thumbnail_url")
        vid_type = str(vid.get("type") or "video").lower()
        is_gif = vid_type == "gif" or "tweet_video" in str(vid.get("url") or "")

        formats = []
        raw_variants = vid.get("formats") or vid.get("variants") or []
        for idx, var in enumerate(raw_variants):
            v_url = str(var.get("url") or "")
            if not v_url.startswith(("http://", "https://")):
                continue
            if ".m3u8" in v_url or var.get("container") == "m3u8":
                formats.append(
                    {
                        "format_id": f"hls-master-{idx}",
                        "url": v_url,
                        "ext": "mp4",
                        "protocol": "m3u8_native",
                        "vcodec": "h264",
                        "acodec": "none" if is_gif else "aac",
                        "width": int(vid["width"]) if vid.get("width") else None,
                        "height": int(vid["height"]) if vid.get("height") else None,
                        "tbr": None,
                    }
                )
                continue

            w, h = None, None
            m_res = re.search(r"/(\d+)x(\d+)/", v_url)
            if m_res:
                w, h = int(m_res.group(1)), int(m_res.group(2))
            elif vid.get("width") and vid.get("height"):
                w, h = int(vid["width"]), int(vid["height"])

            bitrate = var.get("bitrate") or 0
            tbr = round(bitrate / 1000.0, 2) if bitrate else None
            fmt_id = f"http-{int(tbr)}" if tbr else f"mp4-{idx}"

            formats.append(
                {
                    "format_id": fmt_id,
                    "url": v_url,
                    "ext": "mp4",
                    "protocol": "https",
                    "vcodec": "h264",
                    "acodec": "none" if is_gif else "aac",
                    "width": w,
                    "height": h,
                    "tbr": tbr,
                }
            )

        if not formats and vid.get("url"):
            formats.append(
                {
                    "format_id": "http-best",
                    "url": str(vid["url"]),
                    "ext": "mp4",
                    "protocol": "https",
                    "vcodec": "h264",
                    "acodec": "none" if is_gif else "aac",
                    "width": vid.get("width"),
                    "height": vid.get("height"),
                }
            )

        if not formats:
            return None

        info = {
            "id": str(vid.get("id") or tweet_id),
            "title": title[:120],
            "uploader": uploader,
            "duration": duration,
            "thumbnail": thumb_url,
            "thumbnails": [{"url": thumb_url}] if thumb_url else [],
            "webpage_url": url,
            "extractor": "twitter",
            "extractor_key": "Twitter",
            "formats": formats,
            "tw_direct_fallback": True,
        }
        self._populate_missing_direct_filesizes(info, None)
        return info

    def _select_twitter_fallback_stream_url(
        self, info: dict, selected_quality: str, locked_id: str | None = None
    ) -> str | None:
        """Elige la URL directa de video.twimg.com correspondiente a la calidad seleccionada (priorizando HLS si > 900 MB)."""
        formats = info.get("formats") or []
        if not formats:
            return None
        hls_formats = [f for f in formats if "m3u8" in str(f.get("protocol") or "") and f.get("url")]
        http_formats = [f for f in formats if "m3u8" not in str(f.get("protocol") or "") and f.get("url")]

        if locked_id:
            base_locked = locked_id.split("+")[0]
            for f in formats:
                if str(f.get("format_id")) in (locked_id, base_locked) and f.get("url"):
                    f_bytes = f.get("filesize") or f.get("filesize_approx") or 0
                    if (
                        "m3u8" not in str(f.get("protocol") or "")
                        and f_bytes > 900 * 1024 * 1024
                        and self.ffmpeg_path
                        and hls_formats
                    ):
                        return str(hls_formats[0]["url"])
                    return str(f["url"])

        tier_bounds = self.VIDEO_QUALITIES.get(selected_quality)
        pool_base = http_formats if http_formats else formats
        candidates = [f for f in pool_base if self._fits_resolution_tier(f, tier_bounds)]
        if not candidates:
            candidates = list(pool_base)
        candidates.sort(
            key=lambda f: (
                max(f.get("width") or 0, f.get("height") or 0),
                f.get("tbr") or 0,
                f.get("filesize") or 0,
            ),
            reverse=True,
        )
        if not candidates:
            return None
        chosen = candidates[0]
        chosen_bytes = chosen.get("filesize") or chosen.get("filesize_approx") or 0
        if (
            "m3u8" not in str(chosen.get("protocol") or "")
            and chosen_bytes > 900 * 1024 * 1024
            and self.ffmpeg_path
            and hls_formats
        ):
            return str(hls_formats[0]["url"])
        return str(chosen.get("url"))

    def _download_twitter_fallback(
        self,
        url: str,
        selected_format: str,
        selected_quality: str,
        locked_id: str | None = None,
        clip_range: tuple[float, float] | None = None,
    ) -> str | None:
        """Descarga o recorta directamente desde el CDN video.twimg.com cuando X bloquea el Guest Token."""
        fb_info = None
        if self.analyzed_url == url and self.analyzed_info and self.analyzed_info.get("tw_direct_fallback"):
            fb_info = self.analyzed_info
        elif (
            self.clip_analyzed_url == url
            and self.clip_analyzed_info
            and self.clip_analyzed_info.get("tw_direct_fallback")
        ):
            fb_info = self.clip_analyzed_info
        else:
            fb_info = self._extract_twitter_fallback_info(url)

        if not fb_info:
            raise yt_dlp.utils.DownloadError("No se pudo extraer el video mediante el respaldo de X/Twitter.")

        direct_url = self._select_twitter_fallback_stream_url(fb_info, selected_quality, locked_id)
        if not direct_url:
            raise yt_dlp.utils.DownloadError("No se encontró flujo MP4 directo en la publicación de X.")

        self._append_log("[INFO] Usando extracción directa de CDN para publicación restringida de X/Twitter...")
        os.makedirs(self.download_dir, exist_ok=True)
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", fb_info.get("title") or "Video_X").strip(" .")[:95]
        vid_id = fb_info.get("id") or "x"

        if clip_range:
            start_sec, end_sec = clip_range
            tag_start = format_timestamp_input(start_sec).replace(":", "m") + "s"
            tag_end = format_timestamp_input(end_sec).replace(":", "m") + "s"
            clip_part = f" [Clip {tag_start}-{tag_end}]"
        else:
            clip_part = ""

        if selected_format == self.FORMAT_IMAGE_GIF:
            tmp_suffix = ".gif_tmp"
            dl_format = self.FORMAT_VIDEO
        elif selected_format == self.FORMAT_AUDIO:
            tmp_suffix = ".audio_tmp"
            dl_format = self.FORMAT_AUDIO
        else:
            tmp_suffix = ""
            dl_format = self.FORMAT_VIDEO

        ydl_opts = self._build_ydl_options(dl_format, selected_quality, None)
        ydl_opts["format"] = "best"
        ydl_opts["outtmpl"] = os.path.join(
            self.download_dir, f"{safe_title} [{vid_id}]{clip_part}{tmp_suffix}.%(ext)s"
        )
        if clip_range:
            ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [clip_range])
            ydl_opts["force_keyframes_at_cuts"] = True
            ydl_opts["external_downloader_args"] = {"ffmpeg": ["-loglevel", "error"]}

        downloaded_filepath = None
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(direct_url, download=True)
            if info:
                if "requested_downloads" in info and info["requested_downloads"]:
                    downloaded_filepath = info["requested_downloads"][0].get("filepath")
                else:
                    downloaded_filepath = ydl.prepare_filename(info)

        if (
            selected_format == self.FORMAT_AUDIO
            and downloaded_filepath
            and os.path.isfile(downloaded_filepath)
            and ".audio_tmp." in downloaded_filepath
        ):
            clean_audio_path = downloaded_filepath.replace(".audio_tmp.", ".")
            try:
                os.replace(downloaded_filepath, clean_audio_path)
                downloaded_filepath = clean_audio_path
            except Exception:
                pass

        return downloaded_filepath

    @staticmethod
    def _resolve_entry_url(entry: dict) -> str | None:
        """Resuelve la URL descargable de un elemento individual dentro de una lista de reproducción."""
        for key in ("webpage_url", "url", "original_url"):
            val = entry.get(key)
            if val and str(val).startswith(("http://", "https://")):
                return str(val)
        vid_id = entry.get("id")
        if vid_id:
            return f"https://www.youtube.com/watch?v={vid_id}"
        return None

    def _analyze_url_worker(self, url: str, generation: int):
        """Extrae metadatos reales (enlace individual o lista de reproducción) de forma rápida."""
        base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        }
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": 100,
            "skip_download": True,
            "js_runtimes": YTDLP_JS_RUNTIMES,
            "remote_components": YTDLP_REMOTE_COMPONENTS,
            "http_headers": base_headers,
        }
        try:
            if self._is_suno_url(url):
                info = self._extract_suno_info(url)
            else:
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if generation != self._analyze_generation or not info:
                            return

                        if "entries" in info or info.get("_type") == "playlist":
                            entries_list = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
                            if len(entries_list) > 1:
                                # Es una lista de reproducción con múltiples elementos
                                normalized_entries = []
                                for idx, entry in enumerate(entries_list, start=1):
                                    resolved_u = self._resolve_entry_url(entry)
                                    if not resolved_u:
                                        continue
                                    normalized_entries.append(
                                        {
                                            "id": entry.get("id") or f"item_{idx}",
                                            "title": entry.get("title") or f"Elemento #{idx}",
                                            "duration": entry.get("duration"),
                                            "url": resolved_u,
                                            "thumbnails": entry.get("thumbnails"),
                                            "thumbnail": entry.get("thumbnail"),
                                        }
                                    )
                                if len(normalized_entries) > 1:
                                    info["_is_playlist"] = True
                                    info["entries"] = normalized_entries
                                elif len(normalized_entries) == 1:
                                    single_opts = dict(opts, noplaylist=True)
                                    single_opts.pop("extract_flat", None)
                                    with yt_dlp.YoutubeDL(single_opts) as single_ydl:
                                        info = single_ydl.extract_info(normalized_entries[0]["url"], download=False)
                                        self._populate_missing_direct_filesizes(info, single_ydl)
                            elif len(entries_list) == 1:
                                first_e = entries_list[0]
                                if first_e.get("formats"):
                                    info = first_e
                                    self._populate_missing_direct_filesizes(info, ydl)
                                else:
                                    target_u = self._resolve_entry_url(first_e) or url
                                    single_opts = dict(opts, noplaylist=True)
                                    single_opts.pop("extract_flat", None)
                                    with yt_dlp.YoutubeDL(single_opts) as single_ydl:
                                        info = single_ydl.extract_info(target_u, download=False)
                                        self._populate_missing_direct_filesizes(info, single_ydl)
                        else:
                            self._populate_missing_direct_filesizes(info, ydl)
                except Exception:
                    info = None
                    if self._is_twitter_status_url(url):
                        try:
                            info = self._extract_twitter_fallback_info(url)
                        except Exception:
                            info = None
                    if not info:
                        if self.use_external_engine and self.external_ytdlp_path.is_file():
                            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                            res = subprocess.run(
                                [
                                    str(self.external_ytdlp_path),
                                    "--dump-single-json",
                                    "--no-playlist",
                                    "--no-warnings",
                                    "--no-check-certificate",
                                    *YTDLP_CLI_JS_ARGS,
                                    url,
                                ],
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                timeout=25,
                                creationflags=creation_flags,
                            )
                            if res.returncode == 0 and res.stdout.strip():
                                info = json.loads(res.stdout.strip().splitlines()[-1])
                                self._populate_missing_direct_filesizes(info, None)
                            else:
                                raise
                        else:
                            raise

            if generation != self._analyze_generation or not info:
                return

            with self._cache_lock:
                if len(self._url_info_cache) >= 32:
                    oldest_key = next(iter(self._url_info_cache))
                    self._url_info_cache.pop(oldest_key, None)
                self._url_info_cache[url] = info

            self.after(0, lambda: self._apply_analyzed_info_to_ui(info))

        except Exception:
            if generation == self._analyze_generation:
                self.after(
                    0,
                    lambda: (
                        self.media_info_label.configure(text="Enlace listo para descargar"),
                        self.size_estimate_label.configure(text="Peso estimado: Variable según plataforma"),
                    ),
                )

    def _populate_missing_direct_filesizes(self, info: dict, ydl=None):
        """
        En plataformas como X/Twitter, TikTok o Instagram, yt-dlp no consulta el Content-Length real
        de los flujos HTTP directos y en X calcula un 'filesize_approx' falso usando el bitrate tope
        teórico (ej. 10368 kbps -> 76.6 MB cuando el archivo real pesa 11.8 MB).
        Esta función consulta en paralelo los encabezados HTTP (HEAD / Range) de los flujos directos
        sin 'filesize' para obtener el peso exacto byte a byte desde el servidor CDN.
        """
        formats = info.get("formats") or []
        if not formats:
            return

        base_headers = dict(info.get("http_headers") or {})
        if "User-Agent" not in base_headers:
            base_headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )

        to_probe = [
            f for f in formats
            if not f.get("filesize")
            and str(f.get("protocol") or "") in ("http", "https")
            and not f.get("fragments")
            and str(f.get("url") or "").startswith(("http://", "https://"))
        ]

        def _probe_one(fmt: dict):
            target_url = fmt.get("url")
            if not target_url:
                return
            hdrs = dict(base_headers)
            if fmt.get("http_headers"):
                hdrs.update(fmt["http_headers"])

            # 1) Intentar con el cliente de yt-dlp (incluye cookies de sesión de X/TikTok/Instagram)
            if ydl is not None:
                try:
                    from yt_dlp.networking import Request as YdlRequest
                    req_ydl = YdlRequest(target_url, method="HEAD", headers=hdrs)
                    with ydl.urlopen(req_ydl) as resp:
                        cl = resp.headers.get("Content-Length")
                        if cl and str(cl).strip().isdigit() and int(cl) > 0:
                            exact_sz = int(cl)
                            fmt["filesize"] = exact_sz
                            fmt["filesize_approx"] = exact_sz
                            return
                except Exception:
                    pass

            # 2) Intentar petición HEAD estándar
            try:
                req = urllib.request.Request(target_url, headers=hdrs, method="HEAD")
                with urllib.request.urlopen(req, timeout=4) as resp:
                    cl = resp.headers.get("Content-Length")
                    if cl and str(cl).strip().isdigit() and int(cl) > 0:
                        exact_sz = int(cl)
                        fmt["filesize"] = exact_sz
                        fmt["filesize_approx"] = exact_sz
                        return
            except Exception:
                pass

            # 3) Respaldo con petición parcial GET Range: bytes=0-0 (para CDNs que bloquean HEAD)
            try:
                range_hdrs = dict(hdrs)
                range_hdrs["Range"] = "bytes=0-0"
                req_r = urllib.request.Request(target_url, headers=range_hdrs, method="GET")
                with urllib.request.urlopen(req_r, timeout=4) as resp:
                    cr = resp.headers.get("Content-Range", "")
                    if "/" in cr:
                        total_str = cr.split("/")[-1].strip()
                        if total_str.isdigit() and int(total_str) > 0:
                            exact_sz = int(total_str)
                            fmt["filesize"] = exact_sz
                            fmt["filesize_approx"] = exact_sz
                            return
                    cl = resp.headers.get("Content-Length")
                    if cl and str(cl).strip().isdigit() and int(cl) > 1:
                        exact_sz = int(cl)
                        fmt["filesize"] = exact_sz
                        fmt["filesize_approx"] = exact_sz
                        return
            except Exception:
                pass

        if to_probe:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(to_probe))) as executor:
                list(executor.map(_probe_one, to_probe))

        # Respaldo adicional para X/Twitter si algún proxy bloqueara HEAD/Range:
        # reemplazar el 'filesize_approx' inflado de 'http-*' usando el bitrate real de su par 'hls-*'
        duration = info.get("duration")
        if duration and duration > 0:
            hls_audio_tbr = max(
                (float(f.get("tbr") or 0) for f in formats if self._is_audio_only(f)),
                default=128.0,
            )
            hls_by_res = {}
            for f in formats:
                if "m3u8" in str(f.get("protocol") or "") and self._has_video(f) and f.get("tbr"):
                    key = (f.get("width") or 0, f.get("height") or 0)
                    hls_by_res[key] = float(f["tbr"])

            for f in to_probe:
                if not f.get("filesize") and str(f.get("format_id") or "").startswith("http-"):
                    key = (f.get("width") or 0, f.get("height") or 0)
                    if key in hls_by_res:
                        real_tbr = hls_by_res[key] + hls_audio_tbr
                        f["filesize_approx"] = int((real_tbr * 1000.0 / 8.0) * float(duration))

    @staticmethod
    def _is_twitter_gif_info(info: dict | None) -> bool:
        """Detecta si el contenido extraído de X/Twitter es un GIF animado (tweet_video)."""
        if not info:
            return False
        for f in info.get("formats") or []:
            if "/tweet_video/" in str(f.get("url") or ""):
                return True
        for t in info.get("thumbnails") or []:
            if "/tweet_video_thumb/" in str(t.get("url") or ""):
                return True
        return "/tweet_video/" in str(info.get("url") or "")

    @staticmethod
    def _has_video(fmt: dict) -> bool:
        """Indica si el flujo contiene pista de video (maneja tanto vcodec explícito como None con resolución en X/TikTok)."""
        vcodec = fmt.get("vcodec")
        if vcodec == "none" or fmt.get("ext") == "mhtml":
            return False
        return bool(vcodec is not None or fmt.get("height") or fmt.get("width") or fmt.get("vbr"))

    @staticmethod
    def _is_audio_only(fmt: dict) -> bool:
        """Indica si el flujo es exclusivamente de audio (incluso cuando X/Twitter reporta acodec=None y vcodec='none')."""
        return fmt.get("vcodec") == "none" and fmt.get("acodec") != "none"

    @staticmethod
    def _has_exact_filesize(fmt: dict) -> bool:
        """Indica si el servidor reporta el tamaño real en bytes (filesize) para este flujo directo (no m3u8)."""
        sz = fmt.get("filesize")
        proto = str(fmt.get("protocol") or "")
        return bool(sz and sz > 0 and "m3u8" not in proto)

    @staticmethod
    def _stream_bytes(fmt: dict, duration: float | None) -> int:
        """Obtiene el tamaño exacto en bytes o una estimación conservadora si es flujo HLS."""
        exact = fmt.get("filesize") or fmt.get("filesize_approx")
        if exact and exact > 0:
            return int(exact)
        tbr = fmt.get("tbr") or ((fmt.get("vbr") or 0) + (fmt.get("abr") or 0))
        if tbr and duration and duration > 0:
            proto = str(fmt.get("protocol") or "")
            url_str = str(fmt.get("url") or "")
            # En manifiestos m3u8 de YouTube, 'tbr' es el pico máximo (~2.8x el promedio real VBR);
            # en X/Twitter (twimg.com), el bitrate reportado corresponde al promedio real.
            factor = 0.36 if ("m3u8" in proto and "twimg.com" not in url_str) else 1.0
            return int((float(tbr) * factor * 1000.0 / 8.0) * float(duration))
        return 0

    @staticmethod
    def _fits_resolution_tier(fmt: dict, tier_bounds: tuple[int, int] | None) -> bool:
        """Comprueba si un flujo cabe dentro del nivel de resolución (soporta 16:9, 21:9 ultrawide y 9:16 vertical)."""
        if tier_bounds is None:
            return True
        target_short, target_long = tier_bounds
        w = fmt.get("width") or 0
        h = fmt.get("height") or 0
        if w > 0 and h > 0:
            short_side = min(w, h)
            long_side = max(w, h)
            return short_side <= target_short and long_side <= target_long
        if h > 0:
            return h <= target_short
        return False

    @staticmethod
    def _resolution_label(fmt: dict) -> str:
        """Devuelve una etiqueta legible como '2160p', '1440p', '1080p' incluso en videos ultrawide 21:9."""
        w = fmt.get("width") or 0
        h = fmt.get("height") or 0
        long_side = max(w, h)
        if long_side >= 3500 or h >= 2000:
            return "2160p 4K"
        if long_side >= 2400 or h >= 1350:
            return "1440p 2K"
        if long_side >= 1800 or h >= 1000:
            return "1080p"
        if long_side >= 1200 or h >= 680:
            return "720p"
        if long_side >= 800 or h >= 450:
            return "480p"
        if h > 0:
            return f"{h}p"
        return "Auto"

    def _set_size_label(self, text: str):
        """Actualiza la etiqueta de peso estimado de forma segura desde cualquier hilo."""
        if threading.current_thread() is threading.main_thread():
            self.size_estimate_label.configure(text=text)
        else:
            self.after(0, lambda: self.size_estimate_label.configure(text=text))

    def _recalculate_realtime_size(self):
        """
        Selecciona exactamente el mismo flujo (format_id) que se descargará y muestra su peso real.
        Al bloquear 'self.locked_format_id', el peso mostrado en pantalla coincide con el archivo final.
        En modo Lista de Reproducción, calcula el conteo y peso de los elementos marcados en el checklist.
        """
        self.locked_format_id = None
        selected_format = self.format_combobox.get()
        selected_quality = self.quality_combobox.get()

        if self.is_playlist_mode:
            total_items = len(self.playlist_vars)
            checked_rows = [
                (entry, fmt_cb.get(), qual_cb.get())
                for var, entry, fmt_cb, qual_cb in self.playlist_vars
                if var.get()
            ]
            checked_count = len(checked_rows)

            self.playlist_header_label.configure(
                text=f"Lista de reproducción ({checked_count} de {total_items} seleccionados):"
            )
            if not self.is_busy:
                if checked_count > 0:
                    self.download_btn.configure(text=f"DESCARGAR SELECCIONADOS ({checked_count})")
                else:
                    self.download_btn.configure(text="SELECCIONA AL MENOS 1 ELEMENTO")

            if checked_count == 0:
                self._set_size_label("Peso estimado: 0 seleccionados")
                return

            video_rows = [(e, q) for e, f, q in checked_rows if f == self.FORMAT_VIDEO]
            audio_rows = [(e, q) for e, f, q in checked_rows if f == self.FORMAT_AUDIO]
            v_count = len(video_rows)
            a_count = len(audio_rows)

            total_audio_bytes = 0
            for e, q in audio_rows:
                dur = float(e.get("duration") or 0)
                if dur > 0:
                    kbps = self.AUDIO_QUALITIES.get(q, 320)
                    total_audio_bytes += int((kbps * 1000.0 / 8.0) * dur)

            if v_count > 0 and a_count > 0:
                if total_audio_bytes > 0:
                    self._set_size_label(
                        f"Seleccionados: {v_count} MP4 + {a_count} MP3 ({format_bytes(total_audio_bytes, is_exact=True)} audio)"
                    )
                else:
                    self._set_size_label(f"Seleccionados: {v_count} MP4 + {a_count} MP3")
            elif a_count > 0:
                if total_audio_bytes > 0:
                    self._set_size_label(
                        f"Peso total ({a_count} MP3): {format_bytes(total_audio_bytes, is_exact=True)}"
                    )
                else:
                    self._set_size_label(f"Seleccionados: {a_count} pistas MP3")
            else:
                unique_qs = {q.split("(")[0].strip() for _e, q in video_rows}
                q_tag = next(iter(unique_qs)) if len(unique_qs) == 1 else "Calidades individuales"
                self._set_size_label(f"Seleccionados: {v_count} videos MP4 ({q_tag})")
            return

        if selected_format == self.FORMAT_IMAGE_GIF:
            self._set_size_label("Peso estimado: No aplica en Imagen / GIF")
            return

        if not self.analyzed_info:
            self._set_size_label("Peso estimado: Pega un enlace")
            return

        info = self.analyzed_info
        duration = info.get("duration")
        formats = info.get("formats") or []

        # Caso 1: Audio MP3 -> el archivo final se codifica al bitrate CBR elegido (320, 256, 192 o 128 kbps)
        if selected_format == self.FORMAT_AUDIO:
            kbps = self.AUDIO_QUALITIES.get(selected_quality, 320)
            if duration and duration > 0:
                audio_bytes = int((kbps * 1000.0 / 8.0) * float(duration))
                self._set_size_label(
                    f"Peso final ({kbps} kbps): {format_bytes(audio_bytes, is_exact=True)}"
                )
            else:
                audio_streams = [f for f in formats if f.get("acodec") != "none"]
                best_a_size = max((self._stream_bytes(f, None) for f in audio_streams), default=0)
                self._set_size_label(
                    f"Peso estimado ({kbps} kbps): {format_bytes(best_a_size)}"
                )
            return

        # Caso 2: Video MP4 -> elegir el flujo exacto y fijar su format_id para que la descarga baje ese mismo flujo
        locked_id, best_v, total_bytes, is_exact = self._select_optimal_video_format(
            info, selected_quality, self.analyzed_url or ""
        )
        if not best_v:
            fallback_total = info.get("filesize") or info.get("filesize_approx")
            self._set_size_label(f"Peso estimado: {format_bytes(fallback_total)}")
            return

        self.locked_format_id = locked_id
        res_tag = self._resolution_label(best_v)
        label_prefix = "Peso exacto" if is_exact else "Peso estimado"
        self._set_size_label(
            f"{label_prefix} ({res_tag}): {format_bytes(total_bytes, is_exact=is_exact)}"
        )

    def _select_optimal_video_format(
        self, info: dict, selected_quality: str, url_hint: str = ""
    ) -> tuple[str | None, dict | None, int, bool]:
        """
        Selecciona de forma thread-safe (sin leer widgets Qt) el format_id óptimo para Video MP4,
        aplicando priorización HLS (m3u8) en videos de X/Twitter mayores a 900 MB.
        Devuelve: (locked_format_id, best_v_dict, total_bytes, is_exact)
        """
        duration = info.get("duration")
        formats = info.get("formats") or []
        tier_bounds = self.VIDEO_QUALITIES.get(selected_quality)
        all_video = [f for f in formats if self._has_video(f) and f.get("format_id")]

        tier_candidates = [f for f in all_video if self._fits_resolution_tier(f, tier_bounds)]
        if not tier_candidates:
            tier_candidates = all_video
        if not tier_candidates:
            return None, None, 0, False

        exact_candidates = [f for f in tier_candidates if self._has_exact_filesize(f)]
        pool = exact_candidates if exact_candidates else tier_candidates
        pool.sort(
            key=lambda f: (
                max(f.get("width") or 0, f.get("height") or 0),
                f.get("height") or 0,
                1 if f.get("acodec") != "none" else 0,
                1 if f.get("ext") == "mp4" else 0,
                self._stream_bytes(f, duration),
            ),
            reverse=True,
        )
        best_v = pool[0]
        v_id = str(best_v.get("format_id"))
        v_bytes = self._stream_bytes(best_v, duration)

        # En X/Twitter, los archivos MP4 directos (http-*) > 900 MB suelen cortarse cerca de los 3 GB
        # y video.twimg.com agota el tiempo de espera al intentar reanudar con Range en offsets >= 1 GB.
        # Si hay un flujo HLS (m3u8) de igual resolución y FFmpeg está disponible, priorizar HLS por fragmentos.
        is_twitter_src = (
            "twitter" in str(info.get("extractor") or "").lower()
            or self._is_twitter_status_url(url_hint or info.get("webpage_url") or "")
        )
        if (
            is_twitter_src
            and self.ffmpeg_path
            and v_bytes > 900 * 1024 * 1024
            and "m3u8" not in str(best_v.get("protocol") or "")
        ):
            target_res = max(best_v.get("width") or 0, best_v.get("height") or 0)
            hls_candidates = [
                f for f in tier_candidates
                if "m3u8" in str(f.get("protocol") or "")
                and max(f.get("width") or 0, f.get("height") or 0) >= target_res
            ]
            if hls_candidates:
                hls_candidates.sort(
                    key=lambda f: (
                        max(f.get("width") or 0, f.get("height") or 0),
                        f.get("tbr") or 0,
                    ),
                    reverse=True,
                )
                best_v = hls_candidates[0]
                v_id = str(best_v.get("format_id"))
                v_bytes = self._stream_bytes(best_v, duration)

        is_exact = bool(best_v.get("filesize")) and "m3u8" not in str(best_v.get("protocol") or "")
        a_bytes = 0
        if best_v.get("acodec") == "none" and self.ffmpeg_path:
            audio_only = [f for f in formats if self._is_audio_only(f) and f.get("format_id")]
            exact_audio = [f for f in audio_only if self._has_exact_filesize(f)]
            audio_pool = exact_audio if exact_audio else audio_only
            if audio_pool:
                audio_pool.sort(
                    key=lambda f: (
                        1 if f.get("ext") in ("m4a", "mp4") else 0,
                        f.get("abr") or f.get("tbr") or 0,
                        self._stream_bytes(f, duration),
                    ),
                    reverse=True,
                )
                best_a = audio_pool[0]
                a_id = str(best_a.get("format_id"))
                a_bytes = self._stream_bytes(best_a, duration)
                locked_id = f"{v_id}+{a_id}"
                is_exact = is_exact and bool(best_a.get("filesize"))
            else:
                locked_id = f"{v_id}+bestaudio/{v_id}"
                is_exact = False
        else:
            locked_id = v_id

        return locked_id, best_v, v_bytes + a_bytes, is_exact

    # -------------------------------------------------------------------------
    # UTILIDADES DE INTERFAZ Y THREAD-SAFETY
    # -------------------------------------------------------------------------
    def _change_appearance_mode(self, mode_str: str):
        mapping = {"Oscuro": "dark", "Claro": "light", "Sistema": "system"}
        ctk.set_appearance_mode(mapping.get(mode_str, "dark"))
        if self.user_config.get("theme") != mode_str:
            self.user_config["theme"] = mode_str
            self._save_user_config()

    def _select_download_folder(self):
        selected = ctk.ask_directory(initialdir=self.download_dir, title="Seleccionar carpeta de descarga")
        if selected:
            self.download_dir = str(Path(selected))
            self.path_label.configure(text=f"Guardar en: {self.download_dir}")
            self.clip_path_label.configure(text=f"Guardar en: {self.download_dir}")
            self._append_log(f"Carpeta de destino actualizada: {self.download_dir}")
            self.user_config["download_dir"] = self.download_dir
            self._save_user_config()

    def _open_download_folder(self):
        os.makedirs(self.download_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(self.download_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", self.download_dir])
        else:
            subprocess.Popen(["xdg-open", self.download_dir])

    def _append_log(self, message: str):
        def _write():
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", f"{message}\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")

        self.after(0, _write)

    def _update_status(
        self,
        status_text: str,
        progress: float | None = None,
        percent_text: str | None = None,
        throttle: bool = False,
    ):
        # Throttling a ~16 FPS (60 ms) en actualizaciones intermedias para evitar saturar el hilo de UI
        if throttle and progress is not None and 0.0 < progress < 0.99:
            now = time.monotonic()
            if (now - self._last_progress_ui_time) < 0.06:
                return
            self._last_progress_ui_time = now

        def _apply():
            self.status_label.configure(text=f"Estado: {status_text}")
            if progress is not None:
                clamped = max(0.0, min(1.0, progress))
                self.progress_bar.set(clamped)
            if percent_text is not None:
                self.percent_label.configure(text=percent_text)

        self.after(0, _apply)

    def _set_ui_busy(self, busy: bool, action_text: str = "PROCESANDO DESCARGA..."):
        def _toggle():
            self.is_busy = busy
            if busy:
                self.download_btn.configure(state="disabled", text=action_text)
                self.clip_download_btn.configure(state="disabled", text=action_text)
                self.check_update_btn.configure(state="disabled")
                self.update_api_btn.configure(state="disabled")
                self.analyze_btn.configure(state="disabled")
                self.clip_analyze_btn.configure(state="disabled")
                self.url_entry.configure(state="disabled")
                self.clip_url_entry.configure(state="disabled")
                self.format_combobox.configure(state="disabled")
                self.quality_combobox.configure(state="disabled")
                self.clip_format_combobox.configure(state="disabled")
                self.clip_quality_combobox.configure(state="disabled")
                self.clip_start_entry.configure(state="disabled")
                self.clip_end_entry.configure(state="disabled")
                self.clip_start_slider.configure(state="disabled")
                self.clip_end_slider.configure(state="disabled")
                self.select_all_btn.configure(state="disabled")
                self.deselect_all_btn.configure(state="disabled")
                for _var, _entry, fmt_cb, qual_cb in self.playlist_vars:
                    fmt_cb.configure(state="disabled")
                    qual_cb.configure(state="disabled")
            else:
                if self.is_playlist_mode:
                    checked_count = sum(1 for var, _entry, _fmt_cb, _qual_cb in self.playlist_vars if var.get())
                    btn_text = (
                        f"DESCARGAR SELECCIONADOS ({checked_count})"
                        if checked_count > 0
                        else "SELECCIONA AL MENOS 1 ELEMENTO"
                    )
                else:
                    btn_text = "INICIAR DESCARGA"
                self.download_btn.configure(state="normal", text=btn_text)
                self.clip_download_btn.configure(state="normal", text="RECORTAR Y DESCARGAR FRAGMENTO")
                self.check_update_btn.configure(state="normal")
                self.update_api_btn.configure(state="normal")
                self.analyze_btn.configure(state="normal")
                self.clip_analyze_btn.configure(state="normal")
                self.url_entry.configure(state="normal")
                self.clip_url_entry.configure(state="normal")
                self.format_combobox.configure(state="readonly")
                self.clip_format_combobox.configure(state="readonly")
                self.clip_quality_combobox.configure(state="readonly")
                self.clip_start_entry.configure(state="normal")
                self.clip_end_entry.configure(state="normal")
                self.clip_start_slider.configure(state="normal")
                self.clip_end_slider.configure(state="normal")
                self.select_all_btn.configure(state="normal")
                self.deselect_all_btn.configure(state="normal")
                for _var, _entry, fmt_cb, qual_cb in self.playlist_vars:
                    fmt_cb.configure(state="readonly")
                    qual_cb.configure(state="readonly")
                if self.format_combobox.get() != self.FORMAT_IMAGE_GIF:
                    self.quality_combobox.configure(state="readonly")

        self.after(0, _toggle)

    # -------------------------------------------------------------------------
    # SISTEMA DE CONSULTA Y ACTUALIZACIÓN DE API
    # -------------------------------------------------------------------------
    def _detect_local_engine_version(self) -> str:
        bundled_ver = yt_dlp.version.__version__
        if self.external_ytdlp_path.is_file():
            try:
                current_mtime = round(self.external_ytdlp_path.stat().st_mtime, 2)
                cached_mtime = self.user_config.get("ext_engine_mtime")
                cached_ver = self.user_config.get("ext_engine_version")

                # Evitar lanzar subproceso 'yt-dlp.exe --version' (~2s) en cada inicio si el binario no cambió
                if cached_ver and cached_mtime == current_mtime:
                    ext_ver = str(cached_ver)
                else:
                    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    res = subprocess.run(
                        [str(self.external_ytdlp_path), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=8,
                        creationflags=creation_flags,
                    )
                    ext_ver = res.stdout.strip() if (res.returncode == 0 and res.stdout.strip()) else ""
                    if ext_ver:
                        self.user_config["ext_engine_mtime"] = current_mtime
                        self.user_config["ext_engine_version"] = ext_ver
                        self._save_user_config()

                if ext_ver and normalize_version(ext_ver) > normalize_version(bundled_ver):
                    self.use_external_engine = True
                    self.current_engine_version = ext_ver
                    return ext_ver
            except Exception:
                pass

        self.use_external_engine = False
        self.current_engine_version = bundled_ver
        return bundled_ver

    def _fetch_latest_remote_version(self) -> str | None:
        try:
            req = urllib.request.Request(
                self.YTDLP_RELEASE_API,
                headers={"User-Agent": f"UniversalDownloader/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name", "").strip()
                if tag:
                    return tag
        except Exception:
            pass

        try:
            req = urllib.request.Request(
                self.YTDLP_PYPI_API,
                headers={"User-Agent": f"UniversalDownloader/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ver = data.get("info", {}).get("version", "").strip()
                if ver:
                    return ver
        except Exception:
            pass

        return None

    def _init_and_check_updates(self, silent_startup: bool = False):
        local_ver = self._detect_local_engine_version()
        engine_type = "Externo actualizado" if self.use_external_engine else "Integrado"
        self._append_log(f"Motor de extracción activo: v{local_ver} ({engine_type}).")

        if not silent_startup:
            self._update_status("Consultando última versión de la API en servidores oficiales...", 0.3, "...")

        latest_ver = self._fetch_latest_remote_version()
        if not latest_ver:
            if not silent_startup:
                self._update_status("No se pudo conectar al servidor de actualizaciones", 0.0, "0%")
                self._append_log("[AVISO] No fue posible consultar la versión remota (verifica tu conexión).")
            return

        if normalize_version(latest_ver) > normalize_version(local_ver):
            msg = f"¡Nueva actualización de API disponible! (Actual: {local_ver} -> Nueva: {latest_ver})"
            self._append_log(f"[ACTUALIZACIÓN] {msg}. Pulsa el botón 'Actualizar API' para instalarla.")
            self._update_status(msg, 0.0, "Update")
            self.after(
                0,
                lambda: self.update_api_btn.configure(
                    fg_color=("#1e824c", "#27ae60"),
                    hover_color=("#16663b", "#1e8449"),
                    text="¡Actualizar API!",
                ),
            )
        else:
            msg = f"API de descargas al día (v{local_ver})"
            self._append_log(f"[OK] {msg}. No se requieren actualizaciones.")
            if not silent_startup:
                self._update_status(msg, 1.0, "Al día")

    def _on_check_update_clicked(self):
        if self.is_busy:
            return
        self._append_log("-" * 65)
        self._append_log("Consultando si existen nuevas actualizaciones del motor de descarga...")
        threading.Thread(target=self._init_and_check_updates, args=(False,), daemon=True).start()

    def _on_update_api_clicked(self):
        if self.is_busy:
            return
        self._set_ui_busy(True, "ACTUALIZANDO MOTOR API...")
        self._append_log("-" * 65)
        self._append_log("Iniciando actualización del motor de extracción (yt-dlp)...")
        self._update_status("Descargando última versión del motor de descargas...", 0.05, "5%")
        threading.Thread(target=self._run_update_api_task, daemon=True).start()

    def _run_update_api_task(self):
        temp_target = self.external_ytdlp_path.with_suffix(".tmp")
        try:
            req = urllib.request.Request(
                self.YTDLP_EXE_DOWNLOAD_URL,
                headers={"User-Agent": f"UniversalDownloader/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 256 * 1024

                with open(temp_target, "wb") as out_file:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            fraction = downloaded / total_size
                            pct = int(fraction * 100)
                            self._update_status(
                                "Descargando nuevo motor API desde GitHub...",
                                fraction,
                                f"{pct}%",
                                throttle=True,
                            )

            if temp_target.is_file() and temp_target.stat().st_size > 1_000_000:
                shutil.move(str(temp_target), str(self.external_ytdlp_path))

            if not getattr(sys, "frozen", False):
                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "gallery-dl", "--quiet"],
                    capture_output=True,
                    text=True,
                    timeout=35,
                    creationflags=creation_flags,
                )

            new_ver = self._detect_local_engine_version()
            self._update_status(f"¡API actualizada exitosamente a v{new_ver}!", 1.0, "100%")
            self._append_log(f"[ÉXITO] Motor actualizado correctamente a la versión {new_ver}.")
            self.after(
                0,
                lambda: self.update_api_btn.configure(
                    fg_color=("#1f6aa5", "#1f6aa5"),
                    hover_color=("#144870", "#144870"),
                    text="Actualizar API",
                ),
            )
        except Exception as exc:
            self._update_status("Error al actualizar la API (revisa el registro)", 0.0, "Error")
            self._append_log(f"[ERROR DE ACTUALIZACIÓN] No se pudo completar la descarga: {exc}")
        finally:
            if temp_target.is_file():
                try:
                    temp_target.unlink()
                except Exception:
                    pass
            self._set_ui_busy(False)

    # -------------------------------------------------------------------------
    # LÓGICA DE DESCARGA Y EXTRACCIÓN MULTIMEDIA (HILO SECUNDARIO)
    # -------------------------------------------------------------------------
    def _start_download_thread(self):
        if self.is_busy:
            return

        url = self.url_entry.get().strip()
        if not url or not url.startswith(("http://", "https://")):
            self._update_status("Introduce una URL válida (http:// o https://)", 0.0, "0%")
            self._append_log("[ERROR] La URL ingresada está vacía o no tiene un formato válido.")
            return

        selected_format = self.format_combobox.get()
        selected_quality = self.quality_combobox.get()

        # Modo Lista de Reproducción: descargar únicamente los elementos marcados con su formato y calidad individual
        if self.is_playlist_mode and url == self.analyzed_url:
            checked_items = [
                (
                    str(entry.get("url") or ""),
                    str(entry.get("title") or "Elemento"),
                    fmt_cb.get(),
                    qual_cb.get(),
                )
                for var, entry, fmt_cb, qual_cb in self.playlist_vars
                if var.get() and entry.get("url")
            ]
            if not checked_items:
                self._update_status("Selecciona al menos un elemento de la lista para descargar", 0.0, "0%")
                self._append_log("[AVISO] No hay ningún elemento marcado en la lista de reproducción.")
                return

            total_sel = len(checked_items)
            self._set_ui_busy(True, f"DESCARGANDO LISTA (0/{total_sel})...")
            self._update_status(f"Iniciando descarga de {total_sel} elementos seleccionados...", 0.0, "0%")
            self._append_log("-" * 65)
            self._append_log(
                f"Iniciando descarga de lista: {total_sel} elementos seleccionados (formato y calidad individuales)"
            )

            worker = threading.Thread(
                target=self._run_playlist_download_task,
                args=(checked_items,),
                daemon=True,
            )
            worker.start()
            return

        locked_id = self.locked_format_id if (url == self.analyzed_url) else None

        self._set_ui_busy(True, "PROCESANDO DESCARGA...")
        self._update_status("Iniciando descarga...", 0.0, "0%")
        self._append_log("-" * 65)
        self._append_log(f"Iniciando descarga: {url}")
        self._append_log(f"Formato: {selected_format} | Calidad: {selected_quality}")
        if locked_id and selected_format == self.FORMAT_VIDEO:
            self._append_log(f"Flujo exacto seleccionado (ID): {locked_id}")

        worker = threading.Thread(
            target=self._run_download_task,
            args=(url, selected_format, selected_quality, locked_id),
            daemon=True,
        )
        worker.start()

    def _yt_dlp_progress_hook(self, d: dict):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            speed_str = clean_ansi(d.get("_speed_str", "N/A")).strip()
            eta_str = clean_ansi(d.get("_eta_str", "N/A")).strip()

            if total and total > 0:
                fraction = downloaded / total
                pct = int(fraction * 100)
                self._update_status(
                    f"Descargando ({format_bytes(total, is_exact=True)})... Velocidad: {speed_str} | ETA: {eta_str}",
                    fraction,
                    f"{pct}%",
                    throttle=True,
                )
            else:
                pct_raw = clean_ansi(d.get("_percent_str", "0%")).strip()
                self._update_status(
                    f"Descargando... Velocidad: {speed_str}",
                    None,
                    pct_raw,
                    throttle=True,
                )

        elif status == "finished":
            filename = os.path.basename(d.get("filename", "archivo"))
            self._append_log(f"Flujo descargado: {filename}. Procesando archivo final...")
            self._update_status("Procesando y empaquetando archivo final...", 0.95, "95%")

    def _get_video_format_selector(self, selected_quality: str, locked_id: str | None = None) -> str:
        """
        Si el usuario ya analizó el enlace, usa exactamente el mismo 'locked_id' que se calculó en pantalla.
        Si descargó sin analizar antes, aplica el filtro de resolución priorizando flujos HTTPS con tamaño conocido.
        """
        if locked_id:
            return f"{locked_id}/bestvideo+bestaudio/best"

        tier_bounds = self.VIDEO_QUALITIES.get(selected_quality)
        max_h = tier_bounds[0] if tier_bounds else None
        if self.ffmpeg_path:
            if max_h:
                return (
                    f"bestvideo[height<={max_h}][protocol^=http][ext=mp4]+bestaudio[protocol^=http][ext=m4a]/"
                    f"bestvideo[height<={max_h}][ext=mp4]+bestaudio[ext=m4a]/"
                    f"bestvideo[height<={max_h}]+bestaudio/"
                    f"best[height<={max_h}]/best"
                )
            return (
                "bestvideo[protocol^=http][ext=mp4]+bestaudio[protocol^=http][ext=m4a]/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            )
        else:
            if max_h:
                return f"best[height<={max_h}][ext=mp4]/best[height<={max_h}]/best"
            return "best[ext=mp4]/best"

    def _build_ydl_options(self, selected_format: str, selected_quality: str, locked_id: str | None) -> dict:
        os.makedirs(self.download_dir, exist_ok=True)
        output_template = os.path.join(self.download_dir, "%(title).120B [%(id)s].%(ext)s")

        opts = {
            "outtmpl": output_template,
            "noplaylist": True,
            "overwrites": True,
            "continuedl": True,
            "windowsfilenames": True,
            "retries": 25,
            "fragment_retries": 25,
            "socket_timeout": 30,
            "retry_sleep_functions": {
                "http": lambda n: min(2 ** n, 15),
                "fragment": lambda n: min(2 ** n, 15),
            },
            "concurrent_fragment_downloads": 4,
            "buffersize": 256 * 1024,
            "js_runtimes": YTDLP_JS_RUNTIMES,
            "remote_components": YTDLP_REMOTE_COMPONENTS,
            "progress_hooks": [self._yt_dlp_progress_hook],
            "logger": YtDlpLogger(self._append_log),
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            },
        }

        if self.ffmpeg_path:
            opts["ffmpeg_location"] = self.ffmpeg_path

        if selected_format == self.FORMAT_VIDEO:
            opts["format"] = self._get_video_format_selector(selected_quality, locked_id)
            if self.ffmpeg_path:
                opts["merge_output_format"] = "mp4"

        elif selected_format == self.FORMAT_AUDIO:
            kbps = self.AUDIO_QUALITIES.get(selected_quality, 320)
            opts["format"] = "bestaudio/best"
            if self.ffmpeg_path:
                opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": str(kbps),
                    }
                ]

        elif selected_format == self.FORMAT_IMAGE_GIF:
            opts["format"] = "best"

        return opts

    def _run_with_external_engine(
        self, url: str, selected_format: str, selected_quality: str, locked_id: str | None
    ) -> str | None:
        """Ejecuta la descarga usando el binario actualizado en AppData con el mismo format_id calculado."""
        os.makedirs(self.download_dir, exist_ok=True)
        output_template = os.path.join(self.download_dir, "%(title).120B [%(id)s].%(ext)s")

        before_snapshot = {
            str(p): p.stat().st_mtime
            for p in Path(self.download_dir).glob("*")
            if p.is_file()
        }

        cmd = [
            str(self.external_ytdlp_path),
            "--encoding",
            "utf-8",
            "--no-playlist",
            "--force-overwrites",
            "--continue",
            "--windows-filenames",
            "--retries",
            "25",
            "--fragment-retries",
            "25",
            "--socket-timeout",
            "30",
            "--retry-sleep",
            "http:exp=1:15",
            "--retry-sleep",
            "fragment:exp=1:15",
            "--concurrent-fragments",
            "4",
            "--buffer-size",
            "256K",
            "--newline",
            *YTDLP_CLI_JS_ARGS,
            "-o",
            output_template,
        ]

        if self.ffmpeg_path:
            cmd.extend(["--ffmpeg-location", self.ffmpeg_path])

        if selected_format == self.FORMAT_VIDEO:
            fmt_selector = self._get_video_format_selector(selected_quality, locked_id)
            cmd.extend(["-f", fmt_selector])
            if self.ffmpeg_path:
                cmd.extend(["--merge-output-format", "mp4"])
        elif selected_format == self.FORMAT_AUDIO:
            kbps = self.AUDIO_QUALITIES.get(selected_quality, 320)
            cmd.extend(["-f", "bestaudio/best"])
            if self.ffmpeg_path:
                cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", f"{kbps}K"])
        elif selected_format == self.FORMAT_IMAGE_GIF:
            cmd.extend(["-f", "best"])

        cmd.append(url)

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )

        last_file = None
        output_lines = []
        if proc.stdout:
            for raw_line in proc.stdout:
                line = clean_ansi(raw_line).strip()
                if not line:
                    continue
                output_lines.append(line)

                match = CLI_PROGRESS_RE.search(line)
                if match:
                    pct_float = float(match.group("pct"))
                    speed = match.group("speed")
                    eta = match.group("eta")
                    self._update_status(
                        f"Descargando... Velocidad: {speed} | Restante: {eta}",
                        pct_float / 100.0,
                        f"{int(pct_float)}%",
                        throttle=True,
                    )
                else:
                    self._append_log(f"[INFO] {line}")
                    if "Destination:" in line:
                        last_file = line.split("Destination:", 1)[1].strip()
                    elif "Merging formats into" in line:
                        last_file = line.split("Merging formats into", 1)[1].strip().strip('"')
                    elif "has already been downloaded" in line and "[download]" in line:
                        cand = line.split("[download]", 1)[1].split("has already been downloaded", 1)[0].strip()
                        if os.path.isfile(cand):
                            last_file = cand

        ret = proc.wait()
        if ret != 0:
            raise yt_dlp.utils.DownloadError("\n".join(output_lines[-5:]))

        if not last_file or not os.path.isfile(last_file):
            changed_files = [
                str(p)
                for p in Path(self.download_dir).glob("*")
                if p.is_file() and (str(p) not in before_snapshot or p.stat().st_mtime > before_snapshot[str(p)])
            ]
            if changed_files:
                changed_files.sort(key=lambda fp: os.path.getmtime(fp), reverse=True)
                last_file = changed_files[0]

        return last_file

    def _convert_video_to_gif(
        self, input_video_path: str, max_height: int | None = None, fps: int = 15
    ) -> str | None:
        if not self.ffmpeg_path or not os.path.isfile(input_video_path):
            return None

        base, _ = os.path.splitext(input_video_path)
        clean_base = base[:-8] if base.endswith(".gif_tmp") else base
        gif_path = f"{clean_base}.gif"
        self._append_log("Convirtiendo animación a formato .gif optimizado...")
        self._update_status("Generando archivo GIF animado...", 0.97, "97%")

        if max_height and max_height > 0:
            vf_filter = (
                f"fps={fps},scale=-2:'min({max_height},ih)':flags=lanczos,"
                "split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
                "[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
            )
        else:
            vf_filter = (
                f"fps={fps},split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
                "[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
            )

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-threads",
            "0",
            "-i",
            input_video_path,
            "-vf",
            vf_filter,
            "-loop",
            "0",
            gif_path,
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        if res.returncode == 0 and os.path.isfile(gif_path):
            # Eliminar el archivo .mp4 temporal y cualquier miniatura residual del primer fotograma
            try:
                os.remove(input_video_path)
            except Exception:
                pass
            for thumb_ext in (".jpg", ".jpeg", ".png", ".webp"):
                thumb_candidate = f"{base}{thumb_ext}"
                if os.path.isfile(thumb_candidate):
                    try:
                        os.remove(thumb_candidate)
                    except Exception:
                        pass
            return gif_path
        return None

    def _fallback_static_image_download(self, url: str) -> bool:
        try:
            self._append_log("Extrayendo imagen original de la publicación con motor de galerías...")
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--gallery-dl-worker", self.download_dir, url]
            else:
                cmd = [sys.executable, os.path.abspath(__file__), "--gallery-dl-worker", self.download_dir, url]

            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=creation_flags)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if line.strip():
                        self._append_log(f"[ARCHIVO] {line.strip()}")
                return True
        except Exception as exc:
            self._append_log(f"[AVISO] Respaldo de galería no disponible: {exc}")
        return False

    def _download_suno_media(self, url: str, selected_format: str, selected_quality: str) -> str:
        """Descarga directamente canciones, videos o portadas de Suno con barra de progreso en tiempo real."""
        if self.analyzed_url == url and self.analyzed_info and self.analyzed_info.get("suno_mp4_url"):
            info = self.analyzed_info
        else:
            info = self._extract_suno_info(url)
            self.analyzed_url = url
            self.analyzed_info = info

        os.makedirs(self.download_dir, exist_ok=True)
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", info.get("title") or "Cancion").strip(" .")[:110]
        song_id = info.get("id", "suno")
        base_name = f"{safe_title} [{song_id}]"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        }

        if selected_format == self.FORMAT_IMAGE_GIF:
            target_url = info["suno_img_url"]
            final_path = os.path.join(self.download_dir, f"{base_name}.jpg")
            temp_download_path = final_path + ".tmp"
        elif selected_format == self.FORMAT_VIDEO:
            target_url = info["suno_mp4_url"]
            final_path = os.path.join(self.download_dir, f"{base_name}.mp4")
            temp_download_path = final_path + ".tmp"
        else:
            final_path = os.path.join(self.download_dir, f"{base_name}.mp3")
            if self.ffmpeg_path:
                target_url = info["suno_mp4_url"]
                temp_download_path = final_path + ".tmp.mp4"
            else:
                target_url = f"https://cdn1.suno.ai/{song_id}.mp3"
                temp_download_path = final_path + ".tmp.mp3"

        self._append_log(f"[INFO] Pista detectada: {info.get('title')}")
        req = urllib.request.Request(target_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0)) or info.get("filesize") or 0
                downloaded = 0
                chunk_size = 256 * 1024
                with open(temp_download_path, "wb") as out_f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            scale = 0.90 if (selected_format == self.FORMAT_AUDIO and self.ffmpeg_path) else 0.98
                            frac = (downloaded / total) * scale
                            pct = int(frac * 100)
                            self._update_status(
                                f"Descargando ({format_bytes(total, is_exact=True)})...",
                                frac,
                                f"{pct}%",
                                throttle=True,
                            )

            if selected_format == self.FORMAT_AUDIO and self.ffmpeg_path:
                kbps = self.AUDIO_QUALITIES.get(selected_quality, 320)
                self._append_log(f"Convirtiendo pista de audio a MP3 ({kbps} kbps)...")
                self._update_status(f"Codificando archivo MP3 a {kbps} kbps...", 0.95, "95%")
                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                cmd = [
                    self.ffmpeg_path,
                    "-y",
                    "-threads",
                    "0",
                    "-i",
                    temp_download_path,
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    f"{kbps}k",
                    final_path,
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creation_flags)
                if res.returncode != 0 or not os.path.isfile(final_path):
                    raise yt_dlp.utils.DownloadError("Error al convertir el audio a MP3 con FFmpeg.")
            else:
                shutil.move(temp_download_path, final_path)
        finally:
            if os.path.isfile(temp_download_path):
                try:
                    os.remove(temp_download_path)
                except Exception:
                    pass

        return final_path

    def _execute_single_url_download(
        self,
        url: str,
        selected_format: str,
        selected_quality: str,
        locked_id: str | None = None,
        is_batch_item: bool = False,
    ) -> str | None:
        """Ejecuta la descarga completa de un único elemento multimedia y devuelve la ruta final."""
        if self._is_suno_url(url):
            downloaded_filepath = self._download_suno_media(url, selected_format, selected_quality)
            self._append_log(f"[ARCHIVO] Guardado como: {os.path.basename(downloaded_filepath)}")
            return downloaded_filepath

        if not is_batch_item and selected_format == self.FORMAT_VIDEO and not locked_id:
            try:
                probe_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "skip_download": True,
                    "js_runtimes": YTDLP_JS_RUNTIMES,
                    "remote_components": YTDLP_REMOTE_COMPONENTS,
                }
                with yt_dlp.YoutubeDL(probe_opts) as probe_ydl:
                    probe_info = probe_ydl.extract_info(url, download=False)
                    if probe_info:
                        if "entries" in probe_info and probe_info["entries"]:
                            entries_list = list(probe_info["entries"])
                            if entries_list:
                                probe_info = entries_list[0]
                        self._populate_missing_direct_filesizes(probe_info, probe_ydl)
                if probe_info:
                    self.analyzed_url = url
                    self.analyzed_info = probe_info
                    if self._is_twitter_gif_info(probe_info):
                        selected_format = self.FORMAT_IMAGE_GIF
                    else:
                        locked_id, best_v, total_bytes, is_exact = self._select_optimal_video_format(
                            probe_info, selected_quality, url
                        )
                        self.locked_format_id = locked_id
                        if best_v:
                            res_tag = self._resolution_label(best_v)
                            label_prefix = "Peso exacto" if is_exact else "Peso estimado"
                            self._set_size_label(
                                f"{label_prefix} ({res_tag}): {format_bytes(total_bytes, is_exact=is_exact)}"
                            )
                        if locked_id:
                            self._append_log(f"Flujo óptimo verificado automáticamente (ID): {locked_id}")
            except Exception:
                pass

        if not is_batch_item and self._is_twitter_gif_info(self.analyzed_info):
            selected_format = self.FORMAT_IMAGE_GIF

        downloaded_filepath = None
        is_tw_fb_cached = (
            not is_batch_item
            and self.analyzed_url == url
            and self.analyzed_info
            and self.analyzed_info.get("tw_direct_fallback")
        )
        if is_tw_fb_cached:
            downloaded_filepath = self._download_twitter_fallback(
                url, selected_format, selected_quality, locked_id, clip_range=None
            )
        else:
            primary_exc = None
            try:
                if self.use_external_engine and self.external_ytdlp_path.is_file():
                    downloaded_filepath = self._run_with_external_engine(
                        url, selected_format, selected_quality, locked_id
                    )
                else:
                    ydl_opts = self._build_ydl_options(selected_format, selected_quality, locked_id)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if info:
                            if "requested_downloads" in info and info["requested_downloads"]:
                                downloaded_filepath = info["requested_downloads"][0].get("filepath")
                            else:
                                downloaded_filepath = ydl.prepare_filename(info)
            except Exception as e:
                primary_exc = e

            if primary_exc is not None:
                err_txt = clean_ansi(str(primary_exc))
                if "429" in err_txt or "Too Many Requests" in err_txt:
                    raise yt_dlp.utils.DownloadError(
                        "El servidor limitó temporalmente las peticiones (HTTP 429: Too Many Requests). "
                        "Espera 1 o 2 minutos y vuelve a pulsar 'INICIAR DESCARGA' para reanudar desde donde quedó."
                    ) from None
                if self._is_twitter_status_url(url):
                    self._append_log("[AVISO] Falló la descarga principal de X/Twitter; intentando respaldo de CDN...")
                    try:
                        downloaded_filepath = self._download_twitter_fallback(
                            url, selected_format, selected_quality, locked_id, clip_range=None
                        )
                    except Exception as fb_exc:
                        if isinstance(fb_exc, yt_dlp.utils.DownloadError):
                            raise fb_exc
                        raise yt_dlp.utils.DownloadError(f"{primary_exc}\n{fb_exc}") from None
                else:
                    raise primary_exc

        if (
            selected_format == self.FORMAT_IMAGE_GIF
            and downloaded_filepath
            and os.path.isfile(downloaded_filepath)
        ):
            ext = os.path.splitext(downloaded_filepath)[1].lower()
            if ext in (".mp4", ".webm", ".mkv"):
                gif_created = self._convert_video_to_gif(downloaded_filepath)
                if gif_created:
                    downloaded_filepath = gif_created
                    self._append_log(f"GIF generado exitosamente: {os.path.basename(gif_created)}")

        return downloaded_filepath

    def _run_download_task(
        self, url: str, selected_format: str, selected_quality: str, locked_id: str | None
    ):
        try:
            self._execute_single_url_download(
                url, selected_format, selected_quality, locked_id, is_batch_item=False
            )
            self._update_status("¡Descarga completada con éxito!", 1.0, "100%")
            self._append_log("PROCESO FINALIZADO: Archivo guardado en la carpeta de descargas.")

        except yt_dlp.utils.DownloadError as dl_err:
            err_msg = clean_ansi(str(dl_err))
            if selected_format == self.FORMAT_IMAGE_GIF and self._fallback_static_image_download(url):
                self._update_status("¡Imagen descargada con éxito!", 1.0, "100%")
                self._append_log("PROCESO FINALIZADO: Imagen guardada en la carpeta de descargas.")
            else:
                self._update_status("Error durante la descarga (revisa el registro)", 0.0, "Error")
                self._append_log(f"[ERROR DE DESCARGA] {err_msg}")

        except Exception as exc:
            import traceback
            tb_str = traceback.format_exc()
            self._update_status("Ocurrió un error inesperado", 0.0, "Error")
            self._append_log(f"[ERROR CRÍTICO] {exc}")
            self._append_log(f"[DETALLES] {tb_str.strip()}")

        finally:
            self._set_ui_busy(False)

    def _run_playlist_download_task(
        self, checked_items: list[tuple[str, str, str, str]]
    ):
        """Descarga secuencialmente los elementos marcados con el formato (MP4/MP3) y calidad elegidos en su fila."""
        total = len(checked_items)
        ok_count = 0
        fail_count = 0
        try:
            for idx, (item_url, item_title, item_fmt, item_qual) in enumerate(checked_items, start=1):
                short_title = item_title[:38]
                short_qual = item_qual.split("(")[0].strip()
                self.after(
                    0,
                    lambda i=idx, t=total: self.download_btn.configure(
                        text=f"DESCARGANDO LISTA ({i}/{t})..."
                    ),
                )
                self._append_log(f"[{idx}/{total}] Descargando ({item_fmt} | {short_qual}): {item_title}")
                self._update_status(
                    f"[{idx}/{total}] ({item_fmt} {short_qual}) {short_title}...",
                    (idx - 1) / total,
                    f"{int(((idx - 1) / total) * 100)}%",
                )
                try:
                    self._execute_single_url_download(
                        item_url,
                        item_fmt,
                        item_qual,
                        locked_id=None,
                        is_batch_item=True,
                    )
                    ok_count += 1
                    self._append_log(f"[OK {idx}/{total}] Completado ({item_fmt}): {item_title}")
                except Exception as item_exc:
                    fail_count += 1
                    self._append_log(f"[ERROR {idx}/{total}] Falló '{item_title}': {clean_ansi(str(item_exc))}")

            if fail_count == 0:
                self._update_status(
                    f"¡Lista completada! ({ok_count}/{total} descargados con éxito)", 1.0, "100%"
                )
            else:
                self._update_status(
                    f"Lista finalizada: {ok_count} exitosos, {fail_count} con error", 1.0, "100%"
                )
            self._append_log(
                f"PROCESO DE LISTA FINALIZADO: {ok_count} de {total} archivos guardados en la carpeta de descargas."
            )
        finally:
            self._set_ui_busy(False)

    # -------------------------------------------------------------------------
    # MÓDULO INDEPENDIENTE: RECORTAR FRAGMENTO (CLIP MP4, MP3 Y GIF)
    # -------------------------------------------------------------------------
    def _on_tab_switched(self, selected_tab: str):
        """Alterna entre la pestaña de Descarga General/Listas y el Módulo de Recorte de Fragmentos."""
        if selected_tab == self.TAB_CLIP:
            self.main_tab_container.grid_remove()
            self.clip_tab_container.grid(row=2, column=0, padx=0, pady=0, sticky="ew")
        else:
            self.clip_tab_container.grid_remove()
            self.main_tab_container.grid(row=2, column=0, padx=0, pady=0, sticky="ew")

    def _on_clip_format_changed(self, selected_format: str):
        """Actualiza las opciones del selector de Calidad del módulo de recorte según MP4, MP3 o GIF."""
        self.clip_format_combobox.set(selected_format)
        if selected_format == self.FORMAT_VIDEO:
            q_vals = list(self.VIDEO_QUALITIES.keys())
        elif selected_format == self.FORMAT_AUDIO:
            q_vals = list(self.AUDIO_QUALITIES.keys())
        else:
            q_vals = list(self.GIF_QUALITIES.keys())

        self.clip_quality_combobox.configure(state="readonly", values=q_vals)
        self.clip_quality_combobox.set(q_vals[0])
        self._recalculate_clip_size_and_range()

    def _on_clip_quality_changed(self, selected_quality: str):
        self.clip_quality_combobox.set(selected_quality)
        self._recalculate_clip_size_and_range()

    def _on_clip_url_entry_changed(self, _event=None):
        if self._clip_url_debounce_id:
            try:
                self.after_cancel(self._clip_url_debounce_id)
            except Exception:
                pass
            self._clip_url_debounce_id = None

        url = self.clip_url_entry.get().strip()
        if url.startswith(("http://", "https://")) and url != self.clip_analyzed_url:
            self._clip_url_debounce_id = self.after(
                300, lambda: self._trigger_clip_url_analysis(force=False)
            )

    def _paste_to_clip_url(self):
        try:
            clip = self.clipboard_get().strip()
            if clip:
                if self._clip_url_debounce_id:
                    try:
                        self.after_cancel(self._clip_url_debounce_id)
                    except Exception:
                        pass
                    self._clip_url_debounce_id = None
                self.clip_url_entry.delete(0, "end")
                self.clip_url_entry.insert(0, clip)
                if clip.startswith(("http://", "https://")):
                    self._trigger_clip_url_analysis(force=True)
        except Exception:
            pass

    def _clear_clip_url(self):
        if self._clip_url_debounce_id:
            try:
                self.after_cancel(self._clip_url_debounce_id)
            except Exception:
                pass
            self._clip_url_debounce_id = None
        self.clip_url_entry.delete(0, "end")
        self.clip_analyzed_url = None
        self.clip_analyzed_info = None
        self.clip_locked_format_id = None
        self.clip_total_duration = 0.0
        self.clip_start_sec = 0.0
        self.clip_end_sec = 15.0

        self.clip_thumb_label.configure(image=self._placeholder_thumb)
        self.clip_title_label.configure(text="Ningún video cargado")
        self.clip_meta_label.configure(
            text="Pega un enlace y pulsa 'Cargar Video' para habilitar la línea de tiempo"
        )
        self.clip_preview_card.grid_remove()
        self.clip_media_info_label.configure(
            text="Pega un enlace para cargar la duración y elegir el fragmento"
        )

        self._clip_syncing_ui = True
        try:
            self.clip_start_slider.configure(from_=0.0, to=60.0)
            self.clip_end_slider.configure(from_=0.0, to=60.0)
            self.clip_start_slider.set(0.0)
            self.clip_end_slider.set(15.0)
            self.clip_start_entry.delete(0, "end")
            self.clip_start_entry.insert(0, "00:00")
            self.clip_end_entry.delete(0, "end")
            self.clip_end_entry.insert(0, "00:15")
        finally:
            self._clip_syncing_ui = False

        self.clip_range_summary_label.configure(
            text="Rango: 00:00 -> 00:15  (Duración del clip: 00:15)"
        )
        self.clip_size_estimate_label.configure(text="Peso del fragmento: Pega un enlace")

    def _trigger_clip_url_analysis(self, force: bool = False):
        url = self.clip_url_entry.get().strip()
        if not url or not url.startswith(("http://", "https://")):
            self.clip_size_estimate_label.configure(text="Peso del fragmento: Pega un enlace válido")
            return

        if not force and url == self.clip_analyzed_url and self.clip_analyzed_info is not None:
            self._recalculate_clip_size_and_range()
            return

        self._clip_analyze_generation += 1
        current_gen = self._clip_analyze_generation
        self.clip_analyzed_url = url
        self.clip_analyzed_info = None
        self.clip_locked_format_id = None

        self.clip_size_estimate_label.configure(text="Analizando duración y calidades del video...")
        self.clip_media_info_label.configure(text="Extrayendo información del video...")
        self.clip_analyze_btn.configure(state="disabled", text="Cargando...")

        threading.Thread(
            target=self._analyze_clip_url_worker,
            args=(url, current_gen),
            daemon=True,
        ).start()

    def _analyze_clip_url_worker(self, url: str, generation: int):
        try:
            with self._cache_lock:
                cached = self._url_info_cache.get(url)
            if cached is not None and not cached.get("_is_playlist"):
                if generation != self._clip_analyze_generation:
                    return
                self.after(0, lambda: self._apply_clip_analyzed_info_to_ui(cached))
                return

            if self._is_suno_url(url):
                info = self._extract_suno_info(url)
            else:
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "skip_download": True,
                    "js_runtimes": YTDLP_JS_RUNTIMES,
                    "remote_components": YTDLP_REMOTE_COMPONENTS,
                    "http_headers": {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        )
                    },
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info:
                            if "entries" in info and info["entries"]:
                                entries_list = [e for e in info["entries"] if e]
                                if entries_list:
                                    info = entries_list[0]
                            self._populate_missing_direct_filesizes(info, ydl)
                except Exception:
                    info = None
                    if self._is_twitter_status_url(url):
                        try:
                            info = self._extract_twitter_fallback_info(url)
                        except Exception:
                            info = None
                    if not info:
                        if self.use_external_engine and self.external_ytdlp_path.is_file():
                            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                            res = subprocess.run(
                                [
                                    str(self.external_ytdlp_path),
                                    "--dump-single-json",
                                    "--no-playlist",
                                    "--no-warnings",
                                    "--no-check-certificate",
                                    *YTDLP_CLI_JS_ARGS,
                                    url,
                                ],
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                timeout=25,
                                creationflags=creation_flags,
                            )
                            if res.returncode == 0 and res.stdout.strip():
                                info = json.loads(res.stdout.strip().splitlines()[-1])
                                self._populate_missing_direct_filesizes(info, None)
                            else:
                                raise
                        else:
                            raise

            if generation != self._clip_analyze_generation:
                return

            if not info:
                self.after(
                    0,
                    lambda: self.clip_size_estimate_label.configure(
                        text="Peso del fragmento: No disponible"
                    ),
                )
                return

            with self._cache_lock:
                if len(self._url_info_cache) >= 32:
                    oldest_key = next(iter(self._url_info_cache))
                    self._url_info_cache.pop(oldest_key, None)
                self._url_info_cache[url] = info

            self.after(0, lambda: self._apply_clip_analyzed_info_to_ui(info))

        except Exception:
            if generation != self._clip_analyze_generation:
                return
            self.after(
                0,
                lambda: self.clip_size_estimate_label.configure(
                    text="Peso del fragmento: No disponible para este enlace"
                ),
            )
            self.after(
                0,
                lambda: self.clip_media_info_label.configure(
                    text="No se pudo pre-analizar la duración del enlace"
                ),
            )
        finally:
            if generation == self._clip_analyze_generation and not self.is_busy:
                self.after(
                    0,
                    lambda: self.clip_analyze_btn.configure(state="normal", text="Cargar Video"),
                )

    def _apply_clip_analyzed_info_to_ui(self, info: dict):
        """Aplica la información del video analizado a los controles de recorte y línea de tiempo."""
        self.clip_analyzed_info = info
        title = (info.get("title") or "Video detectado").strip()
        short_title = title[:52] + ("..." if len(title) > 52 else "")
        duration = float(info.get("duration") or 0.0)
        self.clip_total_duration = duration

        uploader = (info.get("uploader") or info.get("channel") or info.get("extractor_key") or "").strip()
        dur_str = format_duration(duration)
        self.clip_title_label.configure(text=title[:85])

        meta_parts = []
        if uploader:
            meta_parts.append(uploader[:40])
        if dur_str:
            meta_parts.append(f"Duración total: {dur_str}")
        else:
            meta_parts.append("Duración variable (puedes escribir Inicio y Fin manualmente)")
        self.clip_meta_label.configure(text="  •  ".join(meta_parts))
        self.clip_media_info_label.configure(
            text=f"{short_title} ({dur_str})" if dur_str else short_title
        )
        self.clip_preview_card.grid()

        self._load_thumbnail_async(info, self._clip_analyze_generation, is_clip_tab=True)

        # Configurar el rango de tiempo (si el usuario ya escribió un rango válido dentro de la duración, conservarlo)
        max_slider = duration if duration > 0 else max(self.clip_end_sec, 300.0)
        default_end = duration if duration > 0 else 15.0
        has_custom_range = (
            (self.clip_start_sec > 0.0 or self.clip_end_sec not in (10.0, 15.0))
            and self.clip_end_sec > self.clip_start_sec
            and (duration <= 0 or self.clip_end_sec <= duration)
        )
        if not has_custom_range:
            self.clip_start_sec = 0.0
            self.clip_end_sec = max(1.0, default_end)

        self._clip_syncing_ui = True
        try:
            self.clip_start_slider.configure(from_=0.0, to=max(1.0, max_slider))
            self.clip_end_slider.configure(from_=0.0, to=max(1.0, max_slider))
            self.clip_start_slider.set(self.clip_start_sec)
            self.clip_end_slider.set(self.clip_end_sec)
            self.clip_start_entry.delete(0, "end")
            self.clip_start_entry.insert(0, format_timestamp_input(self.clip_start_sec))
            self.clip_end_entry.delete(0, "end")
            self.clip_end_entry.insert(0, format_timestamp_input(self.clip_end_sec))
        finally:
            self._clip_syncing_ui = False

        if self._is_twitter_gif_info(info):
            self.clip_format_combobox.set(self.FORMAT_IMAGE_GIF)
            self._on_clip_format_changed(self.FORMAT_IMAGE_GIF)
        else:
            self._recalculate_clip_size_and_range()

    def _on_clip_start_slider_moved(self, val: float):
        if self._clip_syncing_ui:
            return
        max_limit = self.clip_total_duration if self.clip_total_duration > 0 else float(self.clip_end_slider.cget("to"))
        min_gap = 0.5 if max_limit < 10 else 1.0
        new_start = round(float(val), 1) if max_limit < 10 else float(round(val))
        max_allowed_start = max(0.0, self.clip_end_sec - min_gap)

        clamped = False
        if new_start >= self.clip_end_sec:
            new_start = max_allowed_start
            clamped = True
        new_start = max(0.0, min(new_start, max_allowed_start))

        self._clip_syncing_ui = True
        try:
            self.clip_start_sec = new_start
            if clamped:
                self.clip_start_slider.set(self.clip_start_sec)
            self.clip_start_entry.delete(0, "end")
            self.clip_start_entry.insert(0, format_timestamp_input(self.clip_start_sec))
        finally:
            self._clip_syncing_ui = False

        self._recalculate_clip_size_and_range()

    def _on_clip_end_slider_moved(self, val: float):
        if self._clip_syncing_ui:
            return
        max_limit = self.clip_total_duration if self.clip_total_duration > 0 else float(self.clip_end_slider.cget("to"))
        min_gap = 0.5 if max_limit < 10 else 1.0
        new_end = round(float(val), 1) if max_limit < 10 else float(round(val))
        min_allowed_end = min(max_limit, self.clip_start_sec + min_gap)

        clamped = False
        if new_end <= self.clip_start_sec:
            new_end = min_allowed_end
            clamped = True
        new_end = max(min_allowed_end, min(new_end, max_limit))

        self._clip_syncing_ui = True
        try:
            self.clip_end_sec = new_end
            if clamped:
                self.clip_end_slider.set(self.clip_end_sec)
            self.clip_end_entry.delete(0, "end")
            self.clip_end_entry.insert(0, format_timestamp_input(self.clip_end_sec))
        finally:
            self._clip_syncing_ui = False

        self._recalculate_clip_size_and_range()

    def _on_clip_time_entry_edited(self, _event=None):
        """Sincroniza en vivo las barras deslizantes cuando el usuario escribe MM:SS o segundos."""
        if self._clip_syncing_ui:
            return
        parsed_start = parse_timestamp_input(self.clip_start_entry.get())
        parsed_end = parse_timestamp_input(self.clip_end_entry.get())
        if parsed_start is None and parsed_end is None:
            return

        if parsed_start is not None:
            if self.clip_total_duration > 0:
                parsed_start = max(0.0, min(parsed_start, max(0.0, self.clip_total_duration - 0.5)))
            self.clip_start_sec = parsed_start

        if parsed_end is not None:
            if self.clip_total_duration > 0:
                parsed_end = max(0.5, min(parsed_end, self.clip_total_duration))
            self.clip_end_sec = parsed_end

        if self.clip_end_sec <= self.clip_start_sec:
            return

        max_limit = (
            self.clip_total_duration
            if self.clip_total_duration > 0
            else max(self.clip_end_sec + 60.0, 300.0)
        )

        self._clip_syncing_ui = True
        try:
            if max_limit > float(self.clip_end_slider.cget("to")):
                self.clip_start_slider.configure(to=max_limit)
                self.clip_end_slider.configure(to=max_limit)
            self.clip_start_slider.set(self.clip_start_sec)
            self.clip_end_slider.set(self.clip_end_sec)
        finally:
            self._clip_syncing_ui = False

        self._recalculate_clip_size_and_range()

    def _on_clip_time_entry_focus_out(self, _event=None):
        """Normaliza los cuadros de texto al formato MM:SS / HH:MM:SS al pulsar Enter o salir del campo."""
        self._on_clip_time_entry_edited()
        max_limit = (
            self.clip_total_duration
            if self.clip_total_duration > 0
            else max(self.clip_start_sec + 60.0, self.clip_end_sec + 60.0, 300.0)
        )
        if self.clip_end_sec <= self.clip_start_sec:
            self.clip_end_sec = min(max_limit, self.clip_start_sec + 15.0)
            if self.clip_end_sec <= self.clip_start_sec:
                self.clip_start_sec = max(0.0, self.clip_end_sec - 1.0)

        self._clip_syncing_ui = True
        try:
            if max_limit > float(self.clip_end_slider.cget("to")):
                self.clip_start_slider.configure(to=max_limit)
                self.clip_end_slider.configure(to=max_limit)
            self.clip_start_entry.delete(0, "end")
            self.clip_start_entry.insert(0, format_timestamp_input(self.clip_start_sec))
            self.clip_end_entry.delete(0, "end")
            self.clip_end_entry.insert(0, format_timestamp_input(self.clip_end_sec))
            self.clip_start_slider.set(self.clip_start_sec)
            self.clip_end_slider.set(self.clip_end_sec)
        finally:
            self._clip_syncing_ui = False

        self._recalculate_clip_size_and_range()

    def _recalculate_clip_size_and_range(self):
        """Actualiza la etiqueta de rango/duración del clip y calcula el peso estimado del fragmento."""
        clip_dur = max(0.5, self.clip_end_sec - self.clip_start_sec)
        start_str = format_timestamp_input(self.clip_start_sec)
        end_str = format_timestamp_input(self.clip_end_sec)
        dur_str = format_duration(clip_dur) or "00:01"
        self.clip_range_summary_label.configure(
            text=f"Rango: {start_str} -> {end_str}  (Duración del clip: {dur_str})"
        )

        selected_format = self.clip_format_combobox.get()
        selected_quality = self.clip_quality_combobox.get()
        self.clip_locked_format_id = None

        # Caso 1: Audio MP3 -> peso exacto CBR según la duración del recorte
        if selected_format == self.FORMAT_AUDIO:
            kbps = self.AUDIO_QUALITIES.get(selected_quality, 320)
            audio_bytes = int((kbps * 1000.0 / 8.0) * float(clip_dur))
            self.clip_size_estimate_label.configure(
                text=f"Peso del clip MP3 ({kbps} kbps): {format_bytes(audio_bytes, is_exact=True)}"
            )
            return

        # Caso 2: Imagen / GIF -> muestra resolución/FPS del GIF y peso aproximado del clip
        if selected_format == self.FORMAT_IMAGE_GIF:
            max_h, fps = self.GIF_QUALITIES.get(selected_quality, (480, 15))
            res_label = f"{max_h}p" if max_h else "Original"
            self.clip_size_estimate_label.configure(
                text=f"Clip GIF ({res_label} • {fps} FPS) | Duración: {dur_str}"
            )
            return

        # Caso 3: Video MP4 -> calcular proporción respecto al flujo de video de la calidad seleccionada
        if not self.clip_analyzed_info:
            self.clip_size_estimate_label.configure(text="Peso del fragmento: Pega un enlace")
            return

        info = self.clip_analyzed_info
        full_duration = float(info.get("duration") or 0.0)
        ratio = min(1.0, max(0.01, clip_dur / full_duration)) if full_duration > 0 else 1.0

        locked_id, best_v, total_full_bytes, _is_exact = self._select_optimal_video_format(
            info, selected_quality, self.clip_analyzed_url or ""
        )
        if not best_v:
            fallback_total = info.get("filesize") or info.get("filesize_approx") or 0
            clip_bytes = int(fallback_total * ratio) if fallback_total else 0
            self.clip_size_estimate_label.configure(
                text=f"Peso estimado del clip: {format_bytes(clip_bytes, is_exact=False)}"
            )
            return

        self.clip_locked_format_id = locked_id
        clip_bytes = int(total_full_bytes * ratio)
        res_tag = self._resolution_label(best_v)
        self.clip_size_estimate_label.configure(
            text=f"Peso estimado del clip ({res_tag}): {format_bytes(clip_bytes, is_exact=False)}"
        )

    def _start_clip_download_thread(self):
        if self.is_busy:
            return

        url = self.clip_url_entry.get().strip()
        if not url or not url.startswith(("http://", "https://")):
            self._update_status("Introduce una URL válida en la pestaña de recorte", 0.0, "0%")
            self._append_log("[ERROR] La URL del módulo de recorte está vacía o no es válida.")
            return

        self._on_clip_time_entry_focus_out()
        start_sec = float(self.clip_start_sec)
        end_sec = float(self.clip_end_sec)
        if end_sec <= start_sec:
            self._update_status("El tiempo de Fin debe ser mayor al tiempo de Inicio", 0.0, "0%")
            self._append_log("[ERROR] Rango de recorte inválido: Fin debe ser mayor que Inicio.")
            return

        selected_format = self.clip_format_combobox.get()
        selected_quality = self.clip_quality_combobox.get()
        locked_id = self.clip_locked_format_id if (url == self.clip_analyzed_url) else None

        range_tag = f"{format_timestamp_input(start_sec)} -> {format_timestamp_input(end_sec)}"
        self._set_ui_busy(True, "RECORTANDO Y DESCARGANDO...")
        self._update_status(f"Recortando fragmento ({range_tag})...", 0.05, "5%")
        self._append_log("-" * 65)
        self._append_log(f"Iniciando recorte de fragmento: {url}")
        self._append_log(
            f"Segmento: {range_tag} | Formato: {selected_format} | Calidad: {selected_quality}"
        )

        worker = threading.Thread(
            target=self._run_clip_download_task,
            args=(url, start_sec, end_sec, selected_format, selected_quality, locked_id),
            daemon=True,
        )
        worker.start()

    def _trim_local_media_with_ffmpeg(
        self,
        input_path: str,
        output_path: str,
        start_sec: float,
        end_sec: float,
        selected_format: str,
        selected_quality: str,
    ) -> str:
        """Recorta un archivo multimedia local con FFmpeg al segmento exacto [start_sec, end_sec]."""
        if not self.ffmpeg_path:
            raise yt_dlp.utils.DownloadError("FFmpeg es necesario para recortar fragmentos.")

        duration = max(0.5, end_sec - start_sec)
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss",
            f"{start_sec:.2f}",
            "-i",
            input_path,
            "-t",
            f"{duration:.2f}",
        ]
        if selected_format == self.FORMAT_AUDIO:
            kbps = self.AUDIO_QUALITIES.get(selected_quality, 320)
            cmd.extend(["-vn", "-acodec", "libmp3lame", "-b:a", f"{kbps}k", output_path])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", output_path])

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        if res.returncode != 0 or not os.path.isfile(output_path):
            raise yt_dlp.utils.DownloadError("No se pudo recortar el segmento con FFmpeg.")
        return output_path

    def _run_clip_with_external_engine(
        self,
        url: str,
        start_sec: float,
        end_sec: float,
        dl_format: str,
        dl_quality: str,
        locked_id: str | None,
        output_template: str,
    ) -> str | None:
        """Ejecuta el recorte de fragmento usando el motor externo actualizado yt-dlp.exe."""
        os.makedirs(self.download_dir, exist_ok=True)
        before_snapshot = {
            str(p): p.stat().st_mtime
            for p in Path(self.download_dir).glob("*")
            if p.is_file()
        }

        cmd = [
            str(self.external_ytdlp_path),
            "--encoding",
            "utf-8",
            "--no-playlist",
            "--force-overwrites",
            "--windows-filenames",
            "--retries",
            "25",
            "--fragment-retries",
            "25",
            "--socket-timeout",
            "30",
            "--retry-sleep",
            "http:exp=1:15",
            "--retry-sleep",
            "fragment:exp=1:15",
            "--concurrent-fragments",
            "4",
            "--buffer-size",
            "256K",
            "--newline",
            *YTDLP_CLI_JS_ARGS,
            "--download-sections",
            f"*{start_sec:.2f}-{end_sec:.2f}",
            "--force-keyframes-at-cuts",
            "-o",
            output_template,
        ]

        if self.ffmpeg_path:
            cmd.extend(["--ffmpeg-location", self.ffmpeg_path])

        if dl_format == self.FORMAT_VIDEO:
            fmt_selector = self._get_video_format_selector(dl_quality, locked_id)
            cmd.extend(["-f", fmt_selector])
            if self.ffmpeg_path:
                cmd.extend(["--merge-output-format", "mp4"])
        elif dl_format == self.FORMAT_AUDIO:
            kbps = self.AUDIO_QUALITIES.get(dl_quality, 320)
            cmd.extend(["-f", "bestaudio/best"])
            if self.ffmpeg_path:
                cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", f"{kbps}K"])

        cmd.append(url)

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )

        last_file = None
        output_lines = []
        if proc.stdout:
            for raw_line in proc.stdout:
                line = clean_ansi(raw_line).strip()
                if not line:
                    continue
                output_lines.append(line)

                match = CLI_PROGRESS_RE.search(line)
                if match:
                    pct_float = float(match.group("pct"))
                    speed = match.group("speed")
                    eta = match.group("eta")
                    self._update_status(
                        f"Recortando... Velocidad: {speed} | Restante: {eta}",
                        pct_float / 100.0,
                        f"{int(pct_float)}%",
                        throttle=True,
                    )
                else:
                    self._append_log(f"[INFO] {line}")
                    if "Destination:" in line:
                        last_file = line.split("Destination:", 1)[1].strip()
                    elif "Merging formats into" in line:
                        last_file = line.split("Merging formats into", 1)[1].strip().strip('"')

        ret = proc.wait()
        if ret != 0:
            raise yt_dlp.utils.DownloadError("\n".join(output_lines[-5:]))

        if not last_file or not os.path.isfile(last_file):
            changed_files = [
                str(p)
                for p in Path(self.download_dir).glob("*")
                if p.is_file() and (str(p) not in before_snapshot or p.stat().st_mtime > before_snapshot[str(p)])
            ]
            if changed_files:
                changed_files.sort(key=lambda fp: os.path.getmtime(fp), reverse=True)
                last_file = changed_files[0]

        return last_file

    def _run_clip_download_task(
        self,
        url: str,
        start_sec: float,
        end_sec: float,
        selected_format: str,
        selected_quality: str,
        locked_id: str | None,
    ):
        try:
            os.makedirs(self.download_dir, exist_ok=True)
            tag_start = format_timestamp_input(start_sec).replace(":", "m") + "s"
            tag_end = format_timestamp_input(end_sec).replace(":", "m") + "s"
            clip_tag = f"Clip {tag_start}-{tag_end}"

            # Para GIF animado descargamos primero el fragmento de video MP4 y luego lo convertimos a .gif
            dl_format = (
                self.FORMAT_VIDEO if selected_format == self.FORMAT_IMAGE_GIF else selected_format
            )
            dl_quality = (
                "720p (HD)" if selected_format == self.FORMAT_IMAGE_GIF else selected_quality
            )

            downloaded_filepath = None

            if self._is_suno_url(url):
                raw_path = self._download_suno_media(url, dl_format, dl_quality)
                base, ext = os.path.splitext(raw_path)
                if selected_format == self.FORMAT_AUDIO:
                    clipped_ext = ".mp3"
                elif selected_format == self.FORMAT_IMAGE_GIF:
                    clipped_ext = ".gif_tmp.mp4"
                else:
                    clipped_ext = ".mp4"
                clipped_path = f"{base} [{clip_tag}]{clipped_ext}"
                self._update_status("Recortando segmento exacto con FFmpeg...", 0.92, "92%")
                downloaded_filepath = self._trim_local_media_with_ffmpeg(
                    raw_path, clipped_path, start_sec, end_sec, dl_format, dl_quality
                )
                try:
                    if os.path.isfile(raw_path) and raw_path != downloaded_filepath:
                        os.remove(raw_path)
                except Exception:
                    pass
            else:
                is_tw_fb_cached = (
                    self.clip_analyzed_url == url
                    and self.clip_analyzed_info
                    and self.clip_analyzed_info.get("tw_direct_fallback")
                )
                if is_tw_fb_cached:
                    downloaded_filepath = self._download_twitter_fallback(
                        url,
                        selected_format,
                        dl_quality,
                        locked_id,
                        clip_range=(start_sec, end_sec),
                    )
                else:
                    if selected_format == self.FORMAT_IMAGE_GIF:
                        tmp_suffix = ".gif_tmp"
                    elif selected_format == self.FORMAT_AUDIO:
                        tmp_suffix = ".audio_tmp"
                    else:
                        tmp_suffix = ""

                    output_template = os.path.join(
                        self.download_dir, f"%(title).100B [%(id)s] [{clip_tag}]{tmp_suffix}.%(ext)s"
                    )
                    ydl_opts = self._build_ydl_options(
                        dl_format,
                        dl_quality,
                        locked_id if dl_format == self.FORMAT_VIDEO else None,
                    )
                    ydl_opts["outtmpl"] = output_template
                    ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(
                        None, [(start_sec, end_sec)]
                    )
                    ydl_opts["force_keyframes_at_cuts"] = True
                    ydl_opts["external_downloader_args"] = {"ffmpeg": ["-loglevel", "error"]}

                    clip_primary_exc = None
                    try:
                        if self.use_external_engine and self.external_ytdlp_path.is_file():
                            downloaded_filepath = self._run_clip_with_external_engine(
                                url,
                                start_sec,
                                end_sec,
                                dl_format,
                                dl_quality,
                                locked_id if dl_format == self.FORMAT_VIDEO else None,
                                output_template,
                            )
                        else:
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                info = ydl.extract_info(url, download=True)
                                if info:
                                    if "requested_downloads" in info and info["requested_downloads"]:
                                        downloaded_filepath = info["requested_downloads"][0].get("filepath")
                                    else:
                                        downloaded_filepath = ydl.prepare_filename(info)

                        if (
                            selected_format == self.FORMAT_AUDIO
                            and downloaded_filepath
                            and os.path.isfile(downloaded_filepath)
                            and ".audio_tmp." in downloaded_filepath
                        ):
                            clean_audio_path = downloaded_filepath.replace(".audio_tmp.", ".")
                            try:
                                os.replace(downloaded_filepath, clean_audio_path)
                                downloaded_filepath = clean_audio_path
                            except Exception:
                                pass
                    except Exception as e:
                        clip_primary_exc = e

                    if clip_primary_exc is not None:
                        if self._is_twitter_status_url(url):
                            try:
                                downloaded_filepath = self._download_twitter_fallback(
                                    url,
                                    selected_format,
                                    dl_quality,
                                    locked_id,
                                    clip_range=(start_sec, end_sec),
                                )
                            except Exception as fb_exc:
                                if isinstance(fb_exc, yt_dlp.utils.DownloadError):
                                    raise fb_exc
                                raise yt_dlp.utils.DownloadError(f"{clip_primary_exc}\n{fb_exc}") from None
                        else:
                            raise clip_primary_exc

            # Si el usuario eligió Imagen / GIF, convertir el fragmento recortado a .gif con la calidad/FPS elegida
            if (
                selected_format == self.FORMAT_IMAGE_GIF
                and downloaded_filepath
                and os.path.isfile(downloaded_filepath)
            ):
                max_h, fps = self.GIF_QUALITIES.get(selected_quality, (480, 15))
                gif_created = self._convert_video_to_gif(
                    downloaded_filepath, max_height=max_h, fps=fps
                )
                if gif_created:
                    downloaded_filepath = gif_created
                    self._append_log(
                        f"Fragmento GIF generado exitosamente: {os.path.basename(gif_created)}"
                    )

            if downloaded_filepath:
                self._append_log(
                    f"[ARCHIVO] Fragmento guardado: {os.path.basename(downloaded_filepath)}"
                )
            self._update_status("¡Fragmento recortado y descargado con éxito!", 1.0, "100%")
            self._append_log(
                "PROCESO FINALIZADO: El fragmento recortado se guardó en la carpeta de descargas."
            )

        except yt_dlp.utils.DownloadError as dl_err:
            err_msg = clean_ansi(str(dl_err))
            self._update_status("Error al recortar el fragmento (revisa el registro)", 0.0, "Error")
            self._append_log(f"[ERROR DE RECORTE] {err_msg}")
        except Exception as exc:
            import traceback
            tb_str = traceback.format_exc()
            self._update_status("Ocurrió un error inesperado al recortar", 0.0, "Error")
            self._append_log(f"[ERROR CRÍTICO] {exc}")
            self._append_log(f"[DETALLES] {tb_str.strip()}")
        finally:
            self._set_ui_busy(False)


def _run_gallery_dl_cli(dest_dir: str, target_url: str) -> int:
    """Modo interno invocado por subproceso para extraer imágenes fijas con gallery_dl."""
    import gallery_dl
    sys.argv = ["gallery-dl", "-d", dest_dir, target_url]
    try:
        return gallery_dl.main()
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--gallery-dl-worker":
        sys.exit(_run_gallery_dl_cli(sys.argv[2], sys.argv[3]))

    app = UniversalDownloaderApp()
    app.mainloop()
