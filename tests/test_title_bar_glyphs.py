"""Başlık çubuğu (18 Kasım 2026): ekranı kapla / geri yükle işareti pencere durumunu gösterir (her WindowStateChange'de),
ipucu duruma ve dile göre değişir; bekleyen güncellemede küçültmenin solunda küçük, yazısız ↑ düğmesi durur."""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtCore import QEvent, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPalette  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.widgets.title_glyphs import contrast, draw_title_glyph, update_ink  # noqa: E402
from src.utils.locales import t  # noqa: E402


def _render(kind: str, size: int = 64) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_title_glyph(painter, kind, QRectF(0, 0, size, size), QColor("#000000"))
    painter.end()
    return image


def _alpha(image: QImage, x: float, y: float) -> int:
    """32'lik ızgara koordinatındaki pikselin opaklığı (64 px görüntüde ×2)."""
    scale = image.width() / 32.0
    return image.pixelColor(int(x * scale), int(y * scale)).alpha()


class GlyphDrawingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_maximize_is_one_rounded_square(self):
        image = _render("maximize")
        self.assertGreater(_alpha(image, 8.5, 16), 100, "sol kenar")
        self.assertGreater(_alpha(image, 23.5, 16), 100, "sağ kenar")
        self.assertEqual(_alpha(image, 16, 16), 0, "fırça yok: içi boş")

    def test_restore_back_square_is_clipped_by_the_front_square(self):
        image = _render("restore")
        self.assertGreater(_alpha(image, 8, 18), 100, "ön karenin sol kenarı")
        self.assertGreater(_alpha(image, 18, 7.5), 100, "arka karenin üst kenarı (önün dışında)")
        self.assertGreater(_alpha(image, 24, 10), 100, "arka karenin sağ kenarı (önün dışında)")
        # Arka karenin sol ve alt kenarı ön karenin içinden geçerdi: kırpıldığı için orası boş
        self.assertEqual(_alpha(image, 11.5, 17), 0, "arka sol kenar ön karenin içinde görünmemeli")
        self.assertEqual(_alpha(image, 15, 20), 0, "arka alt kenar ön karenin içinde görünmemeli")

    def test_update_arrow_is_a_stem_with_a_head(self):
        image = _render("update")
        self.assertGreater(_alpha(image, 16, 20), 100, "gövde")
        self.assertGreater(_alpha(image, 12, 13), 100, "sol kanat")
        self.assertGreater(_alpha(image, 20, 13), 100, "sağ kanat")
        self.assertEqual(_alpha(image, 10.5, 22), 0)

    def test_update_ink_reads_on_both_title_bars_for_every_accent(self):
        from src.gui.palette import ACCENTS

        for key, spec in ACCENTS.items():
            for dark, ground in ((True, "#2f2f2f"), (False, "#f5f5f5")):
                ink = update_ink(dark, spec)
                self.assertGreaterEqual(contrast(ink, QColor(ground)), 3.0, (key, dark, ink.name()))
        self.assertEqual(update_ink(True, ACCENTS["cyan"]).name().lower(), ACCENTS["cyan"]["accent"].lower(),
                         "okunuyorsa vurgunun kendisi")


class _WindowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.gui import palette
        from src.utils.config import get_config

        self.addCleanup(lambda: QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        config = get_config()
        snapshot = copy.deepcopy(config.config)

        def restore():
            config.config = snapshot
            config.save()
            palette.set_accent_override(None)
            self.app.setProperty("tt_dark", None)

        self.addCleanup(restore)
        config.set("ui", "language", "tr")
        config.set("ui", "theme", "dark")
        for name, value in (("is_in_startup", False), ("add_to_startup", True), ("remove_from_startup", True)):
            patcher = mock.patch(f"src.utils.startup.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        from src.gui.main_window import MainWindow

        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.bar = self.window.title_bar


class MaximizeButtonTest(_WindowCase):
    def test_glyph_follows_real_window_state_changes(self):
        """Uygulamanın kendi düğmesinden geçmeyen durum değişimi (Win+Yukarı, Aero Snap, görev çubuğu) de işareti değiştirir."""
        button = self.bar.maximize_btn
        self.window.show()
        self.assertEqual(button.kind(), "maximize")
        self.window.setWindowState(Qt.WindowState.WindowMaximized)
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(button.kind(), "restore")
        self.window.setWindowState(Qt.WindowState.WindowNoState)
        self.app.processEvents()
        self.assertEqual(button.kind(), "maximize")
        self.window.showMaximized()
        self.app.processEvents()
        self.assertEqual(button.kind(), "restore")
        button.click()  # kendi düğmesi: geri yükler
        self.app.processEvents()
        self.assertEqual(button.kind(), "maximize")
        self.window.hide()

    def test_tooltip_follows_state_and_language(self):
        button = self.bar.maximize_btn
        self.assertEqual(button.toolTip(), "Ekranı Kapla")
        with mock.patch.object(self.window, "isMaximized", return_value=True):
            self.window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
            self.assertEqual(button.toolTip(), "Geri Yükle")
            self.bar.retranslate("en")
            self.assertEqual(button.toolTip(), "Restore Down")
        self.window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        self.assertEqual(button.toolTip(), "Maximize")
        self.bar.retranslate("tr")
        self.assertEqual(button.toolTip(), "Ekranı Kapla")
        self.assertEqual(button.text(), "", "yazı işareti yok: vektör çizim")

    def test_glyph_uses_the_neighbouring_button_ink(self):
        for theme in ("dark", "light"):
            self.window.apply_theme(theme)
            self.bar.maximize_btn.ensurePolished()
            self.bar.minimize_btn.ensurePolished()
            neighbour = self.bar.minimize_btn.palette().color(QPalette.ColorRole.ButtonText)
            self.assertEqual(self.bar.maximize_btn.glyph_color().name(), neighbour.name(), theme)
        self.assertEqual(neighbour.name(), "#4a4a4a", "açık tema QSS rengi")

    def test_buttons_differ_visibly_between_states(self):
        button = self.bar.maximize_btn
        normal = button.grab().toImage()
        button.set_kind("restore")
        self.assertNotEqual(normal, button.grab().toImage())


class TitleUpdateButtonTest(_WindowCase):
    def test_hidden_without_a_pending_update(self):
        self.assertTrue(self.bar.update_btn.isHidden())

    def test_pending_update_shows_a_small_icon_left_of_minimize(self):
        self.window.set_update_available("1.2.3")
        button = self.bar.update_btn
        self.assertFalse(button.isHidden())
        self.assertEqual(button.text(), "")
        self.assertEqual(button.kind(), "update")
        self.assertEqual(button.size(), self.bar.minimize_btn.size())
        self.assertEqual(button.property("class"), self.bar.minimize_btn.property("class"), "aynı hover/basılı stili")
        layout = self.bar.layout()
        self.assertEqual(layout.indexOf(button) + 1, layout.indexOf(self.bar.minimize_btn))
        self.assertEqual(layout.indexOf(self.bar.minimize_btn) + 1, layout.indexOf(self.bar.maximize_btn))
        self.window.show()
        self.app.processEvents()
        self.assertLess(button.geometry().right(), self.bar.minimize_btn.geometry().left())
        self.window.hide()
        self.window.set_update_available("")
        self.assertTrue(button.isHidden())

    def test_tooltip_and_accessible_name(self):
        self.window.set_update_available("1.2.3")
        button = self.bar.update_btn
        self.assertEqual(button.toolTip(), "Yeni sürüm v1.2.3 hazır; ayrıntılar ve kurulum için tıklayın")
        self.assertEqual(button.accessibleName(), "Güncelle")
        self.bar.retranslate("en")
        self.assertEqual(button.toolTip(), "Version v1.2.3 is ready; click for details and installation")
        self.assertEqual(button.accessibleName(), "Update")

    def test_click_opens_the_same_update_window_and_installs_nothing(self):
        requested = []
        self.window.update_requested.connect(lambda: requested.append(1))
        self.window.set_update_available("1.2.3")
        with mock.patch.object(self.window, "show_pending_update", wraps=self.window.show_pending_update) as shown:
            QTest.mouseClick(self.bar.update_btn, Qt.MouseButton.LeftButton)
        shown.assert_called_once_with()
        self.assertEqual(requested, [1], "Ayarlar düğmesi ve tepsi satırıyla aynı istek (uygulama pencereyi açar)")

    def test_glyph_is_drawn_in_the_accent_colour(self):
        from src.gui.palette import accent_spec, is_dark

        self.assertEqual(self.bar.update_btn.glyph_color().name(), update_ink(is_dark(), accent_spec()).name())
        self.window.apply_theme("light", accent="orange")
        self.assertEqual(self.bar.update_btn.glyph_color().name(), update_ink(False, accent_spec("orange")).name())

    def test_auto_failed_text_points_to_the_title_bar_icon(self):
        self.assertIn("↑", t("update_auto_failed", "tr"))
        self.assertIn("↑", t("update_auto_failed", "en"))


if __name__ == "__main__":
    unittest.main()
