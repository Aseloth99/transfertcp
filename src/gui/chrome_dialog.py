"""Özel üst çubuklu pencere kalıbı: Ayarlar, Hakkında, Geçmiş, Güncelleme, Karşılama… hepsi aynı çerçeveyi kullanır.

Çerçeve `message_box` ile birebir aynıdır (çerçevesiz, 12 px köşe, 2 px vurgu üst çizgisi, 38 px başlık çubuğu:
uygulama simgesi + başlık + ✕, başlıktan sürüklenir, Esc = vazgeç). Alt sınıf içeriğini `self.body` içine kurar:

    class AboutDialog(ChromeDialog):
        def __init__(self, parent=None):
            super().__init__(parent, "Hakkında")
            layout = QVBoxLayout(self.body)
            ...

İçerik uygulamanın QSS'iyle (tema/vurgu) çizilir; çerçeve ve başlık paleti `palette.tcp_palette()` üzerinden gelir.
Boyut içeriğe göre ayarlanır (`fit_content`), pencere ana pencerenin ortasında açılır.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from .message_box import (
    _SHADOW,
    _TITLE_H,
    _ChromeDialog,
    _TitleBar,
    _plain,
    current_palette,
)


def _chrome_qss(p: dict) -> str:
    """Yalnızca çerçeve kuralları: içerik uygulamanın genel QSS'ini kullanmaya devam eder."""
    return f"""
        QDialog#mb_root {{ background: transparent; border: none; }}
        QWidget[mb="1"] {{ background: transparent; border: none; color: {p['text']}; }}
        QLabel#mb_title_label {{ color: {p['text']}; font-size: 9.5pt; font-weight: 600; }}
    """


class ChromeDialog(_ChromeDialog):
    """Özel çubuklu modal pencere. Alt sınıflar içeriği `self.body` (saydam kapsayıcı) içine kurar."""

    def __init__(self, parent: QWidget | None = None, title: str = ""):
        super().__init__(parent)
        self._title_text = str(title)
        QDialog.setWindowTitle(self, self._title_text)
        self._prepared = False
        self._pal = current_palette()
        self.setStyleSheet(_chrome_qss(self._pal))
        inner = self._inner = _plain(QWidget(self), "mb_inner")
        self._outer.addWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title_bar = _TitleBar(self, self._pal, self._title_text, self._title_icon(), inner)
        lay.addWidget(self.title_bar)
        self.body = QWidget(inner)
        self.body.setProperty("mb", "1")
        lay.addWidget(self.body, 1)

    # -- başlık -----------------------------------------------------------------------------------------------
    def setWindowTitle(self, title: str) -> None:  # noqa: N802 (Qt adı)
        self._title_text = str(title)
        QDialog.setWindowTitle(self, self._title_text)
        bar = getattr(self, "title_bar", None)
        if bar is not None:
            bar.title_label.setText(self._title_text)

    # -- palet ------------------------------------------------------------------------------------------------
    def refresh_chrome(self) -> None:
        """Tema/vurgu değişince (canlı önizleme) çerçeve ve başlık renklerini yeniden oku."""
        self._pal = current_palette()
        self.setStyleSheet(_chrome_qss(self._pal))
        bar = self.title_bar
        bar.title_label.set_color(QColor(self._pal["text"]))
        bar.close_btn._pal = self._pal
        bar.close_btn.update()
        self.update()

    # -- boyut ------------------------------------------------------------------------------------------------
    @staticmethod
    def chrome_size() -> QSize:
        """Çerçevenin içeriğe eklediği boyut (gölge payı + başlık çubuğu)."""
        return QSize(2 * _SHADOW, 2 * _SHADOW + _TITLE_H)

    def fit_content(self, min_content_w: int = 0, extra_w: int = 0, extra_h: int = 0, fixed: bool = True) -> None:
        """Pencereyi içeriğe göre boyutla. `min_content_w`: içerik (çerçevesiz) en az bu genişlikte olsun."""
        self.ensurePolished()
        for widget in self.findChildren(QWidget):
            widget.ensurePolished()
        lay = self.layout()
        lay.invalidate()
        lay.activate()
        hint = lay.sizeHint()
        chrome = self.chrome_size()
        width = max(hint.width(), min_content_w + chrome.width()) + extra_w
        height = hint.height()
        if lay.hasHeightForWidth():  # satır kaydırmalı etiketler: seçilen genişlikte gereken yükseklik
            height = max(height, lay.totalHeightForWidth(width))
        height += extra_h
        if fixed:
            self.setFixedSize(width, height)
        else:
            self.setMinimumSize(width, height)
            self.resize(max(self.width(), width), max(self.height(), height))

    def prepare_content(self) -> None:
        """Alt sınıflar boyut/ilk durum ayarını burada yapar (pencere gösterilmeden hemen önce, bir kez)."""
        self.fit_content()

    def setVisible(self, visible: bool) -> None:  # noqa: N802
        if visible and not self._prepared:
            self._prepared = True
            # Sahibi görünür değilse (tepsiye gizli uygulama) pencere kaybolmasın: en üstte açılır (MessageBox ile aynı)
            hidden_owner = self._anchor_window() is None
            on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            if on_top != hidden_owner:
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, hidden_owner)
            self.prepare_content()
            self._center()
        super().setVisible(visible)
