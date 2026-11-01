"""IP ile cihaz ekleme penceresi (yayınsız ağlar için): özel üst çubuklu, hata satır içinde gösterilir (kutu açılmaz)."""

from __future__ import annotations

import ipaddress

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ..utils.locales import t
from ..utils.ports import DEFAULT_TRANSFER_PORT
from .chrome_dialog import ChromeDialog
from .widgets.stepper_spinbox import StepperSpinBox
from .widgets.tone import set_tone


class ManualDeviceDialog(ChromeDialog):
    def __init__(self, parent=None, lang: str = "tr", default_port: int = DEFAULT_TRANSFER_PORT) -> None:
        super().__init__(parent, t("manual_device_title", lang))
        self.lang = lang
        self.setModal(True)
        self.body.setObjectName("manualDeviceDialog")

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        hint = QLabel(t("manual_device_hint", lang))
        hint.setObjectName("manualDialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QVBoxLayout()
        form.setSpacing(8)

        ip_label = QLabel(t("ip_address", lang))
        ip_label.setObjectName("manualFieldLabel")
        self.ip_edit = QLineEdit()
        self.ip_edit.setObjectName("manualField")
        self.ip_edit.setPlaceholderText("192.168.1.42")
        self.ip_edit.textChanged.connect(lambda _text: self._show_error(""))
        form.addWidget(ip_label)
        form.addWidget(self.ip_edit)

        # Geçersiz IP: pencere açık kalır, neden alanın hemen altında yazar
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        set_tone(self.error_label, "err")
        self.error_label.setVisible(False)
        form.addWidget(self.error_label)

        name_label = QLabel(t("device_alias", lang))
        name_label.setObjectName("manualFieldLabel")
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("manualField")
        self.name_edit.setPlaceholderText(t("device_alias_placeholder", lang))
        form.addWidget(name_label)
        form.addWidget(self.name_edit)

        port_label = QLabel(t("port", lang))
        port_label.setObjectName("manualFieldLabel")
        self.port_spin = StepperSpinBox()
        self.port_spin.setObjectName("manualField")
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.port_spin.setToolTip(t("port_hint", lang))
        self.port_spin.setValue(default_port)
        form.addWidget(port_label)
        form.addWidget(self.port_spin)
        layout.addLayout(form)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.cancel_button = QPushButton(t("cancel", lang))
        self.cancel_button.setObjectName("manualSecondaryButton")
        self.cancel_button.clicked.connect(self.reject)
        self.add_button = QPushButton(t("add_device", lang))
        self.add_button.setObjectName("manualPrimaryButton")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.try_accept)
        row.addWidget(self.cancel_button)
        row.addWidget(self.add_button)
        layout.addSpacing(4)
        layout.addLayout(row)

    def try_accept(self) -> None:
        """Geçerli bir IP girildiyse kabul eder; değilse satır içi hata gösterip pencereyi açık tutar."""
        try:
            ipaddress.ip_address(self.ip_edit.text().strip())
        except ValueError:
            self._show_error(t("invalid_ip", self.lang))
            self.ip_edit.setFocus()
            self.ip_edit.selectAll()
            return
        self.accept()

    def _show_error(self, text: str) -> None:
        if self.error_label.isVisible() == bool(text) and self.error_label.text() == text:
            return
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))
        if self._prepared:  # pencere açıkken içerik değişti: sabit boyutu yeniden hesapla
            self.prepare_content()

    def result_values(self) -> tuple[str, str, int]:
        ip_text = self.ip_edit.text().strip()
        return ip_text, self.name_edit.text().strip() or ip_text, self.port_spin.value()

    def prepare_content(self) -> None:
        self.fit_content(min_content_w=430, extra_w=4, extra_h=4)
