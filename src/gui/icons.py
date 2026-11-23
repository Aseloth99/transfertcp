"""Lumina tarzı programatik menü ikonları."""

import math
import os
import tempfile

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


_SCALE = 2  # simgeler 2x çözünürlükte basılır (yüksek DPI'da keskin kalır)


def _canvas(size: int = 20) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(size * _SCALE, size * _SCALE)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(_SCALE)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pix, painter


# Tema simgeleri (Sistem / Koyu / Açık): vurguya değil nötr/anlamsal renge bağlıdır (güneş sarı, ay ve sistem gri).
# Aynı çizim ve renkler FlexiKey, MediaCompressor ve Lumina'da da vardır.
def theme_system_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#6f6f6f")))
    p.drawEllipse(QRectF(2.0, 2.0, 16.0, 16.0))
    p.setBrush(QBrush(QColor("#f2f2f2")))
    p.drawPie(QRectF(2.0, 2.0, 16.0, 16.0), 90 * 16, 180 * 16)
    p.setPen(QPen(QColor("#8c8c8c"), 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(2.5, 2.5, 15.0, 15.0))
    p.end()
    return QIcon(pix)


def theme_dark_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.PenStyle.NoPen)
    moon = QPainterPath()
    moon.addEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
    bite = QPainterPath()
    bite.addEllipse(QRectF(7.6, 1.2, 12.0, 12.0))
    p.setBrush(QBrush(QColor("#9a9a9a")))
    p.drawPath(moon.subtracted(bite))
    p.end()
    return QIcon(pix)


def theme_light_icon() -> QIcon:
    pix, p = _canvas()
    p.setPen(QPen(QColor("#f59e0b"), 1.6))
    p.setBrush(QBrush(QColor("#fbbf24")))
    p.drawEllipse(QRectF(5.0, 5.0, 10.0, 10.0))
    for ang in range(0, 360, 45):
        p.save()
        p.translate(10, 10)
        p.rotate(ang)
        p.drawLine(QPointF(0, -9), QPointF(0, -7))
        p.restore()
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
    p.drawEllipse(QRectF(5.6, 5.6, 8.8, 8.8))
    for ang in range(0, 360, 45):
        p.save()
        p.translate(10, 10)
        p.rotate(ang)
        p.drawRoundedRect(QRectF(-1.5, -8.6, 3.0, 4.6), 0.8, 0.8)
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


_CHECK_SCALE = 4  # 16 px kutu 64 px çizilir; Qt kutuya küçültür (%150 ölçekte tik bulanık olmasın)


def checkmark_png(color_hex: str = "#ffffff") -> str:
    """Onay kutusu tiki (QSS `image:` için PNG yolu, '/' ayraçlı).

    FlexiKey/MediaCompressor ile aynı çizim: 16x16 içerik kutusunda (3,8)-(6,11)-(13,4), 2.2 px yuvarlak uçlu kalem,
    4x çözünürlük. Diğer ikisiyle aynı yol: SVG yerine PNG (paketlemede PyQt6.QtSvg dışlanıyor), QImage ile çizilir
    (QGuiApplication gerekmez)."""
    s = _CHECK_SCALE
    dest = os.path.join(tempfile.gettempdir(), f"transfertcp_check_{color_hex.lstrip('#').lower()}_x{s}.png")
    if not os.path.exists(dest):
        img = QImage(16 * s, 16 * s, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color_hex), 2.2 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(3 * s, 8 * s), QPointF(6 * s, 11 * s), QPointF(13 * s, 4 * s)]))
        p.end()
        img.save(dest, "PNG")
    return dest.replace("\\", "/")


def chevron_png(color_hex: str) -> str:
    """Açılır liste oku (QSS `image:` için PNG yolu, '/' ayraçlı).

    Lumina/FlexiKey/MediaCompressor ile aynı çizim: 12x12 kutuda (2.5,4.5)-(6,8)-(9.5,4.5), 1.5 px yuvarlak uçlu kalem,
    4x çözünürlük, soluk yazı renginde; üzerine gelince, açıkken ve pasifken değişmez. QImage ile çizilir."""
    s = _CHECK_SCALE
    dest = os.path.join(tempfile.gettempdir(), f"transfertcp_chev_{color_hex.lstrip('#').lower()}_x{s}.png")
    if not os.path.exists(dest):
        img = QImage(12 * s, 12 * s, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color_hex), 1.5 * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(2.5 * s, 4.5 * s), QPointF(6 * s, 8 * s), QPointF(9.5 * s, 4.5 * s)]))
        p.end()
        img.save(dest, "PNG")
    return dest.replace("\\", "/")


def _menu_accent(kind: str = "accent") -> str:
    """Seçili vurgunun rengi (`accent`, `hi_light`): ayarlardaki (ya da önizlenen) vurgu."""
    from .palette import accent_spec

    return accent_spec()[kind]


# --- Renkli menü simgeleri ------------------------------------------------------------------------------------
# Lumina'daki (`app/ui/icons.py: menu_icon`) çizim ve renklerin aynısı: başlık menüleri, tepsi menüsü, sağ tık
# menüleri ve Ayarlar kenar çubuğu için iki tonlu, renkli simgeler. Her anlamın sabit bir rengi var (ayarlar mor
# dişli, bilgi mavi, güncelleme yeşil, çıkış/sil kırmızı, klasör amber...); "blue"/"sky" aileleri seçili vurguyu
# izler. Araç çubuğu simgeleri tek renk kalır. 32'lik ızgarada çizilir (32 ve 48 px kopya: %100/%150'de keskin);
# devre dışı satırlarda Qt simgeyi kendisi griler.

MENU_PALETTE = {
    "blue": "#2196F3", "blue_soft": "#90CAF9",  # "blue"/"sky" aileleri `_mi_color` içinde seçili vurguya yönlenir
    "amber": "#f59e0b", "amber_soft": "#fcd34d", "amber_deep": "#d97706",
    "green": "#22c55e", "emerald": "#10b981",
    "violet": "#8b5cf6", "purple": "#a855f7", "purple_soft": "#e9d5ff",
    "indigo": "#7c7ff5", "sky": "#2196F3", "sky_soft": "#90CAF9",
    "teal": "#14b8a6", "red": "#ef4444", "red_soft": "#fecaca",
    "orange": "#f97316", "cyan": "#06b6d4", "yellow": "#eab308",
}


def _mi_color(name: str) -> QColor:
    """Menü simgesi rengi. "blue"/"sky" aileleri seçili vurguyu izler; diğerleri anlam taşıyan sabit tonlardır."""
    if name in ("blue", "sky"):
        return QColor(_menu_accent("accent"))
    if name in ("blue_soft", "sky_soft"):
        return QColor(_menu_accent("hi_light"))
    return QColor(MENU_PALETTE[name])


def _mi_pen(color: QColor, width: float = 2.2) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _mi_icon(draw) -> QIcon:
    """`draw(painter)` 32×32'lik ızgarada çizer; 32 ve 48 px kopyalar."""
    icon = QIcon()
    for size in (32, 48):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 32.0, size / 32.0)
        draw(p)
        p.end()
        icon.addPixmap(pix)
    return icon


def _mi_gear(p: QPainter) -> None:
    gear = QPainterPath()
    gear.addEllipse(QPointF(16, 16), 8.6, 8.6)
    for i in range(8):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-2.4, -12.4, 4.8, 6.0), 1.2, 1.2)
        p.save()
        p.translate(16, 16)
        p.rotate(i * 45)
        gear = gear.united(p.transform().map(tooth))
        p.restore()
    hole = QPainterPath()
    hole.addEllipse(QPointF(16, 16), 3.6, 3.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("violet")))
    p.drawPath(gear.subtracted(hole))


def _mi_badge(p: QPainter, color: str) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color(color)))
    p.drawEllipse(QPointF(16, 16), 11, 11)


def _mi_info(p: QPainter) -> None:
    _mi_badge(p, "blue")
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawEllipse(QPointF(16, 10.6), 1.7, 1.7)
    p.drawRoundedRect(QRectF(14.5, 14, 3, 9.5), 1.3, 1.3)


def _mi_add(p: QPainter) -> None:
    """Yeşil rozet + beyaz artı: "Yeni …" satırları."""
    _mi_badge(p, "green")
    p.setPen(_mi_pen(QColor("#ffffff"), 2.4))
    p.drawLine(QPointF(16, 10.5), QPointF(16, 21.5))
    p.drawLine(QPointF(10.5, 16), QPointF(21.5, 16))


def _mi_update(p: QPainter) -> None:
    color = _mi_color("emerald")
    p.setPen(_mi_pen(color, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(6.5, 6.5, 19, 19), 30 * 16, 150 * 16)
    p.drawArc(QRectF(6.5, 6.5, 19, 19), 210 * 16, 150 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF([QPointF(24.6, 5.8), QPointF(25.4, 12.6), QPointF(18.8, 10.6)]))
    p.drawPolygon(QPolygonF([QPointF(7.4, 26.2), QPointF(6.6, 19.4), QPointF(13.2, 21.4)]))


def _mi_exit(p: QPainter) -> None:
    """Kapı + dışarı ok: "Çıkış" satırları."""
    color = _mi_color("red")
    p.setPen(_mi_pen(color, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(14.5, 6.5), QPointF(6.5, 6.5), QPointF(6.5, 25.5), QPointF(14.5, 25.5)]))
    p.drawLine(QPointF(12.0, 16.0), QPointF(26.0, 16.0))
    p.drawPolyline(QPolygonF([QPointF(21.0, 11.0), QPointF(26.0, 16.0), QPointF(21.0, 21.0)]))


def _mi_view(p: QPainter) -> None:
    eye = QPainterPath()
    eye.moveTo(4, 16)
    eye.quadTo(16, 4.5, 28, 16)
    eye.quadTo(16, 27.5, 4, 16)
    p.setPen(_mi_pen(_mi_color("indigo"), 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(eye)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("indigo")))
    p.drawEllipse(QPointF(16, 16), 4.6, 4.6)


def _mi_globe(p: QPainter) -> None:
    fill = _mi_color("sky")
    fill.setAlpha(55)
    p.setPen(_mi_pen(_mi_color("sky"), 1.7))
    p.setBrush(QBrush(fill))
    p.drawEllipse(QPointF(16, 16), 10, 10)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(16, 16), 4.6, 10)
    p.drawLine(QPointF(6, 16), QPointF(26, 16))
    p.drawLine(QPointF(7.6, 11), QPointF(24.4, 11))
    p.drawLine(QPointF(7.6, 21), QPointF(24.4, 21))


def _mi_document(p: QPainter) -> None:
    body = QPainterPath()
    body.moveTo(9, 5.5)
    body.lineTo(18.5, 5.5)
    body.lineTo(24, 11)
    body.lineTo(24, 25)
    body.quadTo(24, 26.5, 22.5, 26.5)
    body.lineTo(9.5, 26.5)
    body.quadTo(8, 26.5, 8, 25)
    body.lineTo(8, 7)
    body.quadTo(8, 5.5, 9, 5.5)
    p.setPen(_mi_pen(_mi_color("blue"), 1.6))
    p.setBrush(QBrush(_mi_color("blue_soft")))
    p.drawPath(body)
    p.setBrush(QBrush(_mi_color("blue")))
    p.drawPolygon(QPolygonF([QPointF(18.5, 5.5), QPointF(24, 11), QPointF(18.5, 11)]))
    p.setPen(_mi_pen(_mi_color("blue"), 1.5))
    for y, x2 in ((15.5, 20.5), (19, 20.5), (22.5, 17)):
        p.drawLine(QPointF(11.5, y), QPointF(x2, y))


def _mi_folder(p: QPainter) -> None:
    back = QPainterPath()
    back.moveTo(5, 9.5)
    back.quadTo(5, 7.5, 7, 7.5)
    back.lineTo(12.5, 7.5)
    back.lineTo(15, 10)
    back.lineTo(25, 10)
    back.quadTo(27, 10, 27, 12)
    back.lineTo(27, 23)
    back.quadTo(27, 25, 25, 25)
    back.lineTo(7, 25)
    back.quadTo(5, 25, 5, 23)
    back.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("amber_deep")))
    p.drawPath(back)
    p.setBrush(QBrush(_mi_color("amber_soft")))
    p.drawRoundedRect(QRectF(5, 12.5, 22, 12.5), 2.0, 2.0)


def _mi_plus_badge(p: QPainter) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("green")))
    p.drawEllipse(QPointF(23, 22), 7, 7)
    p.setPen(_mi_pen(QColor("#ffffff"), 1.9))
    p.drawLine(QPointF(23, 18.6), QPointF(23, 25.4))
    p.drawLine(QPointF(19.6, 22), QPointF(26.4, 22))


def _mi_folder_add(p: QPainter) -> None:
    """Klasör + yeşil artı rozeti (Lumina "Kopyala…" ile aynı çizim): "Klasör Ekle"."""
    _mi_folder(p)
    _mi_plus_badge(p)


def _mi_file_add(p: QPainter) -> None:
    """Belge + yeşil artı rozeti: "Dosya Ekle"."""
    _mi_document(p)
    _mi_plus_badge(p)


def _mi_copy(p: QPainter) -> None:
    p.setPen(_mi_pen(_mi_color("sky"), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(12, 5.5, 13, 15.5), 2, 2)
    p.setBrush(QBrush(_mi_color("sky_soft")))
    p.drawRoundedRect(QRectF(7, 10.5, 13, 15.5), 2, 2)


def _mi_trash(p: QPainter) -> None:
    p.setPen(_mi_pen(_mi_color("red"), 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(7.5, 10), QPointF(24.5, 10))
    p.drawLine(QPointF(13, 10), QPointF(13.8, 6.8))
    p.drawLine(QPointF(19, 10), QPointF(18.2, 6.8))
    p.drawLine(QPointF(13.8, 6.8), QPointF(18.2, 6.8))
    p.setBrush(QBrush(_mi_color("red_soft")))
    p.drawRoundedRect(QRectF(9.5, 10, 13, 15.5), 2, 2)
    p.drawLine(QPointF(14, 14), QPointF(14, 21.5))
    p.drawLine(QPointF(18, 14), QPointF(18, 21.5))


def _mi_open_with(p: QPainter) -> None:
    p.setPen(_mi_pen(_mi_color("purple"), 1.8))
    p.setBrush(QBrush(_mi_color("purple_soft")))
    p.drawRoundedRect(QRectF(5.5, 9.5, 17, 17), 2.5, 2.5)
    p.setPen(_mi_pen(_mi_color("purple"), 2.1))
    p.drawLine(QPointF(14, 18), QPointF(26, 6))
    p.drawLine(QPointF(19, 6), QPointF(26, 6))
    p.drawLine(QPointF(26, 6), QPointF(26, 13))


def _mi_rename(p: QPainter) -> None:
    p.save()
    p.translate(16, 16)
    p.rotate(45)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("amber")))
    p.drawRoundedRect(QRectF(-3.2, -11.5, 6.4, 17), 1.2, 1.2)
    p.setBrush(QBrush(_mi_color("amber_deep")))
    p.drawRect(QRectF(-3.2, -11.5, 6.4, 3.4))
    p.setBrush(QBrush(QColor("#fde68a")))
    p.drawPolygon(QPolygonF([QPointF(-3.2, 5.5), QPointF(3.2, 5.5), QPointF(0, 11)]))
    p.restore()
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.6))
    p.drawLine(QPointF(17, 26), QPointF(26, 26))


def _mi_guide(p: QPainter) -> None:
    """Açık kitap: "Kullanım Kılavuzu"."""
    color = _mi_color("indigo")
    soft = QColor(color)
    soft.setAlpha(60)
    p.setPen(_mi_pen(color, 1.7))
    p.setBrush(QBrush(soft))
    for x_out in (5.0, 27.0):
        page = QPainterPath()
        page.moveTo(16, 9)
        page.cubicTo(16 + (x_out - 16) * 0.27, 7, 16 + (x_out - 16) * 0.68, 6.8, x_out, 7.5)
        page.lineTo(x_out, 24)
        page.cubicTo(16 + (x_out - 16) * 0.68, 23.3, 16 + (x_out - 16) * 0.27, 23.5, 16, 25.5)
        page.closeSubpath()
        p.drawPath(page)
    p.drawLine(QPointF(16, 9), QPointF(16, 25.5))


def _mi_bolt(p: QPainter) -> None:
    """Şimşek: "Hızlı İşlemler"."""
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.2))
    p.setBrush(QBrush(_mi_color("yellow")))
    p.drawPolygon(QPolygonF([QPointF(18.4, 4), QPointF(8.8, 16.8), QPointF(15.6, 16.8), QPointF(13.6, 28),
                             QPointF(23.2, 15.2), QPointF(16.4, 15.2)]))


def _mi_backup(p: QPainter) -> None:
    """Arşiv kutusu: "Yedekleme ve Aktarım"."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_mi_color("amber_deep")))
    p.drawRoundedRect(QRectF(5, 7, 22, 6.5), 1.8, 1.8)
    p.setBrush(QBrush(_mi_color("amber_soft")))
    p.drawRoundedRect(QRectF(7, 13.5, 18, 12.5), 1.8, 1.8)
    p.setPen(_mi_pen(_mi_color("amber_deep"), 2.0))
    p.drawLine(QPointF(13, 17.5), QPointF(19, 17.5))


def _mi_trim(p: QPainter) -> None:
    """Makas: "Kırp…" (Lumina'daki kırpma gibi yeşil)."""
    color = _mi_color("green")
    p.setPen(_mi_pen(color, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(9.5, 22.5), 3.6, 3.6)
    p.drawEllipse(QPointF(22.5, 22.5), 3.6, 3.6)
    p.drawLine(QPointF(11.8, 19.6), QPointF(23, 6))
    p.drawLine(QPointF(20.2, 19.6), QPointF(9, 6))


def _mi_adjust(p: QPainter) -> None:
    """Kaydırıcılar: dosyaya özel ayarlar."""
    color = _mi_color("orange")
    p.setPen(_mi_pen(color, 2.0))
    for y in (9, 16, 23):
        p.drawLine(QPointF(5.5, y), QPointF(26.5, y))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    for x, y in ((11, 9), (21, 16), (14, 23)):
        p.drawEllipse(QPointF(x, y), 3.3, 3.3)


def _mi_send(p: QPainter) -> None:
    """Kâğıt uçak: "Dosya Gönder" / aktarım."""
    color = _mi_color("teal")
    soft = QColor(color)
    soft.setAlpha(70)
    p.setPen(_mi_pen(color, 1.8))
    p.setBrush(QBrush(soft))
    p.drawPolygon(QPolygonF([QPointF(4.5, 15), QPointF(27.5, 5.5), QPointF(20.5, 27), QPointF(15, 18.5)]))
    p.drawLine(QPointF(15, 18.5), QPointF(27.5, 5.5))


def _mi_star(p: QPainter) -> None:
    """Yıldız: sık kullanılanlar."""
    points = []
    for i in range(10):
        radius = 11.0 if i % 2 == 0 else 4.8
        angle = math.radians(-90 + i * 36)
        points.append(QPointF(16 + radius * math.cos(angle), 16.8 + radius * math.sin(angle)))
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.2))
    p.setBrush(QBrush(_mi_color("yellow")))
    p.drawPolygon(QPolygonF(points))


def _mi_network(p: QPainter) -> None:
    """Bağlı üç düğüm: ağ ayarları."""
    color = _mi_color("cyan")
    p.setPen(_mi_pen(color, 2.0))
    p.drawLine(QPointF(16, 8.5), QPointF(8.5, 22.5))
    p.drawLine(QPointF(16, 8.5), QPointF(23.5, 22.5))
    p.drawLine(QPointF(8.5, 22.5), QPointF(23.5, 22.5))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    for x, y in ((16, 8.5), (8.5, 22.5), (23.5, 22.5)):
        p.drawEllipse(QPointF(x, y), 4.2, 4.2)


def _mi_pause(p: QPainter) -> None:
    """İki çubuk: "Duraklat"."""
    p.setPen(_mi_pen(_mi_color("amber_deep"), 1.2))
    p.setBrush(QBrush(_mi_color("amber")))
    p.drawRoundedRect(QRectF(8.2, 6.5, 5.8, 19), 1.8, 1.8)
    p.drawRoundedRect(QRectF(18, 6.5, 5.8, 19), 1.8, 1.8)


def _mi_play(p: QPainter) -> None:
    """Üçgen: "Sürdür" / oynat."""
    p.setPen(_mi_pen(_mi_color("emerald"), 1.4))
    p.setBrush(QBrush(_mi_color("green")))
    p.drawPolygon(QPolygonF([QPointF(10, 6.5), QPointF(26, 16), QPointF(10, 25.5)]))

# Anlam -> simge (renk anlamla birlikte gelir; dört uygulamada aynı tablo)
_MENU_DRAWERS = {
    "settings": _mi_gear,       # mor dişli
    "info": _mi_info,           # mavi (vurgu) rozet
    "update": _mi_update,       # zümrüt yeşili oklar
    "exit": _mi_exit,           # kırmızı kapı
    "view": _mi_view,           # çivit göz (Göster/Gizle, önizleme)
    "globe": _mi_globe,         # vurgu küre (dil)
    "file": _mi_document,       # mavi (vurgu) belge
    "folder": _mi_folder,       # amber klasör (klasörde göster / klasörü aç)
    "folder_add": _mi_folder_add,
    "file_add": _mi_file_add,
    "add": _mi_add,             # yeşil artı (yeni …)
    "copy": _mi_copy,           # vurgu kopya
    "trash": _mi_trash,         # kırmızı çöp
    "open_with": _mi_open_with,  # mor dışarı aç
    "rename": _mi_rename,       # amber kalem (yaz/düzenle)
    "guide": _mi_guide,         # çivit kitap
    "bolt": _mi_bolt,           # sarı şimşek
    "backup": _mi_backup,       # amber arşiv
    "trim": _mi_trim,           # yeşil makas
    "adjust": _mi_adjust,       # turuncu kaydırıcılar
    "send": _mi_send,           # camgöbeği-yeşil uçak (aktarım)
    "star": _mi_star,           # sarı yıldız
    "network": _mi_network,     # camgöbeği düğümler
    "pause": _mi_pause,         # amber çubuklar (duraklat)
    "play": _mi_play,           # yeşil üçgen (sürdür / oynat)
}
MENU_ICON_NAMES = frozenset(_MENU_DRAWERS)
_MENU_ICON_CACHE: dict[str, QIcon] = {}


def menu_icon(name: str) -> QIcon:
    """Menü satırı / ayarlar sekmesi için renkli simge (önbellekli; QApplication kurulduktan sonra çağrılmalı)."""
    key = f"{name}|{_menu_accent('accent')}"  # vurgu değişince "blue"/"sky" ailesi yeniden çizilir
    icon = _MENU_ICON_CACHE.get(key)
    if icon is None:
        icon = _mi_icon(_MENU_DRAWERS[name])
        _MENU_ICON_CACHE[key] = icon
    return icon
