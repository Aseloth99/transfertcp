"""Main application window"""

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                            QPushButton, QFileDialog, QLabel,
                            QSplitter, QFrame, QMenu, QApplication,
                            QSizeGrip)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QPoint
from PyQt6.QtGui import (QAction, QKeySequence, QDragEnterEvent, QDropEvent, QIcon,
                         QMouseEvent, QActionGroup, QCursor, QColor)
from os.path import exists, basename

from .device_list import DeviceListWidget
from .transfer_item import TransferListWidget
from .widgets.glyph_icons import glyph_color, glyph_icon
from .widgets.tone import set_tone
from .chrome_dialog import ChromeDialog
from .message_box import MessageBox
from .palette import ACCENTS, DEFAULT_ACCENT, accent_color, accent_key, accent_label, is_dark, set_accent_override
from .settings import SettingsDialog
from ..models.device import Device
from ..models.transfer import Transfer
from ..utils.helpers import format_bytes, get_asset_path
from ..utils.config import get_config
from ..utils.locales import get_active_language, t, language_choices, create_language_icon, install_qt_translations
from .icons import (
    theme_system_icon,
    theme_dark_icon,
    theme_light_icon,
    history_icon,
    globe_icon,
    folder_icon,
    settings_gear_icon,
    door_exit_icon,
    info_icon,
)


def _color_swatch_icon(hex_color: str) -> QIcon:
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
    pix = QPixmap(32, 32)  # 2x çözünürlük (yüksek DPI'da keskin); şekil diğer uygulamalarla aynı
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(2)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(hex_color))
    p.setPen(QPen(QColor(hex_color).darker(115), 1))
    p.drawRoundedRect(QRectF(1, 1, 14, 14), 4, 4)
    p.end()
    return QIcon(pix)


class DropZone(QFrame):
    """Drag and drop zone for files"""
    
    files_dropped = pyqtSignal(list)  # list of file paths
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(False)  # hedef cihaz hazır olunca açılır (set_target)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 10, 12, 10)
        
        icon_label = QLabel()
        self.icon_label = icon_label
        icon_label.setFixedHeight(36)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setContentsMargins(0, 0, 0, 0)
        self.refresh_icon()
        
        self.text_label = QLabel(t("drag_drop_text", "tr").replace("\n", " "))
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setWordWrap(False)
        set_tone(self.text_label, "muted")
        self.text_label.setStyleSheet("font-size: 9pt; padding: 0px; margin: 0px;")
        self.text_label.setMinimumWidth(200)
        
        # Buttons container
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.select_btn = QPushButton(t("select_file", "tr"))
        self.select_btn.setMinimumWidth(100)
        self.select_btn.setMaximumWidth(120)
        self.select_btn.setProperty("class", "primary")
        
        self.select_folder_btn = QPushButton(t("select_folder", "tr"))
        self.select_folder_btn.setMinimumWidth(100)
        self.select_folder_btn.setMaximumWidth(120)
        self.select_folder_btn.setProperty("class", "primary")
        
        buttons_layout.addWidget(self.select_btn)
        buttons_layout.addWidget(self.select_folder_btn)
        
        # Hedef cihaz satiri: dosyalarin kime gidecegi (ya da neden gonderilemeyecegi) birakma alaninda yazar
        self.target_label = QLabel("")
        self.target_label.setObjectName("dropTarget")
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._target = None
        self._target_lang = "tr"
        self.ready = False

        layout.addWidget(icon_label)
        layout.addWidget(self.text_label)
        layout.addLayout(buttons_layout)
        layout.addWidget(self.target_label)
        self.set_target(None)
        
        # Style will be applied from theme
        self._update_dropzone_style()
        
        self.setMinimumHeight(156)
        self.setMaximumHeight(184)

    def refresh_icon(self) -> None:
        """Yukleme simgesi tema rengine gore yeniden cizilir (emoji yerine vektor)."""
        app = QApplication.instance()
        dark = True if app is None or app.property("tt_dark") is None else bool(app.property("tt_dark"))
        self.icon_label.setPixmap(glyph_icon("upload", glyph_color(dark, "muted"), 34).pixmap(34, 34))

    def set_target(self, device, lang: str | None = None) -> None:
        """Secili hedef cihazi gosterir; gonderilemeyecekse (cihaz yok / cevrimdisi) dugmeler pasif olur."""
        if lang is not None:
            self._target_lang = lang
        lang = self._target_lang
        self._target = device
        if device is None:
            state, tone, text = "none", "warn", t("drop_target_none", lang)
        elif not device.is_online:
            state, tone, text = "offline", "err", t("drop_target_offline", lang).format(name=device.display_name)
        else:
            state, tone, text = "ready", "ok", t("drop_target_ready", lang).format(name=device.display_name, ip=device.ip)
        self.target_label.setText(text)
        set_tone(self.target_label, tone)
        ready = state == "ready"
        self.ready = ready
        self.select_btn.setEnabled(ready)
        self.select_folder_btn.setEnabled(ready)
        # Gönderilemiyorsa diyalog açılmaz: düğmeler pasif, nedeni ipucunda ve hedef satırında yazar
        hint = "" if ready else text
        for widget in (self.select_btn, self.select_folder_btn, self):
            widget.setToolTip(hint)
        self.setAcceptDrops(ready)
        if self.property("target") != state:
            self.setProperty("target", state)
            self.style().unpolish(self)
            self.style().polish(self)

    def retranslate(self, lang: str = "tr"):
        self.text_label.setText(t("drop_zone_text", lang).replace("\n", " "))  # tek satir: dusey alan butonlara kalsin
        self.select_btn.setText(t("select_file", lang))
        self.select_folder_btn.setText(t("select_folder", lang))
        self.set_target(self._target, lang)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragOver", True)
            self.style().unpolish(self)
            self.style().polish(self)
    
    def dragLeaveEvent(self, event):
        """Handle drag leave"""
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
    
    def _update_dropzone_style(self):
        """Update dropzone style based on current theme"""
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
    
    def dropEvent(self, event: QDropEvent):
        """Handle drop"""
        files = []
        for url in event.mimeData().urls():
            files.append(url.toLocalFile())
        
        if files:
            self.files_dropped.emit(files)
        
        event.acceptProposedAction()
        self.dragLeaveEvent(event)


class CustomTitleBar(QWidget):
    """Custom title bar for frameless window"""

    update_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._old_pos = None
        self._update_version = ""
        self._lang = "tr"
        self.setObjectName("CustomTitleBar")
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup title bar UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 6, 4)
        layout.setSpacing(6)
        
        # Icon - proportional size with clean padding
        self.icon_label = QLabel()
        icon_path = get_asset_path("icons", "app_icon.png")
        if exists(icon_path):
            icon = QIcon(icon_path)
            pixmap = icon.pixmap(22, 22)
            self.icon_label.setPixmap(pixmap)
        else:
            self.icon_label.setPixmap(folder_icon(accent_color()).pixmap(20, 20))
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setContentsMargins(0, 0, 0, 0)
        self.icon_label.setStyleSheet("padding: 0px; margin: 0px; border: none;")
        
        # Title
        self.title_label = QLabel("TransferTCP")
        self.title_label.setStyleSheet("font-size: 10pt; font-weight: 600; padding: 0px; margin: 0px;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)

        # Güncelleme düğmesi sağda belirince menü ortada kalsın diye sol tarafa eş genişlikte boşluk eklenir
        self._left_balance = QWidget()
        self._left_balance.setFixedWidth(0)
        layout.addWidget(self._left_balance)

        layout.addStretch(1)
        
        # Menu buttons (will be populated by parent window) - centered
        self.menu_container = QWidget()
        self.menu_layout = QHBoxLayout(self.menu_container)
        self.menu_layout.setContentsMargins(0, 0, 0, 0)
        self.menu_layout.setSpacing(3)
        self.menu_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.menu_container)
        
        layout.addStretch(1)
        
        # Güncelleme düğmesi: sessiz denetim yeni sürüm bulursa görünür (pop-up yok)
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("updatePill")
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.update_btn.clicked.connect(self.update_clicked.emit)
        self.update_btn.setVisible(False)
        layout.addWidget(self.update_btn)

        # Window controls
        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setFixedSize(28, 24)
        self.minimize_btn.setProperty("class", "title-button")
        self.minimize_btn.clicked.connect(self.parent_window.showMinimized)
        
        self.maximize_btn = QPushButton("□")
        self.maximize_btn.setFixedSize(28, 24)
        self.maximize_btn.setProperty("class", "title-button")
        self.maximize_btn.clicked.connect(self._toggle_maximize)
        
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(28, 24)
        self.close_btn.setProperty("class", "title-button-close")
        self.close_btn.clicked.connect(self.parent_window.close)
        
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.maximize_btn)
        layout.addWidget(self.close_btn)
        
        # Set fixed height and ensure vertical centering below the accent strip
        self.setFixedHeight(38)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.retranslate("tr")

    def retranslate(self, lang: str = "tr"):
        self._lang = lang
        self.minimize_btn.setToolTip(t("window_minimize", lang))
        self.maximize_btn.setToolTip(t("window_maximize", lang))
        self.close_btn.setToolTip(t("window_close", lang))
        if hasattr(self, "update_btn"):
            self._apply_update_text()

    def set_update_available(self, version: str = "") -> None:
        """"Güncelle · vX" düğmesini göster/gizle (version boşsa gizler)."""
        self._update_version = version or ""
        self._apply_update_text()
        self.update_btn.setVisible(bool(self._update_version))
        self._left_balance.setFixedWidth(
            self.update_btn.sizeHint().width() + 8 if self._update_version else 0
        )

    def _apply_update_text(self) -> None:
        if not self._update_version:
            return
        self.update_btn.setText(t("update_pill", self._lang).format(version=self._update_version))
        self.update_btn.setToolTip(t("update_pill_tip", self._lang).format(version=self._update_version))

    def _toggle_maximize(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()
    
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for window dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            gp = event.globalPosition().toPoint()
            local = self.parent_window.mapFromGlobal(gp)
            if self.parent_window._hit_resize_edges(local):
                event.ignore()
                return
            self._old_pos = gp
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for window dragging"""
        if self._old_pos is not None:
            delta = event.globalPosition().toPoint() - self._old_pos
            self.parent_window.move(self.parent_window.pos() + delta)
            self._old_pos = event.globalPosition().toPoint()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release"""
        self._old_pos = None
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()


class MainWindow(QMainWindow):
    """Main application window"""
    
    # Signals for core operations
    send_files_requested = pyqtSignal(list, Device, str)  # files, target_device, folder_path (empty string if not folder)
    pause_transfer_requested = pyqtSignal(str)  # transfer_id
    resume_transfer_requested = pyqtSignal(str)
    cancel_transfer_requested = pyqtSignal(str)
    update_requested = pyqtSignal()  # başlık çubuğundaki "Güncelle" düğmesi
    refresh_devices_requested = pyqtSignal()  # New signal
    manual_device_requested = pyqtSignal(str, str, int)  # ip, görünen ad, port — yayınsız ağlar için
    device_remove_requested = pyqtSignal(object)  # Device — listeden kaldırma
    
    def __init__(self):
        super().__init__()
        self.config = get_config()
        self.lang = get_active_language(self.config)
        self.current_theme = "dark"
        from ..utils.logger import get_logger
        self.logger = get_logger()
        
        self.setWindowTitle("TransferTCP")
        
        # Set window icon
        from PyQt6.QtGui import QIcon
        icon_path = get_asset_path("icons", "app_icon.png")
        if exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Make window frameless for custom title bar; edges stay resizable
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(900, 600)
        self.resize(1000, 680)
        self._resize_edge = 0
        self._resize_start = None
        self._resize_geom = None
        self._override_shape = None
        
        # Hide default menubar (we'll use custom one in title bar)
        self.menuBar().setVisible(False)
        
        self._setup_title_bar()
        self._setup_ui()
        self._setup_title_bar_menus()
        self._setup_statusbar()
        self._retranslate_ui()
        self._load_theme()
        try:  # follow Windows light/dark while the app is open (only matters when the theme is "system")
            QApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except (AttributeError, TypeError):
            pass
        
        self.logger.info("Main window initialized")
    
    def _setup_title_bar(self):
        """Setup custom title bar"""
        self.title_bar = CustomTitleBar(self)
        self.title_bar.update_clicked.connect(self.update_requested.emit)
        # Title bar will be added to main layout in _setup_ui
    
    def _setup_ui(self):
        """Setup user interface"""
        # Main container widget
        main_container = QWidget()
        main_container.setObjectName("mainContainer")
        main_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.main_container = main_container
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Add title bar
        main_layout.addWidget(self.title_bar)
        
        # Uzaktan duyuru satırı (sunucu bir duyuru verene kadar gizli)
        from .notice_bar import NoticeBar
        self.notice_bar = NoticeBar()
        self.notice_bar.dismissed.connect(self._on_notice_dismissed)
        notice_wrap = QHBoxLayout()
        notice_wrap.setContentsMargins(10, 6, 10, 0)
        notice_wrap.addWidget(self.notice_bar)
        main_layout.addLayout(notice_wrap)

        # Central widget for content
        central_widget = QWidget()
        content_layout = QHBoxLayout(central_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # Splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Devices
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        
        self.device_list = DeviceListWidget()
        self.device_list.device_double_clicked.connect(self._on_device_selected_for_send)
        self.device_list.refresh_requested.connect(self._on_refresh_devices)
        self.device_list.manual_device_requested.connect(self.manual_device_requested.emit)
        self.device_list.device_remove_requested.connect(self.device_remove_requested.emit)
        
        left_layout.addWidget(self.device_list)

        # Bu cihazın adı/adresi: karşı taraf bizi bulamıyorsa neye bakacağını (ad, IP, port) tek satırda gösterir
        self.local_info_label = QLabel("")
        self.local_info_label.setObjectName("localInfo")
        set_tone(self.local_info_label, "muted")
        self.local_info_label.setContentsMargins(6, 4, 6, 0)
        left_layout.addWidget(self.local_info_label)
        self._refresh_local_info()

        # Right panel: Transfers and drop zone
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(12)
        
        # Drop zone - more compact
        self.drop_zone = DropZone()
        self.drop_zone.select_btn.clicked.connect(self._select_files)
        self.drop_zone.select_folder_btn.clicked.connect(self._select_folder)
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.device_list.selection_changed.connect(self._refresh_drop_target)
        self._refresh_drop_target()
        self.drop_zone.setMaximumHeight(184)
        
        # Transfer list
        self.transfer_list = TransferListWidget()
        self.transfer_list.pause_transfer.connect(self.pause_transfer_requested.emit)
        self.transfer_list.resume_transfer.connect(self.resume_transfer_requested.emit)
        self.transfer_list.cancel_transfer.connect(self.cancel_transfer_requested.emit)
        self.transfer_list.clear_requested.connect(self._clear_transfer_list)
        
        right_layout.addWidget(self.drop_zone, stretch=0)
        right_layout.addWidget(self.transfer_list, stretch=1)
        
        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        content_layout.addWidget(splitter)
        main_layout.addWidget(central_widget, 1)
        
        # Set main container as central widget
        self.setCentralWidget(main_container)
        self._size_grip = QSizeGrip(main_container)
        self._size_grip.setFixedSize(18, 18)
        self._size_grip.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._enable_mouse_tracking(self)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
        self._position_size_grip()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_size_grip()

    def _position_size_grip(self) -> None:
        grip = getattr(self, "_size_grip", None)
        host = getattr(self, "main_container", None)
        if grip is None or host is None:
            return
        maximized = self.isMaximized() or self.isFullScreen()
        grip.setVisible(not maximized)
        if maximized:
            return
        grip.move(max(0, host.width() - grip.width() - 8),
                  max(0, host.height() - grip.height() - 8))
        grip.raise_()

    _RESIZE_EDGE = 5
    _RESIZE_CORNER = 10

    def _hit_resize_edges(self, pos: QPoint) -> int:
        if self.isMaximized() or self.isFullScreen():
            return 0
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        if x < 0 or y < 0 or x > w or y > h:
            return 0
        corner = self._RESIZE_CORNER
        edge = self._RESIZE_EDGE
        if x <= corner and y <= corner:
            return 1 | 4
        if x >= w - corner and y <= corner:
            return 2 | 4
        if x <= corner and y >= h - corner:
            return 1 | 8
        if x >= w - corner and y >= h - corner:
            return 2 | 8
        flags = 0
        if x <= edge:
            flags |= 1
        if x >= w - edge:
            flags |= 2
        if y <= edge:
            flags |= 4
        if y >= h - edge:
            flags |= 8
        return flags

    def _cursor_for_edge(self, edge: int):
        if edge in (1 | 4, 2 | 8):
            return Qt.CursorShape.SizeFDiagCursor
        if edge in (2 | 4, 1 | 8):
            return Qt.CursorShape.SizeBDiagCursor
        if edge in (1, 2):
            return Qt.CursorShape.SizeHorCursor
        if edge in (4, 8):
            return Qt.CursorShape.SizeVerCursor
        return None

    def _clear_resize_cursor(self):
        if getattr(self, "_override_shape", None) is not None:
            QApplication.restoreOverrideCursor()
            self._override_shape = None
        self.unsetCursor()

    def _apply_edge_cursor(self, local: QPoint):
        edge = self._hit_resize_edges(local)
        shape = self._cursor_for_edge(edge)
        if not edge or shape is None:
            self._clear_resize_cursor()
            return edge
        if self._override_shape != shape:
            if self._override_shape is None:
                QApplication.setOverrideCursor(QCursor(shape))
            else:
                QApplication.changeOverrideCursor(QCursor(shape))
            self._override_shape = shape
        self.setCursor(shape)
        return edge

    def _apply_resize_delta(self, delta: QPoint):
        geom = self._resize_geom
        if geom is None or not self._resize_edge:
            return
        x, y, w, h = geom.x(), geom.y(), geom.width(), geom.height()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        if self._resize_edge & 1:
            x = min(geom.x() + delta.x(), geom.right() - min_w + 1)
            w = geom.right() - x + 1
        if self._resize_edge & 2:
            w = max(min_w, geom.width() + delta.x())
        if self._resize_edge & 4:
            y = min(geom.y() + delta.y(), geom.bottom() - min_h + 1)
            h = geom.bottom() - y + 1
        if self._resize_edge & 8:
            h = max(min_h, geom.height() + delta.y())
        self.setGeometry(x, y, w, h)

    def _event_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        return QCursor.pos()

    def _enable_mouse_tracking(self, widget):
        if widget is None or isinstance(widget, QMenu):
            return
        widget.setMouseTracking(True)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        for child in widget.findChildren(QWidget):
            if isinstance(child, QMenu):
                continue
            child.setMouseTracking(True)
            child.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def leaveEvent(self, event):
        if not self._resize_edge:
            self._clear_resize_cursor()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._clear_resize_cursor()
        super().hideEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            gp = self._event_global_pos(event)
            local = self.mapFromGlobal(gp)
            edge = self._hit_resize_edges(local)
            if edge:
                self._resize_edge = edge
                self._resize_start = gp
                self._resize_geom = self.geometry()
                self._apply_edge_cursor(local)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        gp = self._event_global_pos(event)
        local = self.mapFromGlobal(gp)
        if self._resize_edge and self._resize_start is not None:
            self._apply_resize_delta(gp - self._resize_start)
            event.accept()
            return
        self._apply_edge_cursor(local)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._resize_edge = None
        self._resize_start = None
        self._resize_geom = None
        gp = self._event_global_pos(event)
        self._apply_edge_cursor(self.mapFromGlobal(gp))
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        et = event.type()
        if et not in (
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Leave,
        ):
            return super().eventFilter(watched, event)
        if not isinstance(watched, QWidget) or watched.window() is not self:
            return super().eventFilter(watched, event)
        if et == QEvent.Type.Leave:
            if watched is self and not self._resize_edge:
                self._clear_resize_cursor()
            return super().eventFilter(watched, event)
        gp = self._event_global_pos(event)
        local = self.mapFromGlobal(gp)
        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edge = self._hit_resize_edges(local)
            if edge:
                self._resize_edge = edge
                self._resize_start = gp
                self._resize_geom = self.geometry()
                self._apply_edge_cursor(local)
                return True
        elif et in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            if self._resize_edge and self._resize_start is not None:
                self._apply_resize_delta(gp - self._resize_start)
                return True
            self._apply_edge_cursor(local)
        elif et == QEvent.Type.MouseButtonRelease:
            self._resize_edge = None
            self._resize_start = None
            self._resize_geom = None
            self._apply_edge_cursor(local)
        return super().eventFilter(watched, event)

    
    def _setup_title_bar_menus(self):
        """Başlık çubuğu menüleri: Dosya · Tema · Dil · Renk · Ayarlar (simgeler vektör, rengi vurgudan)."""
        lang = getattr(self, "lang", "tr")
        # File menu button
        self.file_btn = QPushButton(t('file', lang))
        self.file_btn.setProperty("class", "menu-button")
        self.file_btn.setFixedHeight(24)
        file_menu = QMenu(self)
        file_menu.setToolTipsVisible(True)  # gönderilemiyorsa nedeni menüde de ipucu olarak görünür
        self.file_menu = file_menu

        self.send_action = QAction(t('send_file', lang), self)
        self.send_action.setShortcut(QKeySequence("Ctrl+O"))
        self.send_action.triggered.connect(self._select_files)
        file_menu.addAction(self.send_action)

        file_menu.addSeparator()

        self.exit_action = QAction(t('exit', lang), self)
        # X / Alt+F4 yalnızca tepsiye gizler; uygulamayı gerçekten kapatan: Ctrl+Q, bu "Çıkış" ve tepsi "Çıkış".
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_action.triggered.connect(self.quit_application)
        file_menu.addAction(self.exit_action)

        self.file_btn.setMenu(file_menu)

        # Theme menu button (Doğrudan tema seçenekleri)
        self.theme_btn = QPushButton(t('theme', lang))
        self.theme_btn.setProperty("class", "menu-button")
        self.theme_btn.setFixedHeight(24)
        self.theme_btn.setIcon(theme_system_icon())
        self.theme_menu = QMenu(self)

        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        current_theme = self.config.get('ui', 'theme', 'system')

        self.system_action = QAction(theme_system_icon(), t("theme_system", lang), self)
        self.system_action.setCheckable(True)
        self.system_action.setChecked(current_theme == "system")
        self.system_action.triggered.connect(lambda: self._change_theme("system"))
        theme_group.addAction(self.system_action)
        self.theme_menu.addAction(self.system_action)

        self.dark_action = QAction(theme_dark_icon(), t("theme_dark", lang), self)
        self.dark_action.setCheckable(True)
        self.dark_action.setChecked(current_theme == "dark")
        self.dark_action.triggered.connect(lambda: self._change_theme("dark"))
        theme_group.addAction(self.dark_action)
        self.theme_menu.addAction(self.dark_action)

        self.light_action = QAction(theme_light_icon(), t("theme_light", lang), self)
        self.light_action.setCheckable(True)
        self.light_action.setChecked(current_theme == "light")
        self.light_action.triggered.connect(lambda: self._change_theme("light"))
        theme_group.addAction(self.light_action)
        self.theme_menu.addAction(self.light_action)

        self.theme_btn.setMenu(self.theme_menu)

        # Global kısayol: Ctrl+H geçmiş
        self.history_action = QAction(history_icon(), t("history", lang), self)
        self.history_action.setShortcut(QKeySequence("Ctrl+H"))
        self.history_action.triggered.connect(self._show_history)
        self.addAction(self.history_action)

        # Language menu button (has vector flag icon)
        self.lang_btn = QPushButton(t('language', lang))
        self.lang_btn.setProperty("class", "menu-button")
        self.lang_btn.setFixedHeight(24)
        self.lang_btn.setIcon(globe_icon(accent_color()))
        lang_menu = QMenu(self)
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        self._lang_actions = {}
        for code, label in language_choices(include_auto=True, lang=lang):
            act = QAction(create_language_icon(code), label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, c=code: self._change_language(c))
            lang_group.addAction(act)
            lang_menu.addAction(act)
            self._lang_actions[code] = act
        self.lang_btn.setMenu(lang_menu)

        # Accent Color menu button (has swatch icon)
        self.color_btn = QPushButton(t('accent', lang))
        self.color_btn.setProperty("class", "menu-button")
        self.color_btn.setFixedHeight(24)
        color_menu = QMenu(self)
        color_group = QActionGroup(self)
        color_group.setExclusive(True)
        self._accent_actions = {}
        for key, spec in ACCENTS.items():
            act = QAction(_color_swatch_icon(spec["accent"]), accent_label(key, lang), self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, k=key: self._change_accent(k))
            color_group.addAction(act)
            color_menu.addAction(act)
            self._accent_actions[key] = act
        self.color_btn.setMenu(color_menu)

        # Direct Settings button at far right of menus
        self.settings_btn = QPushButton(t('settings', lang))
        self.settings_btn.setProperty("class", "menu-button")
        self.settings_btn.setFixedHeight(24)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self._open_settings)

        # Ctrl+, her yerde ayarları açar (FlexiKey / MediaCompressor / Lumina ile aynı kısayol)
        self.settings_action = QAction(t('settings', lang), self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self._open_settings)
        self.addAction(self.settings_action)

        self.about_action = QAction(t('about', lang), self)
        self.about_action.setShortcut(QKeySequence("F1"))
        self.about_action.triggered.connect(self._show_about)
        self.addAction(self.about_action)

        # Add to title bar in aligned order: Dosya, Tema, Dil, Renk, Ayarlar
        self.title_bar.menu_layout.addWidget(self.file_btn)
        self.title_bar.menu_layout.addWidget(self.theme_btn)
        self.title_bar.menu_layout.addWidget(self.lang_btn)
        self.title_bar.menu_layout.addWidget(self.color_btn)
        self.title_bar.menu_layout.addWidget(self.settings_btn)
        self._refresh_menu_icons()

    def _refresh_menu_icons(self):
        """Vurguya bağlı menü simgeleri (Dosya, Gönder, Çıkış, Ayarlar, Dil, Hakkında) seçili vurguyla yeniden boyanır."""
        color = accent_color()
        self.file_btn.setIcon(folder_icon(color))
        self.send_action.setIcon(glyph_icon("upload", color, 16))
        self.exit_action.setIcon(door_exit_icon("#ef4444"))
        self.settings_btn.setIcon(settings_gear_icon(color))
        self.settings_action.setIcon(settings_gear_icon(color))
        self.lang_btn.setIcon(globe_icon(color))
        self.about_action.setIcon(info_icon(color))

    def _setup_statusbar(self):
        """Gönderilen/alınan toplamlar transfer başlığına taşındı; alt çubuk gizlenir."""
        if self.statusBar():
            self.statusBar().hide()
        self.stats_label = None
        self.connection_label = None
    
    def _load_theme(self):
        """Load and apply theme"""
        theme = self.config.get('ui', 'theme', 'system')
        self.apply_theme(theme)
        self._update_theme_menu_checks()
    
    def _on_system_scheme_changed(self, *_):
        if self.config.get('ui', 'theme', 'system') == 'system':
            self._load_theme()

    def _change_theme(self, theme: str):
        """Change theme from menu"""
        self.config.set('ui', 'theme', theme)
        self.apply_theme(theme)
        self.logger.info(f"Theme changed to: {theme}")
        self._update_theme_menu_checks()
        self._sync_tray_menus()

    def _update_theme_menu_checks(self):
        theme = self.config.get('ui', 'theme', 'system')
        if hasattr(self, 'system_action'):
            self.system_action.setChecked(theme == "system")
        if hasattr(self, 'dark_action'):
            self.dark_action.setChecked(theme == "dark")
        if hasattr(self, 'light_action'):
            self.light_action.setChecked(theme == "light")

    def _change_language(self, lang_choice: str):
        """Change language from menu or tray"""
        from ..utils.locales import AUTO_LANGUAGE

        self.config.set('ui', 'language', lang_choice)
        self.lang = get_active_language(self.config)
        self._retranslate_ui()
        self._update_lang_menu_checks()
        self.logger.info(f"Language changed to: {lang_choice}")

    def _change_accent(self, key: str):
        """Change accent color from menu"""
        self.config.set('ui', 'accent', key)
        self.apply_theme(self.config.get('ui', 'theme', 'system'))
        self._update_accent_menu_checks()
        self._sync_tray_menus()
        self.logger.info(f"Accent color changed to: {key}")

    def _update_accent_menu_checks(self, key: str | None = None):
        key = key or accent_key()
        if hasattr(self, '_accent_actions'):
            for k, act in self._accent_actions.items():
                act.setChecked(k == key)
        if hasattr(self, 'color_btn'):
            spec = ACCENTS.get(key, ACCENTS[DEFAULT_ACCENT])
            self.color_btn.setIcon(_color_swatch_icon(spec["accent"]))

    def _update_lang_menu_checks(self):
        from ..utils.locales import AUTO_LANGUAGE
        lang_choice = self.config.get('ui', 'language', AUTO_LANGUAGE)
        if hasattr(self, '_lang_actions'):
            for c, act in self._lang_actions.items():
                act.setChecked(c == lang_choice)
        if hasattr(self, 'lang_btn'):
            self.lang_btn.setIcon(globe_icon())

    def _sync_tray_menus(self):
        tray = getattr(self, 'tray_icon', None)
        if not tray:
            return
        from ..utils.locales import AUTO_LANGUAGE

        tray.set_theme_choice(self.config.get('ui', 'theme', 'system'))
        tray.set_language_choice(
            self.config.get('ui', 'language', AUTO_LANGUAGE),
            active_lang=self.lang,
        )
    
    def apply_theme(self, theme: str, accent: str | None = None):
        """Apply theme to window. `accent`: kaydedilmeden denenecek vurgu (ayarlardaki canlı önizleme)."""
        if theme == "system":
            from ..utils.theme import get_system_theme
            actual_theme = get_system_theme()
            self.logger.info(f"System theme detected: {actual_theme}")
        else:
            actual_theme = theme
        self.current_theme = actual_theme
        app_for_theme = QApplication.instance()
        if app_for_theme is not None:
            app_for_theme.setProperty("tt_dark", actual_theme == "dark")  # kodla cizilen simgeler bunu okur

        theme_file = get_asset_path("styles", f"{actual_theme}.qss")
        set_accent_override(accent)  # None: kayıtlı vurgu (önizleme bitti)
        accent_name = accent_key()
        acc_spec = ACCENTS[accent_name]
        
        try:
            if exists(theme_file):
                with open(theme_file, 'r', encoding='utf-8') as f:
                    stylesheet = f.read()
                    icon_dir = get_asset_path("icons").replace('\\', '/')
                    stylesheet = stylesheet.replace("__ASSET_ICONS__", icon_dir)
                    
                    # Dynamic accent color replacement
                    if accent_name != "blue":
                        stylesheet = stylesheet.replace("#2196F3", acc_spec["accent"])
                        stylesheet = stylesheet.replace("#1976D2", acc_spec["accent2"])
                        hi_color = acc_spec["hi_dark"] if actual_theme == "dark" else acc_spec["hi_light"]
                        stylesheet = stylesheet.replace("#42A5F5", hi_color)
                        # the remaining Material blues (pressed shades, highlights, group titles) follow the accent too
                        deep = QColor(acc_spec["accent2"])
                        stylesheet = stylesheet.replace("#1565C0", deep.darker(118).name())
                        stylesheet = stylesheet.replace("#0D47A1", deep.darker(160).name())
                        stylesheet = stylesheet.replace("#64B5F6", acc_spec["hi_dark"])
                        stylesheet = stylesheet.replace("#90CAF9", acc_spec["hi_light"])
                        stylesheet = stylesheet.replace("#BBDEFB", acc_spec["hi_light"])
                        # translucent accent tints (selected rows, checked menu items) are written as rgba(), not hex
                        tint = QColor(acc_spec["accent"])
                        stylesheet = stylesheet.replace("rgba(33, 150, 243,", f"rgba({tint.red()}, {tint.green()}, {tint.blue()},")
                        tint_hi = QColor(hi_color)
                        stylesheet = stylesheet.replace("rgba(66, 165, 245,", f"rgba({tint_hi.red()}, {tint_hi.green()}, {tint_hi.blue()},")
                        
                    self.setStyleSheet(stylesheet)
                    app = QApplication.instance()
                    if app:
                        app.setStyleSheet(stylesheet)
                    if hasattr(self, "device_list"):
                        self.device_list._update_all_widget_styles()
                    if hasattr(self, "drop_zone"):
                        self.drop_zone.refresh_icon()
                    self._update_accent_menu_checks(accent_name)
                    self._update_lang_menu_checks()
                    self._refresh_menu_icons()
                    self.logger.info(f"Theme loaded: {actual_theme} (accent: {accent_name})")
            else:
                self.logger.warning(f"Theme file not found: {theme_file}")
                self._apply_basic_style()
        except Exception as e:
            self.logger.error(f"Failed to load theme: {e}")
            self._apply_basic_style()
    
    def _apply_basic_style(self):
        """Apply basic styling when theme file is not available"""
        basic_style = """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #42A5F5;
            }
        """
        self.setStyleSheet(basic_style)
    
    def _send_target(self):
        """Gönderime hazır hedef cihaz (seçili ve çevrimiçi) ya da None. Hazır değilken düğmeler/menü pasiftir;
        bu yüzden kullanıcıya diyalog gösterilmez, neden bırakma alanındaki hedef satırında ve ipucunda yazar."""
        device = self.device_list.get_selected_device()
        if device is None or not device.is_online:
            return None
        return device

    def _select_files(self):
        """Open file dialog to select files"""
        selected_device = self._send_target()
        if selected_device is None:
            return
        lang = self.lang
        files, _ = QFileDialog.getOpenFileNames(
            self,
            t("dlg_send_files_title", lang).format(name=selected_device.name),
            "",
            t("all_files", lang)
        )

        if files:
            self._on_files_dropped(files)

    def _select_folder(self):
        """Open folder dialog to select folder"""
        selected_device = self._send_target()
        if selected_device is None:
            return
        lang = self.lang
        folder = QFileDialog.getExistingDirectory(
            self,
            t("dlg_send_folder_title", lang).format(name=selected_device.name),
            ""
        )

        if folder:
            self._on_folder_selected(folder)

    def _refresh_local_info(self):
        """"Bu cihaz: ad · IP:port" satırını yapılandırmadan yenile."""
        try:
            from ..utils.helpers import get_hostname, get_local_ip
            from ..utils.ports import DEFAULT_TRANSFER_PORT
            name = self.config.get('general', 'device_name', '') or get_hostname()
            port = self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)
            self.local_info_label.setText(
                t("local_device_info", self.lang).format(name=name, ip=get_local_ip(), port=port)
            )
        except Exception:
            self.local_info_label.setText("")

    def _refresh_drop_target(self):
        """Birakma alanindaki "Hedef: ..." satirini secili cihaza gore guncelle; gonderim eylemleri de buna uyar."""
        if hasattr(self, "drop_zone") and hasattr(self, "device_list"):
            self.drop_zone.set_target(self.device_list.get_selected_device(), self.lang)
            action = getattr(self, "send_action", None)
            if action is not None:
                ready = self.drop_zone.ready
                action.setEnabled(ready)
                action.setToolTip("" if ready else self.drop_zone.target_label.text())

    def _on_files_dropped(self, files: list):
        """Handle files dropped or selected"""
        from os.path import isdir
        lang = self.lang
        
        # Check if any device is selected
        selected_device = self.device_list.get_selected_device()
        
        if not selected_device:
            MessageBox.information(
                self,
                t("msg_target_required_title", lang),
                t("msg_target_files_text", lang)
            )
            return
        
        if not selected_device.is_online:
            MessageBox.warning(
                self,
                t("msg_device_unavailable_title", lang),
                t("msg_device_unavailable_text", lang).format(name=selected_device.name)
            )
            return
        
        # Separate files and folders
        file_list = []
        folder_list = []
        
        for path in files:
            if isdir(path):
                folder_list.append(path)
            else:
                file_list.append(path)
        
        # If there are folders, handle them separately
        if folder_list:
            # If multiple folders or mix of files and folders, handle each folder separately
            for folder_path in folder_list:
                self._on_folder_selected(folder_path)
        
        # If there are regular files, send them
        if file_list:
            self.send_files_requested.emit(file_list, selected_device, "")
            self.statusBar().showMessage(t("sending_files", lang).format(count=len(file_list), device=selected_device.name), 3000)
    
    def _on_folder_selected(self, folder_path: str):
        """Handle folder selected"""
        lang = self.lang
        # Check if any device is selected
        selected_device = self.device_list.get_selected_device()
        
        if not selected_device:
            MessageBox.information(
                self,
                t("msg_target_required_title", lang),
                t("msg_target_folder_text", lang)
            )
            return
        
        if not selected_device.is_online:
            MessageBox.warning(
                self,
                t("msg_device_unavailable_title", lang),
                t("msg_device_unavailable_text", lang).format(name=selected_device.name)
            )
            return
        
        # Scan folder for all files
        from ..utils.helpers import scan_folder
        files = scan_folder(folder_path)
        
        if not files:
            MessageBox.warning(
                self,
                t("msg_folder_empty_title", lang),
                t("msg_folder_empty_text", lang)
            )
            return
        
        # Extract full paths
        file_paths = [full_path for full_path, _ in files]
        file_count = len(file_paths)
        
        # Warn if folder contains more than 10 files
        if file_count > 10:
            reply = MessageBox.question(
                self,
                t("msg_many_files_title", lang),
                t("msg_many_files_confirm", lang).format(count=file_count, name=selected_device.name),
                MessageBox.StandardButton.Yes | MessageBox.StandardButton.No,
                MessageBox.StandardButton.No
            )

            if reply != MessageBox.StandardButton.Yes:
                return
        
        # Store folder info for later use in transfer
        folder_name = basename(folder_path)
        self.statusBar().showMessage(t("sending_folder", lang).format(folder=folder_name, count=file_count, device=selected_device.name), 3000)
        
        # Send files with folder context
        self.send_files_requested.emit(file_paths, selected_device, folder_path)
    
    def _on_device_selected_for_send(self, device: Device):
        """Cihaza çift tık: seç ve (çevrimiçiyse) dosya seçiciyi aç. Çevrimdışıysa yalnızca seçilir; bırakma alanı
        "X çevrimdışı" der ve gönder düğmeleri pasif kalır (diyalog yok)."""
        entry = self.device_list.devices.get(f"{device.ip}:{device.port}")  # çift tıklanan cihazın satırı
        if entry is not None:
            self.device_list.list_widget.setCurrentRow(self.device_list.list_widget.row(entry[0]))
        if device.is_online:
            self._select_files()

    def _open_settings(self):
        """Open settings dialog (Ctrl+, ve başlıktaki Ayarlar). Tek pencere: açıkken yeniden açılmaz."""
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self._settings_dialog = None
        dialog = SettingsDialog(self)
        self._settings_dialog = dialog
        dialog.settings_changed.connect(self._on_settings_changed)
        try:
            dialog.exec()  # İptal/Esc/✕: pencere önizlemeyi kendisi geri alır (reject)
        finally:
            self._settings_dialog = None

    def _on_settings_changed(self):
        """Handle settings changes"""
        self.lang = get_active_language(self.config)
        self._retranslate_ui()
        self._load_theme()
        self._refresh_local_info()
        self._sync_tray_menus()
        self.statusBar().showMessage(t("status_saved", self.lang), 3000)

    def preview_appearance(self, theme: str | None = None, language: str | None = None, accent: str | None = None):
        """Ayarlar penceresindeki canlı önizleme: tema/dil/vurgu kaydedilmeden ana pencerede denenir."""
        if language is not None:
            self.lang = get_active_language(language)
            self._retranslate_ui()
        self.apply_theme(theme or self.config.get('ui', 'theme', 'system'), accent=accent)

    def restore_appearance(self):
        """Önizlemeyi geri al: kayıtlı tema/dil/vurguya dön (Ayarlar'da İptal/Esc/✕)."""
        self.lang = get_active_language(self.config)
        self._retranslate_ui()
        self._load_theme()

    def _retranslate_ui(self):
        lang = self.lang
        install_qt_translations(lang)
        self.title_bar.retranslate(lang)
        self.drop_zone.retranslate(lang)
        self.device_list.retranslate(lang)
        if hasattr(self, "local_info_label"):
            self._refresh_local_info()
        self.transfer_list.retranslate(lang)

        self.file_btn.setText(t('file', lang))
        self.send_action.setText(t('send_file', lang))
        self.exit_action.setText(t('exit', lang))

        if hasattr(self, 'theme_btn'):
            self.theme_btn.setText(t('theme', lang))
            self.theme_btn.setIcon(theme_system_icon())
        if hasattr(self, 'history_action'):
            self.history_action.setText(t("history", lang))
            self.history_action.setIcon(history_icon())
        if hasattr(self, 'theme_menu'):
            self.theme_menu.setTitle(t('theme', lang))
            self.theme_menu.setIcon(theme_system_icon())
        if hasattr(self, 'system_action'):
            self.system_action.setText(t("theme_system", lang))
        if hasattr(self, 'dark_action'):
            self.dark_action.setText(t("theme_dark", lang))
        if hasattr(self, 'light_action'):
            self.light_action.setText(t("theme_light", lang))

        if hasattr(self, 'lang_btn'):
            self.lang_btn.setText(t('language', lang))
        if hasattr(self, 'color_btn'):
            self.color_btn.setText(t('accent', lang))
            for key, act in getattr(self, '_accent_actions', {}).items():
                act.setText(accent_label(key, lang))
        if hasattr(self, 'settings_btn'):
            self.settings_btn.setText(t('settings', lang))
            self.settings_action.setText(t('settings', lang))
        self._update_lang_menu_checks()
        self._update_accent_menu_checks()
        self._refresh_menu_icons()
        self._refresh_drop_target()

        self.about_action.setText(t('about', lang))

        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.retranslate(lang)
            self._sync_tray_menus()

    def _show_history(self):
        """Show transfer history"""
        from .history_dialog import show_history_dialog
        show_history_dialog(self, self.lang)
    
    def _show_about(self):
        """Show about dialog"""
        from ..utils.updater import UpdateChecker
        from .about_dialog import AboutDialog

        checker = UpdateChecker()
        AboutDialog(self, self.lang, checker.get_current_version()).exec()

    def set_update_available(self, version: str = ""):
        """Başlık çubuğundaki "Güncelle · vX" düğmesini göster/gizle."""
        self.update_version = version or ""
        self.title_bar.set_update_available(version)

    def update_connection_status(self, connected: bool):
        """Bağlantı durumu (eski status bar etiketi artık kullanılmıyor)."""
        return

    def update_statistics(self, sent: int, received: int):
        """Update transfer statistics"""
        sent_text = format_bytes(sent)
        received_text = format_bytes(received)
        if hasattr(self, "transfer_list"):
            self.transfer_list.set_statistics(sent_text, received_text)
    
    def add_device(self, device: Device):
        """Add device to list"""
        self.device_list.add_device(device)
    
    def update_device(self, device: Device):
        """Update device in list"""
        self.device_list.update_device(device)
    
    def remove_device(self, device: Device):
        """Remove device from list"""
        self.device_list.remove_device(device)
    
    def _on_refresh_devices(self):
        """Handle refresh devices request"""
        self.refresh_devices_requested.emit()
        self.show_status_message(t("refreshing_devices", self.lang), 2000)
    
    def add_transfer(self, transfer: Transfer):
        """Add transfer to list"""
        self.transfer_list.add_transfer(transfer)
    
    def update_transfer(self, transfer: Transfer):
        """Update transfer in UI list immediately"""
        self.transfer_list.update_transfer(transfer)
    
    def _clear_transfer_list(self):
        """Clear all completed and failed transfers from list"""
        # Get all completed/failed transfers
        to_remove = []
        for transfer_id, (_, widget) in self.transfer_list.transfers.items():
            if widget.transfer.is_complete or widget.transfer.is_failed or widget.transfer.status.value == 'cancelled':
                to_remove.append(transfer_id)
        
        # Remove them
        for transfer_id in to_remove:
            self.transfer_list.remove_transfer(transfer_id)
        
        if to_remove:
            self.statusBar().showMessage(t("list_cleared", self.lang).format(n=len(to_remove)), 3000)
        else:
            self.statusBar().showMessage(t("list_already_clean", self.lang), 2000)

    def clear_all_transfer_history(self):
        """Tepsi menüsünden veya kullanıcı talebiyle transfer listesini ve geçmiş veritabanını temizle"""
        self._clear_transfer_list()
        try:
            from ..models.database import get_database
            get_database().clear_history()
        except Exception:
            pass
        self.show_status_message(t('history_cleared', self.lang), 3000)
    
    def show_notice(self, notice):
        """Sunucudan gelen duyuruyu göster (kullanıcı bu duyuruyu daha önce kapattıysa gösterme)."""
        from ..utils.config import get_config
        if get_config().get('advanced', 'dismissed_notice', '') == notice.id:
            return
        self.notice_bar.show_notice(notice)

    def _on_notice_dismissed(self, notice_id: str):
        from ..utils.config import get_config
        get_config().set('advanced', 'dismissed_notice', notice_id)

    def show_status_message(self, message: str, timeout: int = 3000):
        """Show status message in status bar"""
        self.statusBar().showMessage(message, timeout)
    
    def quit_application(self):
        """Really quit the application"""
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._clear_resize_cursor()
        QApplication.quit()
    
    def changeEvent(self, event: QEvent):
        try:
            if event.type() == QEvent.Type.WindowStateChange:
                if hasattr(self, "title_bar") and hasattr(self.title_bar, "maximize_btn"):
                    if self.isMaximized():
                        self.title_bar.maximize_btn.setText("❐")
                    else:
                        self.title_bar.maximize_btn.setText("□")
                self._position_size_grip()
        except Exception as e:
            self.logger.error(f"Error in changeEvent: {e}")
        super().changeEvent(event)
    
    def closeEvent(self, event):
        """X / Alt+F4: pencere yalnızca tepsiye gizlenir. Uygulamayı gerçekten kapatan yollar: Ctrl+Q, Dosya > Çıkış
        ve tepsi "Çıkış" (`quit_application`); Windows kapanırken/oturum biterken kapanış engellenmez."""
        from PyQt6.QtGui import QGuiApplication
        gui_app = QGuiApplication.instance()
        if gui_app is not None and gui_app.isSavingSession():  # Windows kapanıyor/oturum bitiyor: kapanmayı engelleme
            self._clear_resize_cursor()
            event.accept()
            return
        self._clear_resize_cursor()
        event.ignore()
        self.hide()
