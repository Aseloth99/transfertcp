"""Pencere içi kısa bilgi kapsülü (isteğe bağlı tek eylem düğmesiyle): "Ofis-PC listeden kaldırıldı · Geri al".

Gizli durum çubuğunun yerini alır: ana pencerenin içeriğinin alt-ortasında belirir, birkaç saniye sonra kendiliğinden
söner. Yeni ileti eskisinin yerine geçer (kuyruk yok, gürültü olmasın). Fareyle üstündeyken kapanmaz; tıklayınca kapanır.
Renkler temadan (`palette.is_dark`) ve seçili vurgudan okunur; `refresh_style()` tema değişince çağrılır.
Belirme/sönme 180 ms'lik saydamlık geçişidir; Windows'ta "animasyonları göster" kapalıysa geçiş yapılmaz.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

from .glyph_icons import glyph_icon
from .smooth_progress import _system_animations_enabled

FADE_MS = 180
_TONE_GLYPH = {"ok": "check", "err": "alert", "warn": "alert"}


def _colors(dark: bool, accent: dict) -> dict:
    """Koyu temada yüzeyden bir kademe açık, açık temada koyu kapsül: iki temada da içerikten ayrışır (≥ 4.5:1)."""
    if dark:
        return {"bg": "#3a3d42", "border": "#4a4e55", "text": "#f2f2f2", "action": accent["hi_dark"],
                "ok": "#66BB6A", "err": "#FF8A80", "warn": "#FFB74D", "info": "#f2f2f2"}
    return {"bg": "#2f3236", "border": "#2f3236", "text": "#ffffff", "action": accent["hi_light"],
            "ok": "#81C784", "err": "#FF8A80", "warn": "#FFB74D", "info": "#ffffff"}


class InlineToast(QFrame):
    """`show_message(text, msec, tone, action_text, action)`; `host` içeriğin alt-ortasına yerleşir."""

    MARGIN_BOTTOM = 18

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("inlineToast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._host = host
        self._tone = "info"
        self._action = None
        self._full_text = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 7, 8, 7)
        row.setSpacing(8)
        self._icon = QLabel(self)
        self._icon.setFixedSize(16, 16)
        self._label = QLabel(self)
        self._label.setObjectName("inlineToastText")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._button = QPushButton(self)
        self._button.setObjectName("inlineToastAction")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._button.clicked.connect(self._on_action)
        row.addWidget(self._icon)
        row.addWidget(self._label, 1)
        row.addWidget(self._button)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)
        self._fading_out = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        host.installEventFilter(self)
        self.refresh_style()
        self.hide()

    # -- durum -----------------------------------------------------------------------------------------------
    def text(self) -> str:
        return self._full_text

    def tone(self) -> str:
        return self._tone

    def action_text(self) -> str:
        return self._button.text() if not self._button.isHidden() else ""

    def is_showing(self) -> bool:
        """Görünür ya da görünmek üzere (pencere gizliyken de) ve sönmüyor."""
        return not self.isHidden() and not self._fading_out

    # -- gösterim --------------------------------------------------------------------------------------------
    def show_message(self, text: str, msec: int = 3000, tone: str = "info", action_text: str = "", action=None) -> None:
        self._tone = tone if tone in ("ok", "err", "warn", "info") else "info"
        self._full_text = str(text)
        self._label.setText(self._full_text)
        self._action = action if action_text else None
        self._button.setText(action_text)
        self._button.setVisible(bool(action_text))
        self.refresh_style()
        self._reposition()
        self._timer.start(max(1200, int(msec)))
        was_visible = self.is_showing()
        self._fading_out = False
        self.show()
        self.raise_()
        if was_visible:
            self._fade.stop()
            self._effect.setOpacity(1.0)
            return
        self._animate(0.0, 1.0)

    def dismiss(self) -> None:
        self._timer.stop()
        if self.isHidden() or self._fading_out:
            return
        self._action = None
        self._fading_out = True
        self._animate(self._effect.opacity(), 0.0)

    def _animate(self, start: float, end: float) -> None:
        self._fade.stop()
        if not _system_animations_enabled() or not self.isVisible():
            self._effect.setOpacity(end)
            self._on_fade_finished()
            return
        self._fade.setStartValue(start)
        self._fade.setEndValue(end)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._fading_out:
            self._fading_out = False
            self.hide()
            self._effect.setOpacity(1.0)

    def _on_action(self) -> None:
        action, self._action = self._action, None
        self.dismiss()
        if action is not None:
            action()

    # -- görünüm ---------------------------------------------------------------------------------------------
    def refresh_style(self) -> None:
        from ..palette import accent_spec, is_dark

        colors = _colors(is_dark(), accent_spec())
        self.setStyleSheet(
            f"QFrame#inlineToast {{ background: {colors['bg']}; border: 1px solid {colors['border']};"
            " border-radius: 10px; }"
            f"QLabel#inlineToastText {{ color: {colors['text']}; background: transparent; font-size: 9pt; }}"
            f"QPushButton#inlineToastAction {{ color: {colors['action']}; background: transparent; border: none;"
            " font-weight: 600; font-size: 9pt; padding: 2px 8px; min-height: 0px; min-width: 0px; }"
            "QPushButton#inlineToastAction:hover { background: rgba(255, 255, 255, 30); border-radius: 6px; }"
        )
        glyph = _TONE_GLYPH.get(self._tone)
        self._icon.setVisible(glyph is not None)
        if glyph is not None:
            self._icon.setPixmap(glyph_icon(glyph, colors[self._tone], 16).pixmap(QSize(16, 16)))
        if not self.isHidden():
            self._reposition()

    def _reposition(self) -> None:
        host = self._host
        self._label.setText(self._full_text)
        self.adjustSize()
        hint = self.sizeHint()
        width = min(max(hint.width(), 180), max(200, host.width() - 48))
        height = max(hint.height(), 34)
        if hint.width() > width:  # dar pencere: yazı "…" ile kısalır, tamamı ipucunda
            room = self._label.width() - (hint.width() - width)
            metrics = self._label.fontMetrics()
            self._label.setText(metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(40, room)))
        self.setToolTip(self._full_text if self._label.text() != self._full_text else "")
        self.resize(width, height)
        self.move((host.width() - width) // 2, max(0, host.height() - height - self.MARGIN_BOTTOM))

    # -- olaylar ---------------------------------------------------------------------------------------------
    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self._host and event.type() == QEvent.Type.Resize and not self.isHidden():
            self._reposition()
        return super().eventFilter(watched, event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()  # okurken kapanmasın
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.is_showing():
            self._timer.start(1800)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.dismiss()
            event.accept()
            return
        super().mousePressEvent(event)
