"""System tray icon"""

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QPixmap, QPainter, QColor, QFont, QCursor, QGuiApplication
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QPoint, QSize, QTimer
from os.path import exists
from ..utils.locales import configured_language, get_active_language, language_choices, t, create_language_icon
from ..utils.helpers import get_asset_path
from ..utils.platform_utils import is_windows
from ..utils.theme import ui_font_families
from .icons import (
    theme_system_icon, theme_dark_icon, theme_light_icon,
    eye_icon, settings_gear_icon, door_exit_icon,
    globe_icon, update_arrow_icon,
)
from .palette import accent_color


class TrayIcon(QObject):
    """System tray icon with menu"""
    
    show_window = pyqtSignal()
    hide_window = pyqtSignal()
    open_settings = pyqtSignal()
    quit_app = pyqtSignal()
    clear_history = pyqtSignal()
    update_requested = pyqtSignal()
    theme_selected = pyqtSignal(str)
    language_selected = pyqtSignal(str)
    
    def __init__(self, parent=None, lang: str = "tr"):
        super().__init__(parent)
        self.lang = lang
        self.tray = None
        self.menu = None
        self._update_available = False  # menü yeniden kurulsa da durum burada saklanır
        self._update_version = ""
        self.window_visible = lambda: True  # uygulama bağlar: pencere şu an görünür mü? (Göster/Gizle etiketi için)
        self._load_base_pixmap()
        self._create_icon()
        self._create_menu()

    def _load_base_pixmap(self):
        icon_path = get_asset_path("icons", "app_icon.png")
        if exists(icon_path):
            self.base_pixmap = QPixmap(icon_path).scaled(
                64, 64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        else:
            self.base_pixmap = QPixmap(64, 64)
            self.base_pixmap.fill(Qt.GlobalColor.transparent)
            p = QPainter(self.base_pixmap)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(33, 150, 243))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(4, 4, 56, 56, 14, 14)
            p.end()
    
    def _create_icon(self):
        """Create tray icon using application icon"""
        icon = QIcon(self.base_pixmap)
        self.tray = QSystemTrayIcon(icon)
        self.tray.setToolTip("TransferTCP")
        
        self.tray.activated.connect(self._on_activated)
    
    def _on_activated(self, reason):
        """Tepsi ikonuna tıklanınca pencereyi aç."""
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.show_window.emit()
    
    def _create_menu(self):
        """Tepsi menüsü iskeleti (tüm uygulamalarda aynı):
        [Güncelle · vX] · — · Göster/Gizle · — · Ayarlar · Tema ▸ · Dil ▸ · — · Çıkış"""
        menu = QMenu()
        self.menu = menu
        accent = accent_color()

        # Güncelleme satırı menünün EN ÜSTÜNDE (altında ayırıcı); yalnızca güncelleme bekliyorsa görünür
        self.update_action = QAction(update_arrow_icon(accent), t("tray_update_now", self.lang), menu)
        update_font = self.update_action.font()
        update_font.setBold(True)
        self.update_action.setFont(update_font)
        self.update_action.setVisible(False)
        self.update_action.triggered.connect(self.update_requested.emit)
        menu.addAction(self.update_action)
        self.update_separator = menu.addSeparator()
        self.update_separator.setVisible(False)

        # Pencere durumuna göre dinamik: açıkken "Gizle", gizliyken "Göster"
        self.show_action = QAction(eye_icon(accent), t("tray_show", self.lang), menu)
        self.show_action.triggered.connect(self._toggle_window)
        menu.addAction(self.show_action)

        menu.addSeparator()

        self.settings_action = QAction(settings_gear_icon(accent), t("settings", self.lang), menu)
        self.settings_action.triggered.connect(self.open_settings.emit)
        menu.addAction(self.settings_action)

        self.theme_menu = menu.addMenu(t("theme", self.lang))
        self.theme_menu.setIcon(theme_system_icon())
        self.theme_group = QActionGroup(menu)
        self.theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        theme_icons = {
            "system": theme_system_icon,
            "dark": theme_dark_icon,
            "light": theme_light_icon,
        }
        for key in ("system", "dark", "light"):
            act = QAction(theme_icons[key](), t(f"theme_{key}", self.lang), menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, k=key: self.theme_selected.emit(k) if checked else None)
            self.theme_group.addAction(act)
            self.theme_menu.addAction(act)
            self._theme_actions[key] = act

        self.lang_menu = menu.addMenu(t("language", self.lang))
        self.lang_menu.setIcon(globe_icon(accent))
        self.lang_group = QActionGroup(menu)
        self.lang_group.setExclusive(True)
        self._lang_actions: dict[str, QAction] = {}
        for code, label in language_choices(include_auto=True, lang=self.lang):
            act = QAction(create_language_icon(code), label, menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, c=code: self.language_selected.emit(c) if checked else None)
            self.lang_group.addAction(act)
            self.lang_menu.addAction(act)
            self._lang_actions[code] = act

        menu.addSeparator()

        self.quit_action = QAction(door_exit_icon("#ef4444"), t("tray_quit", self.lang), menu)
        self.quit_action.triggered.connect(self.quit_app.emit)
        menu.addAction(self.quit_action)

        menu.aboutToShow.connect(self._on_menu_about_to_show)
        self.theme_menu.aboutToShow.connect(self._sync_menu_state)
        self.lang_menu.aboutToShow.connect(self._sync_menu_state)
        self.tray.setContextMenu(menu)
        self.sync_state = getattr(self, "sync_state", None)  # yeniden kurulumda dışarıdan bağlanan eşitleyici korunur
        self._apply_update_state()  # menü sonradan (yeniden) kurulsa da güncelleme satırı doğru durumda
        self.refresh_window_action()

    # ------------------------------------------------------------------ Göster / Gizle
    def _window_is_visible(self) -> bool:
        try:
            return bool(self.window_visible())
        except Exception:
            return True

    def refresh_window_action(self) -> None:
        """"Göster" ↔ "Gizle": etiket pencerenin o anki durumuna göre (menü açılırken ve dil değişince çağrılır)."""
        action = getattr(self, "show_action", None)
        if action is not None:
            action.setText(t("tray_hide" if self._window_is_visible() else "tray_show", self.lang))

    def _toggle_window(self) -> None:
        if self._window_is_visible():
            self.hide_window.emit()
        else:
            self.show_window.emit()

    def refresh_icons(self) -> None:
        """Vurgu değişince menü simgeleri yeni vurguyla yeniden boyanır."""
        accent = accent_color()
        self.show_action.setIcon(eye_icon(accent))
        self.settings_action.setIcon(settings_gear_icon(accent))
        self.lang_menu.setIcon(globe_icon(accent))
        self.update_action.setIcon(update_arrow_icon(accent))

    def set_theme_choice(self, theme: str):
        theme_icons = {
            "system": theme_system_icon,
            "dark": theme_dark_icon,
            "light": theme_light_icon,
        }
        if hasattr(self, "theme_menu"):
            self.theme_menu.setIcon(theme_icons.get(theme, theme_system_icon)())
        for key, act in self._theme_actions.items():
            act.setChecked(key == theme)
            act.setText(t(f"theme_{key}", self.lang))

    def set_language_choice(self, lang_choice: str, active_lang: str | None = None):
        active_lang = active_lang or configured_language()
        if hasattr(self, "lang_menu"):
            self.lang_menu.setIcon(globe_icon(accent_color()))
        labels = {code: label for code, label in language_choices(include_auto=True, lang=active_lang)}
        for code, act in self._lang_actions.items():
            act.setChecked(code == lang_choice)
            act.setText(labels.get(code, code))
            act.setIcon(create_language_icon(code))

    def _sync_menu_state(self):
        sync = getattr(self, "sync_state", None)
        if callable(sync):
            sync()

    def _on_menu_about_to_show(self):
        self.refresh_window_action()
        self.refresh_icons()
        self._sync_menu_state()
        self._fix_tray_menu_pos()

    def retranslate(self, lang: str = "tr"):
        self.lang = lang
        self.refresh_window_action()
        if hasattr(self, "theme_menu"):
            self.theme_menu.setTitle(t("theme", lang))
            self.theme_menu.setIcon(theme_system_icon())
        if hasattr(self, "lang_menu"):
            self.lang_menu.setTitle(t("language", lang))
        self.settings_action.setText(t("settings", lang))
        self.quit_action.setText(t("tray_quit", lang))
        self._apply_update_state()
        for key, act in self._theme_actions.items():
            act.setText(t(f"theme_{key}", lang))

    def set_update_available(self, available: bool, version: str = ""):
        """Bekleyen güncellemeyi menünün en üstünde "Güncelle · v{sürüm}" olarak göster (False: gizle)."""
        self._update_available = bool(available)
        if version:
            self._update_version = str(version)
        elif not available:
            self._update_version = ""
        self._apply_update_state()

    def _apply_update_state(self):
        """Saklanan güncelleme durumunu satıra ve ipucuna uygula (dil değişiminde ve menü kurulunda da çağrılır)."""
        action = getattr(self, "update_action", None)
        if action is None:
            return
        shown = self._update_available
        if self._update_version:
            action.setText(t("tray_update_now", self.lang).format(version=self._update_version))
        else:
            action.setText(t("update_now", self.lang))
        action.setVisible(shown)
        separator = getattr(self, "update_separator", None)
        if separator is not None:
            separator.setVisible(shown)
        if self.tray is not None:
            if shown and self._update_version:
                self.tray.setToolTip(t("tray_update_tooltip", self.lang).format(version=self._update_version))
            else:
                self.tray.setToolTip("TransferTCP")
    
    def show(self):
        """Show tray icon"""
        if self.tray:
            self.tray.show()
    
    def hide(self):
        """Hide tray icon"""
        if self.tray:
            self.tray.hide()
    
    @staticmethod
    def is_system_tray_available() -> bool:
        """İşletim sisteminde tepsi var mı? (GNOME'da AppIndicator/StatusNotifier eklentisi gerekir.)"""
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            return False

    def is_available(self) -> bool:
        """Bu uygulamanın tepsi simgesi gerçekten kullanılabilir mi (pencere tepsiye saklanabilir mi)?"""
        return self.tray is not None and self.is_system_tray_available()

    def show_message(self, title: str, message: str, icon=QSystemTrayIcon.MessageIcon.Information) -> bool:
        """Show balloon message. Tepsi yoksa False döner (çağıran yedek bildirim yolunu dener)."""
        if not self.is_available():
            return False
        if not self.tray.isVisible():
            self.tray.show()
        self.tray.showMessage(title, message, icon, 3000)
        return True
    
    def set_tooltip(self, tooltip: str):
        """Set tooltip text"""
        if self.tray:
            self.tray.setToolTip(tooltip)
    
    def update_icon_with_badge(self, count: int):
        """Update icon with transfer count badge"""
        if getattr(self, '_current_badge_count', None) == count:
            return
        self._current_badge_count = count
        if count <= 0:
            if self.tray:
                self.tray.setIcon(QIcon(self.base_pixmap))
            return
            
        pixmap = self.base_pixmap.copy()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setBrush(QColor(239, 68, 68))
        painter.setPen(QColor(255, 255, 255))
        painter.drawEllipse(38, 2, 24, 24)
        
        font = QFont()
        font.setFamilies(ui_font_families())  # Windows: "Segoe UI" önce (eskisiyle aynı)
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(38, 2, 24, 24, Qt.AlignmentFlag.AlignCenter, 
                       str(min(count, 9)) if count < 10 else "9+")
        
        painter.end()
        
        icon = QIcon(pixmap)
        if self.tray:
            self.tray.setIcon(icon)
    
    def _tray_menu_pos(self) -> QPoint:
        pos = QCursor.pos()
        hint = self.menu.sizeHint() if self.menu is not None else QSize(160, 200)
        width = hint.width()
        height = hint.height()
        screen = QGuiApplication.screenAt(pos)
        if screen is not None:
            bounds = screen.availableGeometry()
            x = min(max(pos.x(), bounds.left()), max(bounds.left(), bounds.right() - width))
            y = min(max(pos.y(), bounds.top()), max(bounds.top(), bounds.bottom() - height))
            return QPoint(x, y)
        return pos

    def _fix_tray_menu_pos(self):
        # Yalnızca Windows'ta: macOS'ta menü yerel NSMenu'dür, Wayland'da açılır pencere
        # istemci tarafından taşınamaz (Qt zaten doğru konumlar).
        if not is_windows():
            return
        pos = self._tray_menu_pos()
        QTimer.singleShot(0, lambda p=pos: self.menu.move(p) if self.menu else None)
