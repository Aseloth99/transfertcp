"""Settings dialog — kompakt, hizalı, kaydırmasız düzen."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QFormLayout,
    QGridLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..utils.config import get_config
from ..utils.helpers import get_hostname, get_local_ip
from ..utils.paths import get_default_download_dir, get_download_folder
from ..utils.ports import DEFAULT_TRANSFER_PORT
from ..utils.locales import AUTO_LANGUAGE, get_active_language, language_choices, t, create_language_icon
from .widgets.stepper_spinbox import StepperSpinBox
from .widgets.glyph_icons import glyph_color
from .icons import trash_icon, history_icon, info_icon
from .chrome_dialog import ChromeDialog
from .message_box import MessageBox
from .palette import ACCENTS, DEFAULT_ACCENT, accent_color, accent_label, is_dark


class AccentSwatch(QAbstractButton):
    """Vurgu rengi örneği: dolu daire; seçiliyken dışında halka. Üzerine gelince büyür."""

    def __init__(self, key: str, color: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._color = QColor(color)
        self.setCheckable(True)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = 9.5 if (self.underMouse() or self.isChecked()) else 8.5
        center = self.rect().center()
        cx, cy = center.x() + 0.5, center.y() + 0.5
        if self.isChecked():
            ring = QColor("#f5f5f5" if is_dark() else "#1a1a1a")
            painter.setPen(QPen(ring, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 12, cy - 12, 24, 24))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class SettingsDialog(ChromeDialog):
    """Ayarlar penceresi (özel üst çubuklu). Tema, dil ve vurgu seçimi ana pencerede canlı önizlenir;
    Kaydet kalıcı yapar, İptal/Esc/✕ eski görünüme döndürür."""

    settings_changed = pyqtSignal()

    _FIELD_H = 36
    _LABEL_W = 145
    _MIN_W = 700
    _MAX_W = 820

    def __init__(self, parent=None):
        self.config = get_config()
        self.lang = get_active_language(self.config)
        super().__init__(parent, t("settings_title", self.lang))
        self._update_checker = None
        self._checking_updates = False
        self._previewed = False
        self._loading = True  # yükleme sırasında önizleme tetiklenmesin
        self._accent_key = DEFAULT_ACCENT
        self._accent_btns: dict[str, AccentSwatch] = {}

        self.body.setObjectName("settingsDialog")
        self.setModal(True)

        self._setup_ui()
        self._load_settings()
        self._loading = False

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self.body)
        root.setContentsMargins(14, 8, 14, 14)
        root.setSpacing(0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("settingsTabs")
        self.tab_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tab_widget.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabBar().setExpanding(True)
        self.tab_widget.tabBar().setDrawBase(False)

        corner = QWidget()
        corner.setObjectName("settingsTabCorner")
        self.tab_widget.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        # "&" sekme başlığında hızlandırıcı sayılıp kaybolmasın ("Network & Advanced"): kaçışlı yazılır
        self.tab_widget.addTab(self._create_general_tab(), t("tab_general", self.lang).replace("&", "&&"))
        self.tab_widget.addTab(self._create_transfer_tab(), t("tab_transfer", self.lang).replace("&", "&&"))
        self.tab_widget.addTab(self._create_advanced_tab(), t("tab_advanced", self.lang).replace("&", "&&"))

        sep = QFrame()
        sep.setObjectName("settingsFooterSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 10, 0, 0)
        footer.setSpacing(8)

        self.reset_btn = QPushButton(t("reset_defaults", self.lang))
        self.reset_btn.setObjectName("settingsFooterBtn")
        self.reset_btn.clicked.connect(self._reset_settings)

        self.about_btn = QPushButton(t("about", self.lang))
        self.about_btn.setIcon(info_icon(accent_color()))
        self.about_btn.setIconSize(QSize(16, 16))
        self.about_btn.setObjectName("settingsFooterBtn")
        self.about_btn.clicked.connect(self._show_about)

        self.cancel_btn = QPushButton(t("cancel", self.lang))
        self.cancel_btn.setObjectName("settingsFooterBtn")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton(t("save", self.lang))
        self.save_btn.setObjectName("settingsFooterBtn")
        self.save_btn.setProperty("class", "primary")
        self.save_btn.clicked.connect(self._save_settings)
        self.save_btn.setDefault(True)

        footer.addWidget(self.reset_btn)
        footer.addWidget(self.about_btn)
        footer.addStretch()
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.save_btn)

        root.addWidget(self.tab_widget)
        root.addWidget(sep)
        root.addLayout(footer)

        for cb in self.findChildren(QCheckBox):
            cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def prepare_content(self) -> None:
        """Pencereyi en yüksek sekmeye göre boyutla — fazla boşluk kalmasın (çerçeve payı dahil)."""
        self.ensurePolished()
        for widget in self.findChildren(QWidget):
            widget.ensurePolished()
        max_w, max_h = self._MIN_W, 0
        current = self.tab_widget.currentIndex()
        for i in range(self.tab_widget.count()):
            self.tab_widget.setCurrentIndex(i)
            page = self.tab_widget.widget(i)
            if page is None:
                continue
            page.adjustSize()
            hint = page.sizeHint()
            max_w = max(max_w, hint.width())
            max_h = max(max_h, hint.height())
        self.tab_widget.setCurrentIndex(current)

        margins = self.body.layout().contentsMargins()
        inner_h = (
            self.tab_widget.tabBar().sizeHint().height()
            + self.save_btn.sizeHint().height()
            + margins.top() + margins.bottom()
            + 28
        )
        chrome = self.chrome_size()
        width = min(max(max_w + margins.left() + margins.right() + 24, self._MIN_W), self._MAX_W)
        height = max_h + inner_h + chrome.height()
        self.setFixedSize(width + chrome.width(), height)

    @staticmethod
    def _page_layout() -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        return layout

    @staticmethod
    def _inner_layout() -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(8)
        return layout

    @staticmethod
    def _finish_page(widget: QWidget, layout: QVBoxLayout) -> QWidget:
        widget.setLayout(layout)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return widget

    def _make_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        return form

    def _form_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("settingsFieldLabel")
        label.setMinimumWidth(self._LABEL_W)
        label.setMaximumWidth(self._LABEL_W)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _prepare_field(self, widget: QWidget) -> QWidget:
        widget.setFixedHeight(self._FIELD_H)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if isinstance(widget, QLineEdit):
            widget.setObjectName("settingsLineEdit")
        elif isinstance(widget, QComboBox):
            widget.setObjectName("settingsCombo")
        elif isinstance(widget, (QSpinBox, StepperSpinBox)):
            widget.setObjectName("settingsSpin")
        return widget

    def _add_form_row(self, form: QFormLayout, label_text: str, field: QWidget):
        form.addRow(self._form_label(label_text), self._prepare_field(field))

    def _add_form_meta_row(self, form: QFormLayout, label_text: str, value: QLabel):
        value.setMinimumHeight(self._FIELD_H)
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.addRow(self._form_label(label_text), value)

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("settingsPage")
        layout = self._page_layout()

        device_group = QGroupBox(t("group_device_settings", self.lang))
        device_inner = self._inner_layout()
        device_form = self._make_form()
        self.device_name_edit = QLineEdit()
        self.device_name_edit.setPlaceholderText(get_hostname())
        self._add_form_row(device_form, t("device_name", self.lang), self.device_name_edit)
        self.hostname_value = QLabel()
        self.hostname_value.setObjectName("settingsMeta")
        self._add_form_meta_row(device_form, t("computer_name", self.lang), self.hostname_value)
        self.local_ip_value = QLabel()
        self.local_ip_value.setObjectName("settingsMeta")
        self.local_ip_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._add_form_meta_row(device_form, t("local_ip", self.lang), self.local_ip_value)
        device_inner.addLayout(device_form)
        device_hint = QLabel(t("device_visible_hint", self.lang))
        device_hint.setObjectName("settingsHint")
        device_hint.setWordWrap(True)
        device_inner.addWidget(device_hint)
        device_group.setLayout(device_inner)

        appearance_group = QGroupBox(t("tab_appearance", self.lang))
        appearance_inner = self._inner_layout()
        appearance_form = self._make_form()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([
            t("theme_system", self.lang),
            t("theme_dark", self.lang),
            t("theme_light", self.lang),
        ])
        self._add_form_row(appearance_form, t("theme", self.lang), self.theme_combo)
        self.language_combo = QComboBox()
        self.language_combo.setIconSize(QSize(22, 15))
        for code, label in language_choices(include_auto=True, lang=self.lang):
            self.language_combo.addItem(create_language_icon(code), label, code)
        self._add_form_row(appearance_form, t("language", self.lang), self.language_combo)

        # Vurgu rengi: 10 renk (5 x 2 ızgara); seçim ana pencerede canlı önizlenir
        accent_field = QWidget()
        accent_field.setStyleSheet("background: transparent;")
        accent_grid = QGridLayout(accent_field)
        accent_grid.setContentsMargins(0, 2, 0, 2)
        accent_grid.setHorizontalSpacing(6)
        accent_grid.setVerticalSpacing(4)
        self.accent_group = QButtonGroup(self)
        self.accent_group.setExclusive(True)
        for i, (key, spec) in enumerate(ACCENTS.items()):
            tip = accent_label(key, self.lang) + (f" {t('accent_default', self.lang)}" if key == DEFAULT_ACCENT else "")
            swatch = AccentSwatch(key, spec["accent"], tip, accent_field)
            swatch.clicked.connect(lambda checked=False, k=key: self._on_accent_chosen(k))
            self.accent_group.addButton(swatch)
            accent_grid.addWidget(swatch, i // 5, i % 5)
            self._accent_btns[key] = swatch
        accent_grid.setColumnStretch(5, 1)
        accent_label_widget = self._form_label(t("accent", self.lang))
        accent_label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        accent_label_widget.setContentsMargins(0, 6, 0, 0)
        appearance_form.addRow(accent_label_widget, accent_field)
        self.theme_combo.currentIndexChanged.connect(self._preview)
        self.language_combo.currentIndexChanged.connect(self._preview)
        appearance_inner.addLayout(appearance_form)
        appearance_group.setLayout(appearance_inner)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(device_group, 1)
        top_row.addWidget(appearance_group, 1)

        startup_group = QGroupBox(t("group_startup", self.lang))
        startup_inner = self._inner_layout()
        startup_inner.setSpacing(6)
        self.auto_start_check = QCheckBox(t("auto_start", self.lang))
        self.auto_start_check.stateChanged.connect(self._on_auto_start_changed)
        self.start_minimized_check = QCheckBox(t("start_minimized", self.lang))
        startup_inner.addWidget(self.auto_start_check)
        startup_inner.addWidget(self.start_minimized_check)
        startup_group.setLayout(startup_inner)

        notif_group = QGroupBox(t("group_notifications", self.lang))
        notif_inner = self._inner_layout()
        notif_inner.setSpacing(6)
        self.notifications_check = QCheckBox(t("show_notifications", self.lang))
        self.sounds_check = QCheckBox(t("play_sounds", self.lang))
        notif_inner.addWidget(self.notifications_check)
        notif_inner.addWidget(self.sounds_check)
        notif_group.setLayout(notif_inner)

        mid_row = QHBoxLayout()
        mid_row.setSpacing(10)
        mid_row.addWidget(startup_group, 1)
        mid_row.addWidget(notif_group, 1)

        layout.addLayout(top_row)
        layout.addLayout(mid_row)
        return self._finish_page(widget, layout)

    def _create_transfer_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("settingsPage")
        layout = self._page_layout()

        folder_group = QGroupBox(t("group_file_location", self.lang))
        folder_inner = self._inner_layout()
        folder_form = self._make_form()
        folder_field = QWidget()
        folder_field_row = QHBoxLayout(folder_field)
        folder_field_row.setContentsMargins(0, 0, 0, 0)
        folder_field_row.setSpacing(8)
        self.download_folder_edit = QLineEdit()
        self.download_folder_edit.setObjectName("settingsLineEdit")
        self.download_folder_edit.setFixedHeight(self._FIELD_H)
        self.download_folder_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.browse_btn = QPushButton(t("browse", self.lang))
        self.browse_btn.setObjectName("settingsFooterBtn")
        self.browse_btn.setFixedHeight(self._FIELD_H)
        self.browse_btn.clicked.connect(self._browse_folder)
        folder_field_row.addWidget(self.download_folder_edit, 1)
        folder_field_row.addWidget(self.browse_btn)
        folder_form.addRow(self._form_label(t("download_folder", self.lang)), folder_field)
        folder_inner.addLayout(folder_form)
        folder_group.setLayout(folder_inner)

        transfer_group = QGroupBox(t("group_transfer_settings", self.lang))
        transfer_inner = self._inner_layout()
        transfer_form = self._make_form()

        self.port_spin = StepperSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(DEFAULT_TRANSFER_PORT)
        self._add_form_row(transfer_form, t("port", self.lang), self.port_spin)

        self.chunk_size_combo = QComboBox()
        self.chunk_size_combo.addItems(["512 KB", "1 MB", "2 MB", "4 MB"])
        self.chunk_size_combo.setCurrentText("1 MB")
        self._add_form_row(transfer_form, t("chunk_size", self.lang), self.chunk_size_combo)

        self.speed_limit_spin = StepperSpinBox()
        self.speed_limit_spin.setRange(0, 1000)
        self.speed_limit_spin.setValue(0)
        self.speed_limit_spin.setSuffix(t("speed_limit_suffix", self.lang))
        self._add_form_row(transfer_form, t("speed_limit", self.lang), self.speed_limit_spin)

        self.max_concurrent_spin = StepperSpinBox()
        self.max_concurrent_spin.setRange(1, 10)
        self.max_concurrent_spin.setValue(3)
        self._add_form_row(transfer_form, t("concurrent_transfers", self.lang), self.max_concurrent_spin)

        transfer_inner.addLayout(transfer_form)
        self.auto_open_check = QCheckBox(t("auto_open", self.lang))
        checkbox_wrap = QWidget()
        checkbox_row = QHBoxLayout(checkbox_wrap)
        checkbox_row.setContentsMargins(0, 4, 0, 0)
        checkbox_row.addWidget(self.auto_open_check)
        self.overwrite_check = QCheckBox(t("overwrite_existing", self.lang))
        checkbox_row.addWidget(self.overwrite_check)
        transfer_inner.addWidget(checkbox_wrap)
        transfer_group.setLayout(transfer_inner)

        layout.addWidget(folder_group)
        layout.addWidget(transfer_group)
        return self._finish_page(widget, layout)

    def _create_advanced_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("settingsPage")
        layout = self._page_layout()

        log_group = QGroupBox(t("group_logging", self.lang))
        log_inner = self._inner_layout()
        log_inner.setSpacing(6)
        self.logging_check = QCheckBox(t("enable_logging", self.lang))
        self.log_level_combo = QComboBox()
        log_levels = [
            ("DEBUG", t("log_debug", self.lang)),
            ("INFO", t("log_info", self.lang)),
            ("WARNING", t("log_warning", self.lang)),
            ("ERROR", t("log_error", self.lang)),
        ]
        for val, label in log_levels:
            self.log_level_combo.addItem(label, val)
        log_inner.addWidget(self.logging_check)
        log_form = self._make_form()
        self._add_form_row(log_form, t("log_level", self.lang), self.log_level_combo)
        log_inner.addLayout(log_form)

        history_row = QHBoxLayout()
        history_row.setSpacing(6)

        self.history_btn = QPushButton(t("history", self.lang))
        self.history_btn.setIcon(history_icon(glyph_color(is_dark(), "muted")))
        self.history_btn.setIconSize(QSize(18, 18))
        self.history_btn.setObjectName("settingsFooterBtn")
        self.history_btn.setFixedHeight(self._FIELD_H)
        self.history_btn.clicked.connect(self._open_history)

        self.clear_history_btn = QPushButton()
        self.clear_history_btn.setIcon(trash_icon("#ef4444"))
        self.clear_history_btn.setIconSize(QSize(18, 18))
        self.clear_history_btn.setObjectName("settingsFooterBtn")
        self.clear_history_btn.setFixedSize(self._FIELD_H, self._FIELD_H)
        self.clear_history_btn.setToolTip(t("clear_history", self.lang))
        self.clear_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_history_btn.clicked.connect(self._clear_history_direct)

        history_row.addWidget(self.history_btn, 1)
        history_row.addWidget(self.clear_history_btn)
        log_inner.addLayout(history_row)
        log_group.setLayout(log_inner)

        update_group = QGroupBox(t("group_updates", self.lang))
        update_inner = self._inner_layout()
        update_inner.setSpacing(6)
        self.auto_update_check = QCheckBox(t("auto_update", self.lang))
        self.auto_update_install = QCheckBox(t("auto_update_install", self.lang))
        self.auto_update_check.toggled.connect(self.auto_update_install.setEnabled)
        for box in (self.auto_update_check, self.auto_update_install):
            box.setToolTip(t("auto_update_tip", self.lang))  # ikisinde de aynı kısa ipucu
        self.update_status = QLabel("")
        self.update_status.setObjectName("updateStatus")
        self.update_status.setWordWrap(True)
        self.check_update_btn = QPushButton(t("check_now", self.lang))
        self.check_update_btn.setObjectName("settingsFooterBtn")
        self.check_update_btn.setFixedHeight(self._FIELD_H)
        from .widgets.update_check_ui import UpdateCheckAnimator
        self.update_check = UpdateCheckAnimator(self.check_update_btn, self.update_status, self)
        self.check_update_btn.clicked.connect(self._check_updates_manually)
        update_inner.addWidget(self.auto_update_check)
        update_inner.addWidget(self.auto_update_install)
        update_inner.addWidget(self.update_status)
        update_inner.addWidget(self.check_update_btn)
        update_group.setLayout(update_inner)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(log_group, 1)
        top_row.addWidget(update_group, 1)

        security_group = QGroupBox(t("security", self.lang))
        security_inner = self._inner_layout()
        security_inner.setSpacing(6)
        self.encryption_check = QCheckBox(t("encryption_enabled", self.lang))
        self.accept_anyone_check = QCheckBox(t("accept_from_anyone", self.lang))
        accept_hint = QLabel(t("accept_from_anyone_hint", self.lang))
        accept_hint.setWordWrap(True)
        accept_hint.setObjectName("settingsHint")
        self.fingerprint_label = QLabel()
        self.fingerprint_label.setWordWrap(True)
        self.fingerprint_label.setObjectName("settingsMeta")
        self.fingerprint_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.trusted_label = QLabel()
        self.trusted_label.setObjectName("settingsMeta")
        self.clear_trusted_btn = QPushButton(t("clear_trusted", self.lang))
        self.clear_trusted_btn.setObjectName("settingsFooterBtn")
        self.clear_trusted_btn.setFixedHeight(self._FIELD_H)
        self.clear_trusted_btn.clicked.connect(self._clear_trusted_devices)

        trusted_row = QHBoxLayout()
        trusted_row.setSpacing(8)
        trusted_row.addWidget(self.trusted_label, 1)
        trusted_row.addWidget(self.clear_trusted_btn)

        security_inner.addWidget(self.encryption_check)
        security_inner.addWidget(self.accept_anyone_check)
        security_inner.addWidget(accept_hint)
        security_inner.addWidget(self.fingerprint_label)
        security_inner.addLayout(trusted_row)
        security_group.setLayout(security_inner)


        layout.addLayout(top_row)
        layout.addWidget(security_group)
        return self._finish_page(widget, layout)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            t("select_download_folder", self.lang),
            self.download_folder_edit.text() or get_default_download_dir(),
        )
        if folder:
            self.download_folder_edit.setText(folder)

    def _load_settings(self):
        self.device_name_edit.setText(self.config.get("general", "device_name", ""))
        self.hostname_value.setText(get_hostname())
        try:
            self.local_ip_value.setText(get_local_ip())
        except Exception:
            self.local_ip_value.setText("—")

        from ..utils.startup import is_in_startup
        self.auto_start_check.setChecked(is_in_startup())
        self.start_minimized_check.setChecked(self.config.get("general", "start_minimized", True))
        self.notifications_check.setChecked(self.config.get("general", "notifications_enabled", True))
        self.sounds_check.setChecked(self.config.get("general", "play_sounds", True))

        self.download_folder_edit.setText(get_download_folder(self.config.get("transfer", "download_folder", "")))
        self.port_spin.setValue(self.config.get("transfer", "port", DEFAULT_TRANSFER_PORT))

        chunk_size = self.config.get("transfer", "chunk_size", 1048576)
        chunk_map = {524288: "512 KB", 1048576: "1 MB", 2097152: "2 MB", 4194304: "4 MB"}
        self.chunk_size_combo.setCurrentText(chunk_map.get(chunk_size, "1 MB"))

        self.speed_limit_spin.setValue(self.config.get("transfer", "speed_limit", 0) // 1048576)
        self.max_concurrent_spin.setValue(self.config.get("transfer", "max_concurrent_transfers", 3))
        self.auto_open_check.setChecked(self.config.get("transfer", "auto_open_file", False))
        self.overwrite_check.setChecked(self.config.get("transfer", "overwrite_existing", True))

        theme = self.config.get("ui", "theme", "system")
        theme_map = {"system": 0, "dark": 1, "light": 2}
        self.theme_combo.setCurrentIndex(theme_map.get(theme, 0))
        lang = self.config.get("ui", "language", AUTO_LANGUAGE)
        lang_idx = self.language_combo.findData(lang)
        if lang_idx >= 0:
            self.language_combo.setCurrentIndex(lang_idx)
        saved_accent = self.config.get("ui", "accent", DEFAULT_ACCENT)
        self._set_accent(saved_accent if saved_accent in ACCENTS else DEFAULT_ACCENT)

        self.logging_check.setChecked(self.config.get("advanced", "enable_logging", True))
        current_log_level = self.config.get("advanced", "log_level", "WARNING")
        log_idx = self.log_level_combo.findData(current_log_level)
        if log_idx >= 0:
            self.log_level_combo.setCurrentIndex(log_idx)
        else:
            self.log_level_combo.setCurrentText(current_log_level)
        self.auto_update_check.setChecked(self.config.get("advanced", "auto_update_check", True))
        self.auto_update_install.setChecked(self.config.get("advanced", "auto_update_install", True))
        self.auto_update_install.setEnabled(self.auto_update_check.isChecked())
        self._show_update_status()
        self.encryption_check.setChecked(self.config.get("advanced", "encryption_enabled", True))
        self.accept_anyone_check.setChecked(self.config.get("advanced", "accept_from_anyone", False))
        self._refresh_security_labels()

    def _save_settings(self):
        self.config.set("general", "device_name", self.device_name_edit.text())

        from ..utils.startup import add_to_startup, remove_from_startup
        if self.auto_start_check.isChecked():
            start_minimized = self.start_minimized_check.isChecked()
            if add_to_startup(minimized=start_minimized):
                self.config.set("general", "auto_start", True)
            else:
                MessageBox.warning(
                    self,
                    t("warning", self.lang),
                    t("autostart_failed", self.lang),
                )
                self.auto_start_check.setChecked(False)
        else:
            remove_from_startup()
            self.config.set("general", "auto_start", False)

        self.config.set("general", "start_minimized", self.start_minimized_check.isChecked())
        self.config.set("general", "notifications_enabled", self.notifications_check.isChecked())
        self.config.set("general", "play_sounds", self.sounds_check.isChecked())

        self.config.set("transfer", "download_folder", self.download_folder_edit.text())
        self.config.set("transfer", "port", self.port_spin.value())

        chunk_map = {"512 KB": 524288, "1 MB": 1048576, "2 MB": 2097152, "4 MB": 4194304}
        self.config.set("transfer", "chunk_size", chunk_map.get(self.chunk_size_combo.currentText(), 1048576))
        self.config.set("transfer", "speed_limit", self.speed_limit_spin.value() * 1048576)
        self.config.set("transfer", "max_concurrent_transfers", self.max_concurrent_spin.value())
        self.config.set("transfer", "auto_open_file", self.auto_open_check.isChecked())
        self.config.set("transfer", "overwrite_existing", self.overwrite_check.isChecked())

        self.config.set("ui", "theme", self._selected_theme())
        lang = self.language_combo.currentData() or self.lang
        self.config.set("ui", "language", lang)
        self.config.set("ui", "accent", self._accent_key)

        enable_logging = self.logging_check.isChecked()
        log_level = self.log_level_combo.currentData() or "WARNING"
        self.config.set("advanced", "enable_logging", enable_logging)
        self.config.set("advanced", "log_level", log_level)
        self.config.set("advanced", "auto_update_check", self.auto_update_check.isChecked())
        self.config.set("advanced", "auto_update_install", self.auto_update_install.isChecked())
        self.config.set("advanced", "encryption_enabled", self.encryption_check.isChecked())
        self.config.set("advanced", "accept_from_anyone", self.accept_anyone_check.isChecked())

        from ..utils.logger import get_logger
        logger = get_logger()
        logger.set_level(log_level)
        logger.set_enabled(enable_logging)

        self.settings_changed.emit()
        self.accept()

    # ------------------------------------------------------------------ canlı önizleme
    def _set_accent(self, key: str) -> None:
        self._accent_key = key
        button = self._accent_btns.get(key)
        if button is not None:
            button.setChecked(True)

    def _on_accent_chosen(self, key: str) -> None:
        self._set_accent(key)
        self._preview()

    def _selected_theme(self) -> str:
        idx = self.theme_combo.currentIndex()
        return ["system", "dark", "light"][idx] if 0 <= idx <= 2 else "system"

    def _preview(self, *_args) -> None:
        """Tema/dil/vurgu seçimini kaydetmeden ana pencerede dener; çerçevemiz de yeni vurguyu alır."""
        if self._loading:
            return
        owner = self.parent()
        preview = getattr(owner, "preview_appearance", None)
        if callable(preview):
            self._previewed = True
            preview(theme=self._selected_theme(), language=self.language_combo.currentData() or AUTO_LANGUAGE,
                    accent=self._accent_key)
            self.refresh_chrome()
            self.about_btn.setIcon(info_icon(accent_color()))
            self.history_btn.setIcon(history_icon(glyph_color(is_dark(), "muted")))

    def reject(self) -> None:  # noqa: D401
        """İptal / Esc / ✕: önizlenen tema, dil ve vurgu eski hâline döner."""
        owner = self.parent()
        restore = getattr(owner, "restore_appearance", None)
        if callable(restore) and getattr(self, "_previewed", False):
            restore()
        super().reject()

    def _get_update_checker(self):
        parent_window = self.parent()
        if parent_window is not None and hasattr(parent_window, "update_checker"):
            return parent_window.update_checker
        from ..utils.updater import UpdateChecker
        return UpdateChecker()

    def _on_check_message(self, level: str, _title: str, _message: str):
        if level != "info":
            self._check_failed = True

    def _check_updates_manually(self):
        if self._checking_updates:
            return
        checker = self._get_update_checker()
        if checker is None:
            return
        if self._update_checker is not checker:
            if self._update_checker is not None:
                try:
                    self._update_checker.manual_check_finished.disconnect(self._on_manual_update_done)
                    self._update_checker.check_message.disconnect(self._on_check_message)
                except TypeError:
                    pass
            self._update_checker = checker
            checker.manual_check_finished.connect(self._on_manual_update_done)
            checker.check_message.connect(self._on_check_message)

        self._checking_updates = True
        self._check_failed = False
        self.update_status.setVisible(True)
        self.update_check.start(t("checking_updates", self.lang))
        checker.check_for_updates(show_message=True)

    def _pending_update_version(self) -> str:
        pending = getattr(self.parent(), "update_version", "")
        return pending if isinstance(pending, str) else ""

    def _show_update_status(self, failed: bool = False, checked: bool = False):
        """Pop-up yerine ayarlardaki durum satırı: yeni sürüm / güncel / denetlenemedi."""
        pending = self._pending_update_version()
        if pending:
            text = t("update_new_version", self.lang).format(version=pending)
        elif failed:
            text = t("update_status_failed", self.lang)
        elif checked:
            from ..utils.updater import UpdateChecker
            text = t("update_status_current", self.lang).format(version=UpdateChecker().get_current_version())
        else:
            text = ""
        self.update_status.setText(text)
        self.update_status.setVisible(bool(text))

    def _on_manual_update_done(self):
        self._checking_updates = False
        pending = self._pending_update_version()
        if pending:
            self.update_check.finish("new", t("update_new_version", self.lang).format(version=pending))
        elif getattr(self, "_check_failed", False):
            self.update_check.finish("fail", t("update_status_failed", self.lang))
        else:
            from ..utils.updater import UpdateChecker
            version = UpdateChecker().get_current_version()
            self.update_check.finish("ok", t("update_status_current", self.lang).format(version=version))

    def _on_auto_start_changed(self, state):
        pass

    def _refresh_security_labels(self):
        from ..core.crypto import format_fingerprint, get_local_fingerprint, list_trusted_devices
        try:
            fingerprint = format_fingerprint(get_local_fingerprint())
        except Exception:
            fingerprint = "—"
        self.fingerprint_label.setText(f"{t('your_fingerprint', self.lang)} {fingerprint}")
        count = len(list_trusted_devices())
        self.trusted_label.setText(t("trusted_count", self.lang).format(count=count))

    def _clear_trusted_devices(self):
        from .trust_dialog import ask_confirm
        from ..core.crypto import clear_trusted_devices
        if not ask_confirm(
            self,
            t("clear_trusted", self.lang),
            t("trusted_clear_confirm", self.lang),
            t("yes", self.lang),
            t("no", self.lang),
        ):
            return
        clear_trusted_devices()
        self._refresh_security_labels()  # sonuç satır içi: "0 güvenilen cihaz"

    def _open_history(self):
        from .history_dialog import show_history_dialog
        show_history_dialog(self, self.lang)

    def _clear_history_direct(self):
        from .trust_dialog import ask_confirm
        if not ask_confirm(
            self,
            t("clear_history", self.lang),
            t("clear_history_confirm", self.lang),
            t("yes", self.lang),
            t("no", self.lang),
        ):
            return
        from ..models.database import get_database
        get_database().clear_history()
        self.clear_history_btn.setEnabled(False)  # sonuç satır içi: temizlenecek bir şey kalmadı
        self.clear_history_btn.setToolTip(t("history_cleared", self.lang))

    def _show_about(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "_show_about"):
            parent._show_about()

    def _reset_settings(self):
        self.config.reset_to_default()
        self._load_settings()
