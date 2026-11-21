"""Uzaktan duyuru satırı: yalnızca sunucu bir duyuru verdiyse ve kullanıcı kapatmadıysa görünür.

Kasten stil kuralı koymaz: yazı rengi uygulamanın o anki temasından miras alınır (iki temada da okunur),
zemin yarı saydam gridir. Duyuru düz metin olarak gösterilir (HTML yorumlanmaz); satıra tıklamak
(güvenilir bir adres verildiyse) tarayıcıda açar, ✕ kapatır.
Belirirken/kapanırken 200 ms'de yükseklik açılıp kapanır ve saydamlık değişir (birden belirip itmesin);
Windows'ta "animasyonları göster" kapalıysa geçiş yapılmaz.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy

from ..utils.remote_notice import Notice, is_trusted_url
from .widgets.smooth_progress import _system_animations_enabled

ANIM_MS = 200
_NO_LIMIT = 16777215  # QWIDGETSIZE_MAX


class NoticeBar(QFrame):
    dismissed = pyqtSignal(str)  # duyuru kimliği

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("notice_bar")
        self._notice: Notice | None = None
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)  # yalnızca yazı kadar yer kaplar
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 10, 6)
        row.setSpacing(8)
        self.text_label = QLabel(self)
        self.text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.text_label.setWordWrap(True)
        self.text_label.setOpenExternalLinks(False)
        self.arrow = QLabel("↗", self)
        self.close_label = QLabel("✕", self)
        self.close_label.setCursor(Qt.CursorShape.PointingHandCursor)
        for label in (self.arrow, self.close_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.text_label, 1)
        row.addWidget(self.arrow, 0)
        row.addWidget(self.close_label, 0)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self._opacity.setEnabled(False)  # yalnızca geçiş sırasında (sürekli açık efekt yazıyı ara belleğe çizer)
        self.setGraphicsEffect(self._opacity)
        self._anim = QParallelAnimationGroup(self)
        self._height_anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity", self)
        for anim in (self._height_anim, self._fade_anim):
            anim.setDuration(ANIM_MS)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.addAnimation(anim)
        self._anim.finished.connect(self._on_anim_finished)
        self._closing = False
        self.hide()

    def show_notice(self, notice: Notice) -> None:
        self._notice = notice
        self.text_label.setText(notice.text)
        has_link = bool(notice.url) and is_trusted_url(notice.url)
        self.arrow.setVisible(has_link)
        self.setCursor(Qt.CursorShape.PointingHandCursor if has_link else Qt.CursorShape.ArrowCursor)
        edge = "#E0A030" if notice.level == "warn" else "rgba(127, 127, 127, 140)"
        self.setStyleSheet(
            # sol köşeler küçük yarıçaplı: 8 px'te 3 px'lik kenar çizgisi "(" gibi kıvrık çiziliyordu
            "QFrame#notice_bar { background: rgba(127, 127, 127, 38); border-radius: 8px;"
            " border-top-left-radius: 3px; border-bottom-left-radius: 3px;"
            f" border-left: 3px solid {edge}; }}"
        )
        was_open = not self.isHidden() and not self._closing
        self._closing = False
        self.show()
        if was_open:
            return
        self._run(opening=True)

    def current(self) -> Notice | None:
        return self._notice

    def dismiss(self) -> None:
        notice, self._notice = self._notice, None
        if not self.isHidden() and not self._closing:
            self._closing = True
            self._run(opening=False)
        if notice is not None:
            self.dismissed.emit(notice.id)

    def is_closing(self) -> bool:
        return self._closing

    def _run(self, opening: bool) -> None:
        """Yükseklik 0 <-> içerik yüksekliği ve saydamlık 0 <-> 1; animasyon kapalıysa hemen biter."""
        self._anim.stop()
        width = self.width() if self.width() > 0 else self.sizeHint().width()
        full = self.heightForWidth(width) if self.hasHeightForWidth() else -1
        full = max(full, self.sizeHint().height(), 1)
        if not _system_animations_enabled() or not self.isVisible():
            self._on_anim_finished()
            return
        current = min(self.height(), full) if not opening else 0
        self._height_anim.setStartValue(current)
        self._height_anim.setEndValue(full if opening else 0)
        self._fade_anim.setStartValue(self._opacity.opacity() if not opening else 0.0)
        self._fade_anim.setEndValue(1.0 if opening else 0.0)
        self.setMaximumHeight(current)
        self._opacity.setOpacity(0.0 if opening else self._opacity.opacity())
        self._opacity.setEnabled(True)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        self._opacity.setEnabled(False)
        self._opacity.setOpacity(1.0)
        self.setMaximumHeight(_NO_LIMIT)
        if self._closing:
            self._closing = False
            self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._notice is None:
            return super().mousePressEvent(event)
        if self.childAt(event.position().toPoint()) is self.close_label:
            self.dismiss()
        elif self._notice.url and is_trusted_url(self._notice.url):
            QDesktopServices.openUrl(QUrl(self._notice.url))
        else:
            super().mousePressEvent(event)


class LinkLabel(QLabel):
    """Altı çizili, tıklanınca tarayıcıda açan yazı. Renk temadan miras alınır (iki temada da okunur)."""

    def __init__(self, text: str, url: str, parent=None):
        super().__init__(text, parent)
        self._url = url
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = self.font()
        font.setUnderline(True)
        self.setFont(font)
        self.setToolTip(url)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and is_trusted_url(self._url):
            QDesktopServices.openUrl(QUrl(self._url))
        else:
            super().mousePressEvent(event)
