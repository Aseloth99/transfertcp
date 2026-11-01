"""Lumina tarzı programatik menü ikonları."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _canvas(size: int = 20) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pix, painter


def theme_system_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#475569")))
    p.drawEllipse(2, 2, 16, 16)
    p.setBrush(QBrush(QColor("#f8fafc")))
    p.drawPie(2, 2, 16, 16, 90 * 16, 180 * 16)
    p.setPen(QPen(QColor(0, 0, 0, 45), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(2, 2, 16, 16)
    p.end()
    return QIcon(pix)


def theme_dark_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#6366f1")))
    p.drawEllipse(2, 2, 16, 16)
    p.setBrush(QBrush(QColor("#1e1b4b")))
    p.drawEllipse(7, 2, 13, 14)
    p.end()
    return QIcon(pix)


def theme_light_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(QPen(QColor("#f59e0b"), 1.6))
    p.setBrush(QBrush(QColor("#fbbf24")))
    p.drawEllipse(5, 5, 10, 10)
    for ang in range(0, 360, 45):
        p.save()
        p.translate(10, 10)
        p.rotate(ang)
        p.drawLine(QPointF(0, -9), QPointF(0, -7))
        p.restore()
    p.end()
    return QIcon(pix)


def refresh_network_icon(color_hex: str = "#38bdf8") -> QIcon:
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(3.5, 3.5, 13, 13), 50 * 16, -240 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color_hex)))
    p.drawPolygon(QPolygonF([
        QPointF(15.2, 3.2),
        QPointF(18.4, 7.4),
        QPointF(12.6, 7.1),
    ]))
    p.end()
    return QIcon(pix)


def history_icon(color_hex: str = "#9e9e9e") -> QIcon:
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4, 3.5, 12, 14), 1.6, 1.6)
    p.drawLine(QPointF(7, 7.2), QPointF(13, 7.2))
    p.drawLine(QPointF(7, 10.2), QPointF(13, 10.2))
    p.drawLine(QPointF(7, 13.2), QPointF(11, 13.2))
    p.end()
    return QIcon(pix)


def minimize_tray_icon(color_hex: str = "#9e9e9e") -> QIcon:
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4, 5, 12, 9), 1.5, 1.5)
    p.drawLine(QPointF(6.5, 15.5), QPointF(13.5, 15.5))
    p.end()
    return QIcon(pix)


def globe_icon(color_hex: str = "#38bdf8", size: int = 20) -> QIcon:
    pix, p = _canvas(size)
    pen = QPen(QColor(color_hex), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = (size - 4) / 2.0
    cx, cy = size / 2.0, size / 2.0
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
    p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
    p.drawEllipse(QPointF(cx, cy), r * 0.55, r)
    p.end()
    return QIcon(pix)


def eye_icon(color_hex: str = "#38bdf8") -> QIcon:
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(2.5, 10.0)
    path.cubicTo(6.0, 4.5, 14.0, 4.5, 17.5, 10.0)
    path.cubicTo(14.0, 15.5, 6.0, 15.5, 2.5, 10.0)
    p.drawPath(path)
    p.setBrush(QBrush(QColor(color_hex)))
    p.drawEllipse(QPointF(10.0, 10.0), 2.6, 2.6)
    p.end()
    return QIcon(pix)


def trash_icon(color_hex: str = "#ef4444") -> QIcon:
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(4, 6), QPointF(16, 6))
    p.drawPolyline([QPointF(8, 6), QPointF(8, 3.8), QPointF(12, 3.8), QPointF(12, 6)])
    p.drawPolyline([QPointF(5.5, 6), QPointF(6.5, 16.5), QPointF(13.5, 16.5), QPointF(14.5, 6)])
    p.drawLine(QPointF(8.5, 8.5), QPointF(8.5, 14))
    p.drawLine(QPointF(11.5, 8.5), QPointF(11.5, 14))
    p.end()
    return QIcon(pix)


def settings_gear_icon(color_hex: str = "#38bdf8") -> QIcon:
    pix, p = _canvas()
    color = QColor(color_hex)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawEllipse(QRectF(6.2, 6.2, 7.6, 7.6))
    for ang in range(0, 360, 45):
        p.save()
        p.translate(10, 10)
        p.rotate(ang)
        p.drawRoundedRect(QRectF(-1.5, -8.4, 3.0, 4.2), 0.8, 0.8)
        p.restore()
    # göbek deliği: sabit koyu/lacivert nokta yerine şeffaf delik (her menü zemininde doğru görünür)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawEllipse(QRectF(7.6, 7.6, 4.8, 4.8))
    p.end()
    return QIcon(pix)


def update_arrow_icon(color_hex: str = "#22c55e") -> QIcon:
    """Güncelleme (aşağı ok + taban çizgisi): tepsi menüsündeki "Güncelle · vX" satırı için."""
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(10.0, 3.0), QPointF(10.0, 12.5))
    p.drawPolyline([QPointF(6.2, 9.0), QPointF(10.0, 12.8), QPointF(13.8, 9.0)])
    p.drawLine(QPointF(4.5, 16.5), QPointF(15.5, 16.5))
    p.end()
    return QIcon(pix)


def door_exit_icon(color_hex: str = "#ef4444") -> QIcon:
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(9.0, 3.5), QPointF(3.5, 3.5), QPointF(3.5, 16.5), QPointF(9.0, 16.5)])
    p.drawLine(QPointF(7.0, 10.0), QPointF(16.5, 10.0))
    p.drawLine(QPointF(13.0, 6.5), QPointF(16.5, 10.0))
    p.drawLine(QPointF(13.0, 13.5), QPointF(16.5, 10.0))
    p.end()
    return QIcon(pix)


def folder_icon(color_hex: str = "#38bdf8") -> QIcon:
    """Klasör (menü: "Dosya"); emoji yerine vektör, rengi vurgudan gelir."""
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(3.0, 6.0)
    path.lineTo(3.0, 15.0)
    path.lineTo(17.0, 15.0)
    path.lineTo(17.0, 7.5)
    path.lineTo(9.6, 7.5)
    path.lineTo(8.2, 5.0)
    path.lineTo(3.0, 5.0)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def info_icon(color_hex: str = "#38bdf8") -> QIcon:
    """Bilgi (daire + i): "Hakkında" düğmesi/eylemi için."""
    pix, p = _canvas()
    pen = QPen(QColor(color_hex), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(10.0, 10.0), 7.2, 7.2)
    p.drawLine(QPointF(10.0, 9.2), QPointF(10.0, 13.6))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color_hex)))
    p.drawEllipse(QPointF(10.0, 6.5), 1.0, 1.0)
    p.end()
    return QIcon(pix)

