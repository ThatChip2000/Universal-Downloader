"""
Motor gráfico nativo basado en PySide6 (Qt6 Widgets) para Universal Downloader.
Reemplaza por completo a CustomTkinter/Tkinter con controles nativos en C++ de alto rendimiento,
bajo consumo de CPU (< 0.5% al redimensionar) y diseño funcional y cómodo a la vista.
"""

from __future__ import annotations
import sys
from typing import Callable, Any
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QSignalBlocker, QSize, QPoint, QThread
from PySide6.QtGui import (
    QFont,
    QIcon,
    QImage,
    QPixmap,
    QPainter,
    QColor,
    QPen,
    QPolygon,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QSlider,
    QProgressBar,
    QPlainTextEdit,
    QCheckBox,
    QScrollArea,
    QFileDialog,
    QSizePolicy,
)

_CURRENT_THEME = "dark"

DARK_STYLESHEET = """
QMainWindow, QWidget#CentralRoot {
    background-color: #16181d;
    color: #e6edf3;
    font-family: "Segoe UI", sans-serif;
}
QFrame[card="true"] {
    background-color: #20242b;
    border: 1px solid #2e3440;
    border-radius: 8px;
}
QFrame[subcard="true"] {
    background-color: #1a1d23;
    border: 1px solid #2b303c;
    border-radius: 6px;
}
QFrame[transparent="true"], QWidget[transparent="true"] {
    background-color: transparent;
    border: none;
}
QLabel {
    background-color: transparent;
    color: #e6edf3;
    border: none;
}
QLineEdit {
    background-color: #14171c;
    color: #f0f6fc;
    border: 1px solid #373e4d;
    border-radius: 5px;
    padding: 4px 10px;
    selection-background-color: #1f6aa5;
}
QLineEdit:focus {
    border: 1px solid #388bfd;
}
QLineEdit:disabled {
    background-color: #1b1e24;
    color: #6e7681;
}
QPushButton {
    background-color: #2d333b;
    color: #ffffff;
    border: 1px solid #3d444d;
    border-radius: 5px;
    padding: 4px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #373e47;
    border-color: #484f58;
}
QPushButton:pressed {
    background-color: #22272e;
}
QPushButton:disabled {
    background-color: #21262d;
    color: #6e7681;
    border-color: #2d333b;
}
QComboBox {
    background-color: #16191f;
    color: #e6edf3;
    border: 1px solid #373e4d;
    border-radius: 5px;
    padding: 3px 10px;
}
QComboBox:hover {
    border-color: #58a6ff;
}
QComboBox:disabled {
    background-color: #1b1e24;
    color: #6e7681;
}
QComboBox QAbstractItemView {
    background-color: #20242b;
    color: #e6edf3;
    border: 1px solid #373e4d;
    selection-background-color: #1f6aa5;
    selection-color: #ffffff;
    outline: 0;
}
QSlider::groove:horizontal {
    border: 1px solid #2e3440;
    height: 6px;
    background: #14171c;
    margin: 0px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #1f6aa5;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #58a6ff;
    border: 1px solid #1f6aa5;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #79c0ff;
}
QProgressBar {
    background-color: #14171c;
    border: 1px solid #2e3440;
    border-radius: 6px;
}
QProgressBar::chunk {
    background-color: #1f6aa5;
    border-radius: 5px;
}
QPlainTextEdit {
    background-color: #121418;
    color: #d0d7de;
    border: 1px solid #2b303c;
    border-radius: 6px;
    padding: 6px;
    selection-background-color: #1f6aa5;
}
QScrollArea {
    background-color: #16191f;
    border: 1px solid #2b303c;
    border-radius: 6px;
}
QCheckBox {
    color: #e6edf3;
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #484f58;
    background-color: #14171c;
}
QCheckBox::indicator:checked {
    background-color: #1f6aa5;
    border-color: #388bfd;
}
QScrollBar:vertical {
    background: #16181d;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #373e4d;
    min-height: 24px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #484f58;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

LIGHT_STYLESHEET = """
QMainWindow, QWidget#CentralRoot {
    background-color: #f0f2f5;
    color: #1f2328;
    font-family: "Segoe UI", sans-serif;
}
QFrame[card="true"] {
    background-color: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 8px;
}
QFrame[subcard="true"] {
    background-color: #f6f8fa;
    border: 1px solid #d8dee4;
    border-radius: 6px;
}
QFrame[transparent="true"], QWidget[transparent="true"] {
    background-color: transparent;
    border: none;
}
QLabel {
    background-color: transparent;
    color: #1f2328;
    border: none;
}
QLineEdit {
    background-color: #ffffff;
    color: #1f2328;
    border: 1px solid #afb8c1;
    border-radius: 5px;
    padding: 4px 10px;
    selection-background-color: #0969da;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border: 1px solid #0969da;
}
QLineEdit:disabled {
    background-color: #eaeef2;
    color: #8c959f;
}
QPushButton {
    background-color: #1f6aa5;
    color: #ffffff;
    border: 1px solid #1b5c90;
    border-radius: 5px;
    padding: 4px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #185687;
}
QPushButton:pressed {
    background-color: #13446b;
}
QPushButton:disabled {
    background-color: #d0d7de;
    color: #8c959f;
    border-color: #afb8c1;
}
QComboBox {
    background-color: #ffffff;
    color: #1f2328;
    border: 1px solid #afb8c1;
    border-radius: 5px;
    padding: 3px 10px;
}
QComboBox:hover {
    border-color: #0969da;
}
QComboBox:disabled {
    background-color: #eaeef2;
    color: #8c959f;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1f2328;
    border: 1px solid #afb8c1;
    selection-background-color: #1f6aa5;
    selection-color: #ffffff;
    outline: 0;
}
QSlider::groove:horizontal {
    border: 1px solid #afb8c1;
    height: 6px;
    background: #d0d7de;
    margin: 0px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #1f6aa5;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #1f6aa5;
    border: 1px solid #13446b;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QProgressBar {
    background-color: #d8dee4;
    border: 1px solid #afb8c1;
    border-radius: 6px;
}
QProgressBar::chunk {
    background-color: #1f6aa5;
    border-radius: 5px;
}
QPlainTextEdit {
    background-color: #f6f8fa;
    color: #1f2328;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 6px;
}
QScrollArea {
    background-color: #f6f8fa;
    border: 1px solid #d0d7de;
    border-radius: 6px;
}
QCheckBox {
    color: #1f2328;
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #8c959f;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #1f6aa5;
    border-color: #1f6aa5;
}
QScrollBar:vertical {
    background: #f0f2f5;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #afb8c1;
    min-height: 24px;
    border-radius: 5px;
}
"""


def _ensure_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
    return app


def _resolve_color(color_spec: str | tuple[str, str] | None) -> str | None:
    if not color_spec:
        return None
    if isinstance(color_spec, (tuple, list)):
        val = color_spec[0] if _CURRENT_THEME == "light" else color_spec[1]
    else:
        val = str(color_spec)
    mapping = {
        "gray15": "#16191f",
        "gray16": "#181b21",
        "gray18": "#1c2026",
        "gray20": "#22272e",
        "gray28": "#2d333b",
        "gray35": "#484f58",
        "gray40": "#57606a",
        "gray65": "#8b949e",
        "gray70": "#9ca3af",
        "gray85": "#e1e4e8",
        "gray88": "#eaeef2",
        "gray90": "#f0f3f6",
    }
    return mapping.get(val, val)


def set_appearance_mode(mode: str):
    global _CURRENT_THEME
    app = _ensure_qapp()
    m = (mode or "dark").lower()
    if m == "system":
        try:
            scheme = app.styleHints().colorScheme()
            m = "light" if scheme == Qt.ColorScheme.Light else "dark"
        except Exception:
            m = "dark"
    if m == "light":
        _CURRENT_THEME = "light"
        app.setStyleSheet(LIGHT_STYLESHEET)
    else:
        _CURRENT_THEME = "dark"
        app.setStyleSheet(DARK_STYLESHEET)

    for top in app.topLevelWidgets():
        for w in top.findChildren(QWidget):
            if hasattr(w, "_apply_button_style"):
                w._apply_button_style()
            elif hasattr(w, "_apply_color"):
                w._apply_color()
            elif hasattr(w, "_update_button_styles"):
                w._update_button_styles()


def set_default_color_theme(_theme: str):
    pass


def ask_directory(initialdir: str = "", title: str = "Seleccionar carpeta") -> str:
    _ensure_qapp()
    return QFileDialog.getExistingDirectory(None, title, initialdir)


def create_placeholder_pixmap(width: int = 88, height: int = 50) -> CTkImage:
    _ensure_qapp()
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor(30, 36, 46))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(65, 78, 96))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.drawRect(1, 1, width - 3, height - 3)
    painter.setBrush(QColor(88, 166, 255))
    painter.setPen(Qt.PenStyle.NoPen)
    poly = QPolygon([QPoint(36, 15), QPoint(36, 35), QPoint(54, 25)])
    painter.drawPolygon(poly)
    painter.end()
    return CTkImage(qimage=img, size=(width, height))


def decode_thumbnail_bytes_to_ctk_image(raw_bytes: bytes, size: tuple[int, int] = (88, 50)) -> CTkImage | None:
    """Decodifica y escala bytes de imagen en C++ nativo con QImage (thread-safe, sin usar Pillow)."""
    qimg = QImage.fromData(raw_bytes)
    if qimg.isNull():
        return None
    w, h = size
    scaled = qimg.scaled(
        w,
        h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.width() > w or scaled.height() > h:
        x_off = max(0, (scaled.width() - w) // 2)
        y_off = max(0, (scaled.height() - h) // 2)
        scaled = scaled.copy(x_off, y_off, w, h)
    return CTkImage(qimage=scaled, size=size)


class CTkFont(QFont):
    def __init__(self, family: str = "Segoe UI", size: int = 12, weight: str = "normal"):
        super().__init__(family)
        # Ajuste de escala: CTk usa tamaño en píxeles (~13px), Qt usa píxeles exactos con setPixelSize
        self.setPixelSize(max(10, int(size)))
        if weight == "bold":
            self.setBold(True)


class CTkImage:
    def __init__(
        self,
        light_image: Any = None,
        dark_image: Any = None,
        size: tuple[int, int] = (88, 50),
        qimage: QImage | None = None,
    ):
        self.size = size
        self._qimage = qimage
        self._pixmap: QPixmap | None = None

    def to_pixmap(self) -> QPixmap:
        if self._pixmap is None:
            if self._qimage is not None:
                self._pixmap = QPixmap.fromImage(self._qimage)
            else:
                self._pixmap = QPixmap(self.size[0], self.size[1])
                self._pixmap.fill(QColor(30, 36, 46))
        return self._pixmap


class BooleanVar:
    def __init__(self, value: bool = False):
        self._value = bool(value)
        self._checkbox: CTkCheckBox | None = None

    def get(self) -> bool:
        if self._checkbox is not None:
            return self._checkbox.isChecked()
        return self._value

    def set(self, val: bool):
        self._value = bool(val)
        if self._checkbox is not None:
            with QSignalBlocker(self._checkbox):
                self._checkbox.setChecked(self._value)


def _parse_pad(pad: int | tuple[int, int]) -> tuple[int, int]:
    if isinstance(pad, (tuple, list)) and len(pad) >= 2:
        return int(pad[0]), int(pad[1])
    v = int(pad or 0)
    return v, v


class _GridPlaceableMixin:
    """Proporciona posicionamiento .grid() y .grid_remove() sobre QGridLayout nativo de Qt."""

    def _init_grid_mixin(self):
        self._grid_wrapper: QWidget | None = None

    def grid(
        self,
        row: int = 0,
        column: int = 0,
        rowspan: int = 1,
        columnspan: int = 1,
        padx: int | tuple[int, int] = 0,
        pady: int | tuple[int, int] = 0,
        sticky: str = "",
    ):
        if self._grid_wrapper is not None:
            self._grid_wrapper.show()
            self.show()
            p = self.parentWidget()
            while p is not None:
                if p.layout() is not None:
                    p.layout().invalidate()
                    p.layout().activate()
                p.updateGeometry()
                p = p.parentWidget()
            top = self.window()
            if top is not None and top.isVisible():
                min_h = top.minimumSizeHint().height()
                if top.height() < min_h:
                    top.resize(top.width(), min_h)
            return

        parent = self.parentWidget()
        if parent is None:
            return
        target_container = getattr(parent, "_inner_container", parent)
        layout = target_container.layout()
        if not isinstance(layout, QGridLayout):
            return

        px_l, px_r = _parse_pad(padx)
        py_t, py_b = _parse_pad(pady)

        st = (sticky or "").lower()
        h_expand = "e" in st and "w" in st
        v_expand = "n" in st and "s" in st

        sp = self.sizePolicy()
        sp.setHorizontalPolicy(
            QSizePolicy.Policy.Expanding if h_expand else QSizePolicy.Policy.Preferred
        )
        sp.setVerticalPolicy(
            QSizePolicy.Policy.Expanding if v_expand else QSizePolicy.Policy.Minimum
        )
        self.setSizePolicy(sp)

        align = Qt.AlignmentFlag(0)
        if not h_expand:
            if "w" in st:
                align |= Qt.AlignmentFlag.AlignLeft
            elif "e" in st:
                align |= Qt.AlignmentFlag.AlignRight
            else:
                align |= Qt.AlignmentFlag.AlignHCenter
        if not v_expand:
            if "n" in st:
                align |= Qt.AlignmentFlag.AlignTop
            elif "s" in st:
                align |= Qt.AlignmentFlag.AlignBottom
            else:
                align |= Qt.AlignmentFlag.AlignVCenter

        if px_l or px_r or py_t or py_b:
            wrapper = QWidget(target_container)
            wrapper.setProperty("transparent", True)
            w_layout = QVBoxLayout(wrapper)
            w_layout.setContentsMargins(px_l, py_t, px_r, py_b)
            w_layout.setSpacing(0)
            w_layout.addWidget(self)
            w_sp = wrapper.sizePolicy()
            w_sp.setHorizontalPolicy(sp.horizontalPolicy())
            w_sp.setVerticalPolicy(sp.verticalPolicy())
            wrapper.setSizePolicy(w_sp)
            wrapper.destroy = lambda w=wrapper, s=self: (
                w.setParent(None),
                w.deleteLater(),
                s.setParent(None),
                s.deleteLater(),
            )
            self._grid_wrapper = wrapper
            layout.addWidget(wrapper, row, column, rowspan, columnspan, align)
            wrapper.show()
        else:
            layout.addWidget(self, row, column, rowspan, columnspan, align)

        self.show()

    def grid_remove(self):
        if self._grid_wrapper is not None:
            self._grid_wrapper.hide()
        else:
            self.hide()
        p = self.parentWidget()
        while p is not None:
            if p.layout() is not None:
                p.layout().invalidate()
                p.layout().activate()
            p.updateGeometry()
            p = p.parentWidget()

    def destroy(self):
        if self._grid_wrapper is not None:
            self._grid_wrapper.setParent(None)
            self._grid_wrapper.deleteLater()
        self.setParent(None)
        self.deleteLater()


class _UiDispatcher(QObject):
    call_signal = Signal(int, object)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._timers: dict[str, QTimer] = {}
        self._counter = 0
        self.call_signal.connect(self._on_call, Qt.ConnectionType.QueuedConnection)

    def _on_call(self, delay_ms: int, func: Callable):
        if delay_ms <= 0:
            try:
                func()
            except Exception:
                pass
        else:
            QTimer.singleShot(delay_ms, func)

    def schedule_main_thread(self, delay_ms: int, func: Callable) -> str:
        if QThread.currentThread() == self.thread() and delay_ms > 0:
            self._counter += 1
            tid = f"timer_{self._counter}"
            timer = QTimer(self)
            timer.setSingleShot(True)

            def _fire():
                self._timers.pop(tid, None)
                try:
                    func()
                except Exception:
                    pass

            timer.timeout.connect(_fire)
            self._timers[tid] = timer
            timer.start(delay_ms)
            return tid

        self.call_signal.emit(max(0, int(delay_ms)), func)
        return "queued"

    def cancel(self, timer_id: str | None):
        if timer_id and timer_id in self._timers:
            t = self._timers.pop(timer_id, None)
            if t is not None:
                t.stop()


class CTk(QMainWindow):
    def __init__(self):
        _ensure_qapp()
        super().__init__()
        self._central = QWidget(self)
        self._central.setObjectName("CentralRoot")
        self.setCentralWidget(self._central)
        self._layout = QGridLayout(self._central)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._inner_container = self._central
        self._dispatcher = _UiDispatcher(self)

    def title(self, text: str):
        self.setWindowTitle(text)

    def geometry(self, spec: str):
        parts = spec.lower().split("x")
        if len(parts) == 2:
            self.resize(int(parts[0]), int(parts[1]))

    def minsize(self, w: int, h: int):
        self.setMinimumSize(w, h)

    def iconbitmap(self, path: str):
        self.setWindowIcon(QIcon(path))

    def grid_columnconfigure(self, col: int, weight: int = 0):
        self._layout.setColumnStretch(col, weight)

    def grid_rowconfigure(self, row: int, weight: int = 0):
        self._layout.setRowStretch(row, weight)

    def after(self, delay_ms: int, func: Callable) -> str:
        return self._dispatcher.schedule_main_thread(delay_ms, func)

    def after_cancel(self, timer_id: str | None):
        self._dispatcher.cancel(timer_id)

    def clipboard_get(self) -> str:
        cb = QGuiApplication.clipboard()
        return cb.text() if cb else ""

    def withdraw(self):
        self.hide()

    def update(self):
        QApplication.processEvents()

    def destroy(self):
        self.close()

    def mainloop(self):
        self.show()
        app = QApplication.instance()
        if app is not None:
            app.exec()


class CTkFrame(QFrame, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        corner_radius: int = 8,
        fg_color: str | tuple[str, str] | None = None,
        height: int | None = None,
        width: int | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        self._inner_container = self
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        if fg_color == "transparent":
            self.setProperty("transparent", True)
        elif fg_color is not None:
            self.setProperty("subcard", True)
        else:
            self.setProperty("card", True)

        if height:
            self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)

    def grid_columnconfigure(self, col: int, weight: int = 0):
        self._layout.setColumnStretch(col, weight)

    def grid_rowconfigure(self, row: int, weight: int = 0):
        self._layout.setRowStretch(row, weight)

    def winfo_children(self) -> list[QWidget]:
        out = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None:
                out.append(w)
        return out


class CTkScrollableFrame(QScrollArea, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        height: int = 155,
        corner_radius: int = 8,
        fg_color: str | tuple[str, str] | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        self.setWidgetResizable(True)
        self.setMinimumHeight(105)
        self.setMaximumHeight(max(120, height))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._inner_container = QWidget(self)
        self._inner_container.setProperty("transparent", True)
        self._layout = QGridLayout(self._inner_container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._inner_container)

    def grid_columnconfigure(self, col: int, weight: int = 0):
        self._layout.setColumnStretch(col, weight)

    def winfo_children(self) -> list[QWidget]:
        out = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None:
                out.append(w)
        return out

    def clear_children(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()


class CTkLabel(QLabel, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        text: str = "",
        font: CTkFont | None = None,
        text_color: str | tuple[str, str] | None = None,
        anchor: str = "w",
        image: CTkImage | None = None,
        width: int | None = None,
        height: int | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(text, parent)
        self._init_grid_mixin()
        self._text = text
        self._text_color = text_color
        self._image = image

        if font is not None:
            self.setFont(font)
        if width and height and image is not None:
            self.setFixedSize(width, height)
        elif width:
            self.setMinimumWidth(width)

        self._apply_anchor(anchor)
        self._apply_color()
        if image is not None:
            self.setPixmap(image.to_pixmap())

    def _apply_anchor(self, anchor: str):
        a = (anchor or "w").lower()
        if "e" in a:
            self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif a == "center":
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _apply_color(self):
        c = _resolve_color(self._text_color)
        if c:
            self.setStyleSheet(f"color: {c}; background: transparent; border: none;")

    def configure(self, **kwargs):
        if "text" in kwargs:
            self._text = str(kwargs["text"])
            self.setText(self._text)
        if "text_color" in kwargs:
            self._text_color = kwargs["text_color"]
            self._apply_color()
        if "image" in kwargs and kwargs["image"] is not None:
            self._image = kwargs["image"]
            self.setPixmap(self._image.to_pixmap())
        if "font" in kwargs and kwargs["font"] is not None:
            self.setFont(kwargs["font"])

    def cget(self, key: str) -> Any:
        if key == "text":
            return self.text()
        return None


class CTkButton(QPushButton, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        text: str = "",
        width: int | None = None,
        height: int | None = 32,
        corner_radius: int = 6,
        fg_color: str | tuple[str, str] | None = None,
        hover_color: str | tuple[str, str] | None = None,
        text_color: str = "#FFFFFF",
        font: CTkFont | None = None,
        command: Callable | None = None,
        state: str = "normal",
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(text, parent)
        self._init_grid_mixin()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fg_color = fg_color
        self._hover_color = hover_color
        self._text_color = text_color
        self._command = command

        if font is not None:
            self.setFont(font)
        if height:
            self.setFixedHeight(height)
        if width:
            self.setMinimumWidth(width)

        self._apply_button_style()
        self.setEnabled(state != "disabled")
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        if self._command is not None:
            self._command()

    def _apply_button_style(self):
        fg = _resolve_color(self._fg_color) or "#1f6aa5"
        hv = _resolve_color(self._hover_color) or "#185687"
        tc = _resolve_color(self._text_color) or "#ffffff"
        if _CURRENT_THEME == "light":
            dis_bg, dis_fg, dis_bd = "#d0d7de", "#8c959f", "#afb8c1"
        else:
            dis_bg, dis_fg, dis_bd = "#21262d", "#6e7681", "#2d333b"
        self.setStyleSheet(
            f"QPushButton {{ background-color: {fg}; color: {tc}; border: 1px solid {hv}; border-radius: 5px; padding: 4px 10px; font-weight: 600; }}"
            f"QPushButton:hover {{ background-color: {hv}; }}"
            f"QPushButton:disabled {{ background-color: {dis_bg}; color: {dis_fg}; border-color: {dis_bd}; }}"
        )

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.setText(str(kwargs["text"]))
        if "state" in kwargs:
            self.setEnabled(kwargs["state"] != "disabled")
        if "command" in kwargs:
            self._command = kwargs["command"]
        if "fg_color" in kwargs or "hover_color" in kwargs:
            if "fg_color" in kwargs:
                self._fg_color = kwargs["fg_color"]
            if "hover_color" in kwargs:
                self._hover_color = kwargs["hover_color"]
            self._apply_button_style()

    def cget(self, key: str) -> Any:
        if key == "text":
            return self.text()
        return None


class CTkEntry(QLineEdit, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        placeholder_text: str = "",
        width: int | None = None,
        height: int = 34,
        font: CTkFont | None = None,
        justify: str = "left",
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        self.setPlaceholderText(placeholder_text)
        if font is not None:
            self.setFont(font)
        if height:
            self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        if justify == "center":
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def get(self) -> str:
        return self.text()

    def insert(self, _index: Any, text: str):
        self.setText(str(text))

    def delete(self, _start: Any, _end: Any = None):
        self.clear()

    def bind(self, event_name: str, callback: Callable):
        ev = (event_name or "").lower()
        if "keyrelease" in ev:
            self.textEdited.connect(lambda _txt: callback(None))
        elif "focusout" in ev:
            self.editingFinished.connect(lambda: callback(None))
        elif "return" in ev:
            self.returnPressed.connect(lambda: callback(None))

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.setEnabled(kwargs["state"] != "disabled")


class CTkComboBox(QComboBox, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        values: list[str] | None = None,
        width: int = 140,
        height: int = 32,
        state: str = "readonly",
        font: CTkFont | None = None,
        command: Callable[[str], None] | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        self._values = list(values or [])
        self._command = command
        self._state = state

        if font is not None:
            self.setFont(font)
        if height:
            self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)

        self.addItems(self._values)
        self.setEnabled(state != "disabled")
        self.textActivated.connect(self._on_activated)

    def _on_activated(self, val: str):
        if self._command is not None:
            self._command(val)

    def get(self) -> str:
        return self.currentText()

    def set(self, val: str):
        with QSignalBlocker(self):
            idx = self.findText(str(val))
            if idx >= 0:
                self.setCurrentIndex(idx)
            elif str(val):
                self.addItem(str(val))
                self.setCurrentText(str(val))

    def configure(self, **kwargs):
        if "values" in kwargs:
            self._values = list(kwargs["values"])
            with QSignalBlocker(self):
                cur = self.currentText()
                self.clear()
                self.addItems(self._values)
                if cur in self._values:
                    self.setCurrentText(cur)
        if "state" in kwargs:
            self._state = kwargs["state"]
            self.setEnabled(self._state != "disabled")
        if "command" in kwargs:
            self._command = kwargs["command"]

    def cget(self, key: str) -> Any:
        if key == "values":
            return list(self._values)
        if key == "state":
            return self._state
        return None


class CTkOptionMenu(CTkComboBox):
    pass


class CTkSegmentedButton(QFrame, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        values: list[str],
        height: int = 34,
        corner_radius: int = 8,
        font: CTkFont | None = None,
        command: Callable[[str], None] | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        self._values = list(values)
        self._command = command
        self._current = self._values[0] if self._values else ""
        self._buttons: dict[str, QPushButton] = {}

        self.setProperty("subcard", True)
        h_layout = QHBoxLayout(self)
        h_layout.setContentsMargins(4, 4, 4, 4)
        h_layout.setSpacing(6)

        for val in self._values:
            btn = QPushButton(val.strip(), self)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(height - 4)
            if font is not None:
                btn.setFont(font)
            btn.clicked.connect(lambda _checked=False, v=val: self._on_tab_clicked(v))
            h_layout.addWidget(btn)
            self._buttons[val] = btn

        self._update_button_styles()

    def _on_tab_clicked(self, val: str):
        self._current = val
        self._update_button_styles()
        if self._command is not None:
            self._command(val)

    def _update_button_styles(self):
        for val, btn in self._buttons.items():
            if val == self._current:
                btn.setStyleSheet(
                    "QPushButton { background-color: #1f6aa5; color: #ffffff; border: 1px solid #388bfd; border-radius: 5px; font-weight: bold; }"
                )
            else:
                if _CURRENT_THEME == "light":
                    btn.setStyleSheet(
                        "QPushButton { background-color: transparent; color: #57606a; border: 1px solid transparent; border-radius: 5px; font-weight: 600; }"
                        "QPushButton:hover { background-color: #e1e4e8; color: #1f2328; }"
                    )
                else:
                    btn.setStyleSheet(
                        "QPushButton { background-color: transparent; color: #8b949e; border: 1px solid transparent; border-radius: 5px; font-weight: 600; }"
                        "QPushButton:hover { background-color: #21262d; color: #e6edf3; }"
                    )

    def get(self) -> str:
        return self._current

    def set(self, val: str):
        self._current = val
        self._update_button_styles()


class CTkSlider(QSlider, _GridPlaceableMixin):
    _SCALE = 10

    def __init__(
        self,
        master: QWidget,
        from_: float = 0.0,
        to: float = 100.0,
        height: int = 18,
        command: Callable[[float], None] | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._init_grid_mixin()
        self._from = float(from_)
        self._to = float(to)
        self._command = command
        self.setFixedHeight(max(18, height))
        self.setRange(int(self._from * self._SCALE), int(max(self._from + 1.0, self._to) * self._SCALE))
        self.valueChanged.connect(self._on_val_changed)

    def _on_val_changed(self, int_val: int):
        if self._command is not None:
            self._command(int_val / self._SCALE)

    def get(self) -> float:
        return self.value() / self._SCALE

    def set(self, val: float):
        with QSignalBlocker(self):
            self.setValue(int(round(float(val) * self._SCALE)))

    def configure(self, **kwargs):
        if "from_" in kwargs:
            self._from = float(kwargs["from_"])
        if "to" in kwargs:
            self._to = float(kwargs["to"])
        if "from_" in kwargs or "to" in kwargs:
            with QSignalBlocker(self):
                self.setRange(
                    int(round(self._from * self._SCALE)),
                    int(round(max(self._from + 1.0, self._to) * self._SCALE)),
                )
        if "state" in kwargs:
            self.setEnabled(kwargs["state"] != "disabled")

    def cget(self, key: str) -> Any:
        if key == "to":
            return self._to
        if key == "from_":
            return self._from
        return None


class CTkProgressBar(QProgressBar, _GridPlaceableMixin):
    def __init__(self, master: QWidget, height: int = 14, corner_radius: int = 6):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        self.setRange(0, 1000)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(height)

    def set(self, fraction: float):
        clamped = max(0.0, min(1.0, float(fraction)))
        self.setValue(int(round(clamped * 1000)))


class CTkTextbox(QPlainTextEdit, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        font: CTkFont | None = None,
        wrap: str = "word",
        state: str = "disabled",
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(parent)
        self._init_grid_mixin()
        if font is not None:
            self.setFont(font)
        self.setReadOnly(True)
        self.setMinimumHeight(65)
        # Límite nativo en C++ de 500 bloques para uso constante de RAM sin borrar manualmente
        self.document().setMaximumBlockCount(500)

    def configure(self, **kwargs):
        pass

    def insert(self, _pos: str, text: str):
        clean = text.rstrip("\n")
        if clean:
            self.appendPlainText(clean)

    def index(self, _spec: str) -> str:
        return f"{self.document().blockCount()}.0"

    def delete(self, _start: str, _end: str):
        pass

    def see(self, _pos: str):
        sb = self.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())


class CTkCheckBox(QCheckBox, _GridPlaceableMixin):
    def __init__(
        self,
        master: QWidget,
        text: str = "",
        variable: BooleanVar | None = None,
        font: CTkFont | None = None,
        checkbox_width: int = 18,
        checkbox_height: int = 18,
        corner_radius: int = 4,
        command: Callable | None = None,
    ):
        parent = getattr(master, "_inner_container", master)
        super().__init__(text, parent)
        self._init_grid_mixin()
        self._variable = variable
        self._command = command
        if font is not None:
            self.setFont(font)
        if variable is not None:
            initial_checked = variable.get()
            variable._checkbox = self
            self.setChecked(initial_checked)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool):
        if self._variable is not None:
            self._variable._value = checked
        if self._command is not None:
            self._command()
