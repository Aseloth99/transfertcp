"""Hakkında penceresi (F1): özel üst çubuklu, tema/vurgu renkli."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ..utils.locales import t
from .chrome_dialog import ChromeDialog
from .notice_bar import LinkLabel


class AboutDialog(ChromeDialog):
    def __init__(self, parent=None, lang: str = "tr", version: str = "") -> None:
        super().__init__(parent, t("about_title", lang))
        self.setModal(True)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)

        title = QLabel(f"TransferTCP  v{version}")
        title.setObjectName("aboutTitle")
        title_font = title.font()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)

        tagline = QLabel(t("about_tagline", lang))
        tagline.setWordWrap(True)

        features_title = QLabel(t("about_features", lang))
        features_title.setStyleSheet("font-weight: 600; margin-top: 8px;")

        features = QLabel(
            "\n".join(f"• {t(key, lang)}" for key in (
                "about_feature_discovery",
                "about_feature_bidirectional",
                "about_feature_controls",
                "about_feature_fast",
                "about_feature_e2ee",
            ))
        )
        features.setWordWrap(True)
        features.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        from ..utils.remote_notice import SITE_URL
        site = LinkLabel("macik.com.tr", SITE_URL, self)

        self.ok_btn = QPushButton(t("ok", lang))
        self.ok_btn.setProperty("class", "primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)

        layout.addWidget(title)
        layout.addWidget(tagline)
        layout.addWidget(features_title)
        layout.addWidget(features)
        layout.addWidget(site)
        layout.addSpacing(8)
        layout.addWidget(self.ok_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def prepare_content(self) -> None:
        self.fit_content(min_content_w=420, extra_w=8, extra_h=8)
