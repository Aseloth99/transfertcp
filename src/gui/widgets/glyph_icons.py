"""Düğme simgeleri: emoji yerine verilen renkle boyanan vektörler.

"⏸" gibi emoji karakterleri Windows'ta renkli mavi bir kutu olarak çiziliyor ve temayı hiç izlemiyordu;
burada çizilen simgeler yazı rengine uyar (koyu temada açık, açık temada koyu).
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_CACHE: dict[tuple[str, str, int], QIcon] = {}
KINDS = ("pause", "play", "close", "upload")


def glyph_color(dark: bool, tone: str = "normal") -> str:
    """Tema (koyu/açık) ve ton için simge rengi."""
    if tone == "muted":
        return "#9a9a9a" if dark else "#616161"
    return "#e6e6e6" if dark else "#424242"


def glyph_icon(kind: str, color: str, size: int = 16) -> QIcon:
    if kind not in KINDS:
        raise ValueError(f"unknown glyph: {kind}")
    key = (kind, color.lower(), size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    scale = 2
    pix = QPixmap(size * scale, size * scale)
    pix.setDevicePixelRatio(scale)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = QColor(color)
    s = float(size)
    if kind == "pause":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.drawRoundedRect(QRectF(s * 0.27, s * 0.2, s * 0.16, s * 0.6), 1.4, 1.4)
        painter.drawRoundedRect(QRectF(s * 0.57, s * 0.2, s * 0.16, s * 0.6), 1.4, 1.4)
    elif kind == "play":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        path = QPainterPath()
        path.moveTo(QPointF(s * 0.34, s * 0.2))
        path.lineTo(QPointF(s * 0.34, s * 0.8))
        path.lineTo(QPointF(s * 0.8, s * 0.5))
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "close":
        pen = QPen(c, s * 0.11)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(s * 0.3, s * 0.3), QPointF(s * 0.7, s * 0.7))
        painter.drawLine(QPointF(s * 0.7, s * 0.3), QPointF(s * 0.3, s * 0.7))
    elif kind == "upload":
        pen = QPen(c, s * 0.075)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(s * 0.5, s * 0.62), QPointF(s * 0.5, s * 0.16))
        painter.drawLine(QPointF(s * 0.5, s * 0.16), QPointF(s * 0.32, s * 0.34))
        painter.drawLine(QPointF(s * 0.5, s * 0.16), QPointF(s * 0.68, s * 0.34))
        tray = QPainterPath()
        tray.moveTo(QPointF(s * 0.16, s * 0.6))
        tray.lineTo(QPointF(s * 0.16, s * 0.82))
        tray.lineTo(QPointF(s * 0.84, s * 0.82))
        tray.lineTo(QPointF(s * 0.84, s * 0.6))
        painter.drawPath(tray)
    painter.end()
    icon = QIcon(pix)
    _CACHE[key] = icon
    return icon
