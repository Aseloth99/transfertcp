"""Onay pencereleri: tümü özel üst çubuklu (işletim sistemi başlık çubuğu ve yerel kutu yok)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .chrome_dialog import ChromeDialog
from .message_box import MessageBox
from .widgets.tone import set_tone


def _compact_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("dialogCompactBtn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(30)
    return btn


def ask_confirm(parent, title: str, text: str, yes_text: str, no_text: str) -> bool:
    """Evet/Hayır onayı (geri alınamaz işlemler için). Varsayılan (Enter) ve Esc: Hayır."""
    box = MessageBox(parent)
    box.setIcon(MessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(yes_text, MessageBox.ButtonRole.YesRole)
    no = box.addButton(no_text, MessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes


def show_info(parent, title: str, text: str, ok_text: str | None = None) -> None:
    """Tek düğmeli bilgi kutusu (düğme metni verilmezse uygulama dilinde "Tamam")."""
    box = MessageBox(parent)
    box.setIcon(MessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(text)
    if ok_text:
        box.addButton(ok_text, MessageBox.ButtonRole.AcceptRole)
    else:
        box.addButton(MessageBox.StandardButton.Ok)
    box.exec()


class TrustDeviceDialog(ChromeDialog):
    """Gelen transfer: bu cihaza güvenilsin mi? `approved` sonucu tutar."""

    def __init__(self, title: str, body: str, fingerprint: str,
                 accept_text: str, reject_text: str, parent=None) -> None:
        super().__init__(parent, title)
        self.setModal(True)
        self.approved = False

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        text = QLabel(body)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setStyleSheet("font-size: 11pt;")
        text.setMinimumWidth(380)
        layout.addWidget(text)

        fp = QLabel(fingerprint)
        fp.setWordWrap(True)
        fp.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_tone(fp, "muted")
        fp.setStyleSheet("font-size: 9pt;")
        layout.addWidget(fp)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        reject = _compact_button(reject_text)
        accept = _compact_button(accept_text)
        accept.setProperty("class", "primary")
        accept.setDefault(True)
        reject.clicked.connect(self._reject)
        accept.clicked.connect(self._accept)
        row.addWidget(reject)
        row.addWidget(accept)
        layout.addLayout(row)

    def _accept(self) -> None:
        self.approved = True
        self.accept()

    def _reject(self) -> None:
        self.approved = False
        self.reject()
