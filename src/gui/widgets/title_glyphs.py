"""Başlık çubuğu düğmelerinin vektör işaretleri: ekranı kapla, geri yükle ve güncelleme oku (↑).

Şekiller 32×32'lik ızgarada tanımlıdır (FlexiKey, Lumina ve MediaCompressor ile aynı ölçüler) ve doğrudan
`paintEvent` içinde çizilir; böylece %100, %125 ve %150 ölçekte de keskin kalır. "□"/"❐" yazı işaretleri
yazı tipine göre farklı göründüğü için kullanılmaz.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QPushButton

KINDS = ("maximize", "restore", "update")

# Başlık düğmesinde ızgaranın çizildiği kare (px): 28×24 düğmede "−" ve "×" ile aynı görsel ağırlık
GLYPH_BOX = 16


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_title_glyph(painter: QPainter, kind: str, rect: QRectF, color: QColor) -> None:
    """`kind` işaretini `rect` karesine (32'lik ızgara ölçeklenerek) çizer; fırça yok, uçlar ve köşeler yuvarlak."""
    if kind not in KINDS:
        raise ValueError(f"unknown title glyph: {kind}")
    side = min(rect.width(), rect.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(rect.x() + (rect.width() - side) / 2.0, rect.y() + (rect.height() - side) / 2.0)
    painter.scale(side / 32.0, side / 32.0)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "maximize":
        painter.setPen(_pen(color, 1.85))
        painter.drawRoundedRect(QRectF(8.5, 8.5, 15, 15), 2.2, 2.2)
    elif kind == "restore":
        front = QRectF(8, 11.5, 12.5, 12.5)
        back = QRectF(11.5, 7.5, 12.5, 12.5)
        painter.setPen(_pen(color, 1.7))
        # Arka kare yalnızca öndekinin kapatmadığı yerde görünür (çizgiler kesişmez)
        visible = QPainterPath()
        visible.addRect(QRectF(0, 0, 32, 32))
        covered = QPainterPath()
        covered.addRoundedRect(front, 1.8, 1.8)
        painter.save()
        painter.setClipPath(visible.subtracted(covered))
        painter.drawRoundedRect(back, 1.8, 1.8)
        painter.restore()
        painter.drawRoundedRect(front, 1.8, 1.8)
    else:  # update: gövde + ok başı
        painter.setPen(_pen(color, 2.1))
        painter.drawLine(QPointF(16, 24), QPointF(16, 9))
        head = QPainterPath(QPointF(10.5, 14.5))
        head.lineTo(QPointF(16, 9))
        head.lineTo(QPointF(21.5, 14.5))
        painter.drawPath(head)
    painter.restore()


def _lum(c: QColor) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(c.redF()) + 0.7152 * lin(c.greenF()) + 0.0722 * lin(c.blueF())


def contrast(a: QColor, b: QColor) -> float:
    la, lb = _lum(QColor(a)), _lum(QColor(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def update_ink(dark: bool, spec: dict) -> QColor:
    """↑ işaretinin rengi: seçili vurgu; başlık zemininde zor okunuyorsa (kontrast < 3) aynı vurgunun açık/koyu tonu."""
    ground = QColor("#2f2f2f" if dark else "#f5f5f5")  # QSS: koyu düğme zemini / açık başlık zemini
    color = QColor(spec["accent"])
    if contrast(color, ground) >= 3.0:
        return color
    color = QColor(spec["hi_dark"] if dark else spec["accent2"])
    for _ in range(12):
        if contrast(color, ground) >= 3.0:
            break
        color = color.lighter(110) if dark else color.darker(110)
    return color


class TitleGlyphButton(QPushButton):
    """QSS'li başlık düğmesi (zemin/kenar/hover stilden gelir); üstüne vektör işaret çizilir, yazı yoktur.

    Renk: `ink` verilmezse komşu "−"/"×" ile aynı yazı rengi (QSS `color`, üzerine gelince temanın metin rengi).
    """

    def __init__(self, kind: str, parent=None):
        super().__init__("", parent)
        if kind not in KINDS:
            raise ValueError(f"unknown title glyph: {kind}")
        self._kind = kind
        self._ink: QColor | None = None
        self._dy = 0.0

    def set_glyph_offset(self, dy: float) -> None:
        """İşareti düşeyde kaydırır (komşu yazı işaretleri "−"/"×" yazı tipi gereği ortanın biraz altında durur)."""
        self._dy = float(dy)
        self.update()

    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown title glyph: {kind}")
        if kind != self._kind:
            self._kind = kind
            self.update()

    def set_ink(self, color: QColor | str | None) -> None:
        self._ink = QColor(color) if color is not None else None
        self.update()

    def glyph_color(self) -> QColor:
        if self._ink is not None:
            return QColor(self._ink)
        if self.underMouse() and self.isEnabled():
            from ..palette import tcp_palette  # QSS hover: açık temada yazı koyulaşır (#4a4a4a → #1a1a1a)

            return QColor(tcp_palette()["text"])
        return self.palette().color(QPalette.ColorRole.ButtonText)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)  # QSS zemini ve kenarı
        painter = QPainter(self)
        box = float(GLYPH_BOX)
        rect = QRectF((self.width() - box) / 2.0, (self.height() - box) / 2.0 + self._dy, box, box)
        draw_title_glyph(painter, self._kind, rect, self.glyph_color())
        painter.end()
