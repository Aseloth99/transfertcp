"""Transfer geçmişi penceresi: özel üst çubuklu; geçmiş boşken başlık + ne yapılacağı (rehberli boş durum)."""

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QWidget
from ..utils.locales import t, get_active_language
from ..utils.helpers import format_bytes
from ..utils.config import get_config
from .chrome_dialog import ChromeDialog
from .trust_dialog import ask_confirm
from .icons import trash_icon


class HistoryDialog(ChromeDialog):
    """Son 100 transferin listesi; temizleme düğmesi onay ister."""

    def __init__(self, parent=None, lang: str | None = None) -> None:
        if lang is None:
            lang = get_active_language(get_config())
        super().__init__(parent, t("history_dialog_title", lang))
        self.lang = lang
        self.body.setObjectName("settingsDialog")  # alt düğmeler ayarlardakiyle aynı stili alır

        from ..models.database import get_database
        self._db = get_database()
        history = self._db.get_transfer_history(limit=100)

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMinimumSize(660, 380)
        layout.addWidget(self.text_edit, 1)

        # Boş durum: başlık + ne yapılacağı (cihaz/transfer listeleriyle aynı biçim)
        self.empty_box = QWidget()
        self.empty_box.setMinimumSize(660, 380)
        empty_lay = QVBoxLayout(self.empty_box)
        empty_lay.setContentsMargins(24, 24, 24, 24)
        empty_lay.setSpacing(6)
        empty_lay.addStretch(1)
        self.empty_title = QLabel(t("history_empty_title", lang))
        self.empty_title.setObjectName("deviceName")  # cihaz listesinin boş durumuyla aynı başlık/ipucu biçimi
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setWordWrap(True)
        self.empty_hint = QLabel(t("history_empty_hint", lang))
        self.empty_hint.setObjectName("deviceInfo")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_lay.addWidget(self.empty_title)
        empty_lay.addWidget(self.empty_hint)
        empty_lay.addStretch(1)
        layout.addWidget(self.empty_box, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(trash_icon("#ef4444"))
        self.clear_btn.setIconSize(QSize(18, 18))
        self.clear_btn.setObjectName("settingsFooterBtn")
        self.clear_btn.setFixedSize(34, 34)
        self.clear_btn.setToolTip(t("clear_history", lang))
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._do_clear)

        self.close_btn = QPushButton(t("close", lang))
        self.close_btn.setObjectName("settingsFooterBtn")
        self.close_btn.setFixedHeight(34)
        self.close_btn.clicked.connect(self.close)

        footer.addWidget(self.clear_btn)
        footer.addStretch()
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)

        self._show_history(history)

    def _format(self, history) -> str:
        lang = self.lang
        text = f"{t('history_header', lang)}\n" + "=" * 70 + "\n\n"
        for item in history:
            status_icon = "✓" if item['status'] == 'completed' else "✕"
            is_send = item['direction'] in ('send', 'outgoing')
            dir_str = t("history_outgoing" if is_send else "history_incoming", lang)
            text += f"{status_icon} {dir_str} {item['filename']}\n"
            text += f"   {item['device_name']} ({item['device_ip']})\n"
            text += f"   {format_bytes(item['bytes_transferred'])}\n"
            text += f"   {item['start_time']}\n\n"
        return text

    def _show_history(self, history) -> None:
        has_items = bool(history)
        if has_items:
            self.text_edit.setPlainText(self._format(history))
        else:
            self.text_edit.clear()
        self.text_edit.setVisible(has_items)
        self.empty_box.setVisible(not has_items)
        self.clear_btn.setEnabled(has_items)

    def _do_clear(self) -> None:
        if not ask_confirm(
            self,
            t("clear_history", self.lang),
            t("clear_history_confirm", self.lang),
            t("yes", self.lang),
            t("no", self.lang),
        ):
            return
        self._db.clear_history()
        self._show_history([])  # sonuç satır içi görünür (boş durum): ayrıca bilgi kutusu açılmaz

    def prepare_content(self) -> None:
        self.fit_content(extra_w=8, extra_h=8)


def show_history_dialog(parent=None, lang: str = None) -> None:
    """Transfer geçmişini gösteren pencereyi açar."""
    HistoryDialog(parent, lang).exec()
