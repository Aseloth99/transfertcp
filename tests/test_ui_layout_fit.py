"""Dar pencerede sığma ve küçük cilalar: kartlar daralır, ad/IP/durum kesilmez, başlık toplamı kısalır,
açık temada oklar görünür, bayt/ayraç/zaman biçimleri."""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtCore import QEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.models.device import Device  # noqa: E402
from src.models.transfer import Transfer, TransferDirection  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _device(ip="192.168.1.52", name="Misafir-PC", online=False) -> Device:
    device = Device(ip, 38520, name, name)
    device.is_online = online
    return device


def _transfer(tid="t1") -> Transfer:
    return Transfer(tid, "C:/x/a.mkv", "a.mkv", 10_000_000, "192.168.1.37", "Pixel 8", TransferDirection.RECEIVE)


class ListShrinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _settle(self, widget, width, height=400):
        widget.resize(width, height)
        QTest.qWait(250)  # Adjust kipi yeniden yerleşimi kısa bir gecikmeyle yapar

    def test_transfer_cards_follow_the_viewport_when_narrowed(self) -> None:
        from src.gui.transfer_item import TransferListWidget

        widget = TransferListWidget()
        self.addCleanup(widget.deleteLater)
        widget.add_transfer(_transfer())
        _, card = widget.transfers["t1"]
        self.addCleanup(card.update_timer.stop)
        widget.show()
        self._settle(widget, 900)
        self._settle(widget, 560)
        self.assertLessEqual(card.width(), widget.list_widget.viewport().width(),
                             "daraltınca kart eski genişlikte kalıp sağdan kesilmemeli")

    def test_device_cards_follow_the_viewport_when_narrowed(self) -> None:
        from src.gui.device_list import DeviceListWidget

        widget = DeviceListWidget()
        self.addCleanup(widget.deleteLater)
        widget.add_device(_device())
        widget.show()
        self._settle(widget, 500)
        self._settle(widget, 260)
        viewport = widget.list_widget.viewport().width()
        for i in range(widget.list_widget.count()):
            card = widget.list_widget.itemWidget(widget.list_widget.item(i))
            self.assertLessEqual(card.width(), viewport)


class DeviceCardRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_name_gets_the_whole_top_row_and_state_sits_beside_the_ip(self) -> None:
        from src.gui.device_list import DeviceItemWidget

        card = DeviceItemWidget(_device())
        self.addCleanup(card.deleteLater)
        card.resize(220, 60)
        card.show()
        self.app.processEvents()
        self.assertEqual(card.name_label.text(), "Misafir-PC", "kısa ad dar kartta bile kesilmemeli")
        self.assertEqual(card.state_label.geometry().center().y(), card.info_label.geometry().center().y())
        self.assertGreater(card.state_label.x(), card.info_label.geometry().right(), "durum IP'nin sağında")
        self.assertGreaterEqual(card.info_label.width(), card.info_label.sizeHint().width(), "IP kesilmemeli")

    def test_left_panel_keeps_room_for_ip_and_state(self) -> None:
        from src.gui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.deleteLater)
        panel = window.device_list.parentWidget()
        self.assertGreaterEqual(panel.minimumWidth(), 270)


class TransferHeaderStatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_totals_switch_to_the_short_form_only_when_they_do_not_fit(self) -> None:
        from src.gui.transfer_item import TransferListWidget

        widget = TransferListWidget()
        self.addCleanup(widget.deleteLater)
        widget.retranslate("tr")
        widget.show()
        widget.resize(1200, 300)
        self.app.processEvents()
        widget.set_statistics("609.22 MB", "217.26 MB")
        self.assertIn("Alınan", widget.stats_label.text())
        self.assertEqual(widget.stats_label.toolTip(), "")
        widget.resize(300, 300)
        self.app.processEvents()
        self.assertEqual(widget.stats_label.text(), "↑ 609.22 MB  ·  ↓ 217.26 MB")
        self.assertIn("Alınan: 217.26 MB", widget.stats_label.toolTip(), "tam metin ipucunda kalmalı")
        widget.resize(1200, 300)
        self.app.processEvents()
        self.assertIn("Gönderilen", widget.stats_label.text())


class LightThemeArrowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_light_stylesheet_uses_the_dark_stroke_arrows(self) -> None:
        with open(os.path.join(ROOT, "assets", "styles", "light.qss"), encoding="utf-8") as fh:
            qss = fh.read()
        self.assertNotRegex(qss, r"arrow_(up|down)_dark\.svg", "açık zeminde açık gri ok görünmüyordu")
        self.assertRegex(qss, r"arrow_up_light\.svg")
        self.assertRegex(qss, r"arrow_down_light\.svg")
        for name in ("arrow_up_light.svg", "arrow_down_light.svg"):
            with open(os.path.join(ROOT, "assets", "icons", name), encoding="utf-8") as fh:
                stroke = re.search(r'stroke="(#[0-9a-fA-F]{6})"', fh.read()).group(1)
            self.assertEqual(stroke.lower(), "#4a4a4a", name)

    def test_stepper_arrows_repaint_when_the_theme_changes(self) -> None:
        from src.gui.widgets.stepper_spinbox import StepperSpinBox

        previous = self.app.property("tt_dark")
        self.addCleanup(self.app.setProperty, "tt_dark", previous)
        self.app.setProperty("tt_dark", True)
        spin = StepperSpinBox()
        self.addCleanup(spin.deleteLater)
        self.assertEqual(spin._arrow_color, "#cbd5e1")
        self.app.setProperty("tt_dark", False)
        QApplication.sendEvent(spin, QEvent(QEvent.Type.StyleChange))
        self.assertEqual(spin._arrow_color, "#4a4a4a")


class SmallFormatsTest(unittest.TestCase):
    def test_bytes_are_whole_numbers(self) -> None:
        from src.utils.helpers import format_bytes

        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.50 KB")

    def test_transfer_info_lines_use_the_middle_dot(self) -> None:
        from src.utils.locales import t

        for lang in ("tr", "en"):
            for key in ("transfer_info_completed", "transfer_info_failed", "transfer_info_cancelled"):
                text = t(key, lang)
                self.assertIn(" · ", text, f"{lang}:{key}")
                self.assertNotIn(" - ", text, f"{lang}:{key}")

    def test_turkish_settings_labels_are_not_jargon(self) -> None:
        from src.utils.locales import t

        self.assertEqual(t("chunk_size", "tr"), "Parça Boyutu")
        self.assertEqual(t("log_level", "tr"), "Günlük Düzeyi")

    def test_history_time_is_readable(self) -> None:
        from src.gui.history_dialog import _format_time

        self.assertEqual(_format_time("2026-11-17T15:24:31.705133", "tr"), "17.11.2026 15:24")
        self.assertEqual(_format_time("2026-11-17T15:24:31.705133", "en"), "2026-11-17 15:24")
        self.assertEqual(_format_time("dün", "tr"), "dün", "okunamayan değer olduğu gibi kalır")
        self.assertEqual(_format_time(None, "tr"), "")


class SettingsFormAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_labels_are_as_tall_as_fields_and_bands_are_transparent(self) -> None:
        from PyQt6.QtWidgets import QLabel

        from src.gui.settings import SettingsDialog

        dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)
        labels = dialog.findChildren(QLabel, "settingsFieldLabel")
        self.assertTrue(labels)
        for label in labels:
            self.assertEqual(label.minimumHeight(), dialog._FIELD_H, label.text())
        folder_field = dialog.download_folder_edit.parentWidget()
        self.assertIn("transparent", folder_field.styleSheet())


if __name__ == "__main__":
    unittest.main()
