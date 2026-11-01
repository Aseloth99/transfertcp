"""İlk kurulum karşılama penceresi: cihaz adı + indirme klasörü + "Başla" tek pencerede (eski üç ardışık kutunun yerine).

Özel üst çubuklu. Esc / ✕ ile kapatmak "varsayılanlarla devam" demektir (cihaz adı = bilgisayar adı, klasör = İndirilenler):
kullanıcı hiçbir kutuyla yüzleşmeden uygulamaya girer; her şey sonradan Ayarlar'dan değişir.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ..utils.locales import t
from .chrome_dialog import ChromeDialog
from .widgets.tone import set_tone


class WelcomeDialog(ChromeDialog):
    def __init__(self, parent=None, lang: str = "tr", default_name: str = "", default_folder: str = "") -> None:
        super().__init__(parent, t("welcome_title", lang))
        self.lang = lang
        self.default_name = default_name
        self.default_folder = default_folder
        self.started = False  # "Başla"ya basıldı mı (Esc/✕ = varsayılanlarla devam)
        self.setModal(True)
        self.body.setObjectName("manualDeviceDialog")  # alan/düğme stilleri IP ile cihaz ekleme penceresiyle ortak

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        intro = QLabel(t("welcome_intro", lang))
        intro.setWordWrap(True)
        intro.setObjectName("welcomeIntro")
        layout.addWidget(intro)

        name_label = QLabel(t("device_name", lang))
        name_label.setObjectName("manualFieldLabel")
        self.name_edit = QLineEdit(default_name)
        self.name_edit.setObjectName("manualField")
        self.name_edit.setPlaceholderText(default_name)
        layout.addSpacing(4)
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name_box.addWidget(name_label)
        name_box.addWidget(self.name_edit)
        layout.addLayout(name_box)

        folder_label = QLabel(t("download_folder", lang))
        folder_label.setObjectName("manualFieldLabel")
        self.folder_edit = QLineEdit(default_folder)
        self.folder_edit.setObjectName("manualField")
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setCursorPosition(0)
        self.browse_btn = QPushButton(t("browse", lang))
        self.browse_btn.setObjectName("manualSecondaryButton")
        self.browse_btn.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_btn)
        folder_box = QVBoxLayout()
        folder_box.setSpacing(4)
        folder_box.addWidget(folder_label)
        folder_box.addLayout(folder_row)
        layout.addLayout(folder_box)

        tip = QLabel(t("welcome_tip", lang))
        tip.setWordWrap(True)
        set_tone(tip, "muted")
        layout.addSpacing(6)
        layout.addWidget(tip)

        row = QHBoxLayout()
        row.addStretch(1)
        self.start_btn = QPushButton(t("welcome_start", lang))
        self.start_btn.setObjectName("manualPrimaryButton")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._start)
        row.addWidget(self.start_btn)
        layout.addSpacing(6)
        layout.addLayout(row)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, t("select_download_folder", self.lang),
                                                  self.folder_edit.text() or self.default_folder)
        if folder:
            self.folder_edit.setText(folder)
            self.folder_edit.setCursorPosition(0)

    def _start(self) -> None:
        self.started = True
        self.accept()

    def values(self) -> tuple[str, str]:
        """(cihaz adı, indirme klasörü): "Başla" ile seçilenler; Esc/✕ ile varsayılanlar. Boş ad bilgisayar adına döner."""
        if not self.started:
            return self.default_name, self.default_folder
        name = self.name_edit.text().strip() or self.default_name
        folder = self.folder_edit.text().strip() or self.default_folder
        return name, folder

    def prepare_content(self) -> None:
        self.fit_content(min_content_w=520, extra_w=4, extra_h=4)
