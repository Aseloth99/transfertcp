"""Arayüz cilası: bırakma alanı hedef satırı, boş cihaz listesi, transfer kartı rozeti/çubuğu, boş transfer listesi."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.models.device import Device  # noqa: E402
from src.models.transfer import Transfer, TransferDirection, TransferStatus  # noqa: E402


def _device(ip="192.168.18.99", name="HP", online=True) -> Device:
    device = Device(ip, 38520, name, name)
    device.is_online = online
    return device


def _transfer(direction=TransferDirection.SEND, rel="programs/a.exe") -> Transfer:
    return Transfer("t1", "C:/x/a.exe", "a.exe", 10_000_000, "192.168.18.99", "HP", direction, relative_path=rel)


class DropZoneTargetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _zone(self):
        from src.gui.main_window import DropZone

        zone = DropZone()
        self.addCleanup(zone.deleteLater)
        return zone

    def test_no_device_disables_buttons_and_asks_for_one(self) -> None:
        zone = self._zone()
        zone.set_target(None, "tr")
        self.assertFalse(zone.select_btn.isEnabled())
        self.assertFalse(zone.select_folder_btn.isEnabled())
        self.assertIn("cihaz", zone.target_label.text().lower())
        self.assertEqual(zone.target_label.property("tone"), "warn")

    def test_offline_device_is_named_and_blocks_sending(self) -> None:
        zone = self._zone()
        zone.set_target(_device(online=False), "tr")
        self.assertFalse(zone.select_btn.isEnabled())
        self.assertIn("HP", zone.target_label.text())
        self.assertEqual(zone.target_label.property("tone"), "err")
        self.assertEqual(zone.property("target"), "offline")

    def test_online_device_enables_buttons_and_shows_name_and_ip(self) -> None:
        zone = self._zone()
        zone.set_target(_device(), "en")
        self.assertTrue(zone.select_btn.isEnabled())
        self.assertTrue(zone.select_folder_btn.isEnabled())
        self.assertIn("HP", zone.target_label.text())
        self.assertIn("192.168.18.99", zone.target_label.text())
        self.assertTrue(zone.target_label.text().startswith("Target"))
        self.assertEqual(zone.property("target"), "ready")

    def test_language_change_rewrites_the_target_line(self) -> None:
        zone = self._zone()
        zone.set_target(_device(), "tr")
        self.assertTrue(zone.target_label.text().startswith("Hedef"))
        zone.retranslate("en")
        self.assertTrue(zone.target_label.text().startswith("Target"))


class DeviceListStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_list_shows_the_explanation_instead_of_a_blank_list(self) -> None:
        from src.gui.device_list import DeviceListWidget

        widget = DeviceListWidget()
        self.addCleanup(widget.deleteLater)
        widget.resize(300, 400)
        widget.show()
        self.app.processEvents()
        self.assertFalse(widget.empty_box.isHidden(), "başlangıçta boş durum açıklaması görünmeli")
        self.assertTrue(widget.list_widget.isHidden())
        widget.add_device(_device())
        self.app.processEvents()
        self.assertTrue(widget.empty_box.isHidden())
        self.assertFalse(widget.list_widget.isHidden())
        widget.remove_device(_device())
        self.app.processEvents()
        self.assertFalse(widget.empty_box.isHidden())

    def test_selection_changes_are_announced(self) -> None:
        from src.gui.device_list import DeviceListWidget

        widget = DeviceListWidget()
        self.addCleanup(widget.deleteLater)
        calls = []
        widget.selection_changed.connect(lambda: calls.append(1))
        widget.add_device(_device())
        self.assertTrue(calls, "cihaz eklenince hedef satırı güncellensin diye haber verilmeli")
        calls.clear()
        offline = _device(online=False)
        widget.update_device(offline)
        self.assertTrue(calls, "çevrimiçi durumu değişince de haber verilmeli")

    def test_card_shows_the_connection_state_as_text(self) -> None:
        from src.gui.device_list import DeviceItemWidget

        online = DeviceItemWidget(_device(online=True))
        offline = DeviceItemWidget(_device(online=False))
        self.assertEqual(online.info_label.text(), "192.168.18.99", "IP satırı yalnızca IP: taşma olmasın")
        self.assertNotEqual(online.state_label.text(), offline.state_label.text())
        self.assertEqual(online.state_label.property("tone"), "ok")
        self.assertEqual(offline.state_label.property("tone"), "muted")
        offline.update_device(_device(online=True))
        self.assertEqual(offline.state_label.property("tone"), "ok", "çevrimiçi olunca durum yazısı güncellenmeli")


class MainWindowWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_adding_the_only_device_selects_it_and_targets_the_drop_zone(self) -> None:
        from src.gui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.assertFalse(window.drop_zone.select_btn.isEnabled())
        window.device_list.add_device(_device())
        self.app.processEvents()
        self.assertTrue(window.drop_zone.select_btn.isEnabled())
        self.assertIn("HP", window.drop_zone.target_label.text())
        window.device_list.remove_device(_device())
        self.app.processEvents()
        self.assertFalse(window.drop_zone.select_btn.isEnabled())


class TransferCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, transfer):
        from src.gui.transfer_item import TransferItemWidget

        card = TransferItemWidget(transfer)
        self.addCleanup(card.update_timer.stop)
        self.addCleanup(card.deleteLater)
        return card

    def test_badge_follows_direction_and_status(self) -> None:
        send = _transfer()
        card = self._card(send)
        self.assertEqual(card.direction_label.text(), "↑")
        recv = self._card(_transfer(TransferDirection.RECEIVE))
        self.assertEqual(recv.direction_label.text(), "↓")
        send.start()
        send.complete()
        card._update_ui()
        self.assertEqual(card.direction_label.text(), "✓")
        self.assertEqual(card.direction_label.property("badge"), "ok")
        failed = _transfer()
        failed_card = self._card(failed)
        failed.fail("hata")
        failed_card._update_ui()
        self.assertEqual(failed_card.direction_label.text(), "!")
        self.assertEqual(failed_card.direction_label.property("badge"), "err")

    def test_bar_color_comes_from_the_theme_not_a_widget_stylesheet(self) -> None:
        transfer = _transfer()
        card = self._card(transfer)
        self.assertEqual(card.progress_bar.styleSheet(), "", "sabit mavi stil kalmamalı: vurgu rengi temadan gelir")
        self.assertEqual(card.progress_bar.property("state"), "running")
        transfer.start()
        transfer.status = TransferStatus.PAUSED
        card._update_ui()
        self.assertEqual(card.progress_bar.property("state"), "paused")
        transfer.fail("x")
        card._update_ui()
        self.assertEqual(card.progress_bar.property("state"), "failed")

    def test_percent_and_icons(self) -> None:
        transfer = _transfer()
        card = self._card(transfer)
        transfer.start()
        transfer.bytes_transferred = 2_500_000
        card._update_ui()
        self.assertEqual(card.percent_label.text(), "25%")
        self.assertFalse(card.cancel_btn.icon().isNull(), "iptal düğmesi çizilmiş simge taşımalı (emoji değil)")
        self.assertEqual(card.cancel_btn.text(), "")
        transfer.status = TransferStatus.PAUSED
        card._update_ui()
        self.assertFalse(card.pause_btn.icon().isNull())

    def test_empty_transfer_list_paints_its_hint(self) -> None:
        from src.gui.transfer_item import TransferListWidget

        widget = TransferListWidget()
        self.addCleanup(widget.deleteLater)
        widget.resize(600, 300)
        widget.show()
        self.app.processEvents()
        pixmap = widget.list_widget.viewport().grab()
        self.assertFalse(pixmap.isNull())
        self.assertEqual(widget.list_widget.count(), 0)


class GlyphIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_every_glyph_draws_a_non_empty_icon(self) -> None:
        from src.gui.widgets.glyph_icons import KINDS, glyph_icon

        for kind in KINDS:
            icon = glyph_icon(kind, "#ffffff", 16)
            image = icon.pixmap(16, 16).toImage()
            painted = any(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()) for y in range(image.height()))
            self.assertTrue(painted, kind)

    def test_unknown_glyph_is_rejected(self) -> None:
        from src.gui.widgets.glyph_icons import glyph_icon

        with self.assertRaises(ValueError):
            glyph_icon("bilinmeyen", "#fff")


class EmptyDeviceBoxFitTest(unittest.TestCase):
    """Boş cihaz kutusunun açıklaması dar panelde 3 satıra bölünse de son satır kırpılmamalı (eski hata: düzen hizası)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_hint_gets_the_height_its_wrapped_text_needs(self) -> None:
        from src.gui.device_list import DeviceListWidget

        for width in (170, 200, 219, 260, 340):
            widget = DeviceListWidget()
            widget.resize(width, 560)
            widget.show()
            self.app.processEvents()
            hint = widget.empty_hint
            self.assertTrue(widget.empty_box.isVisible())
            # Asıl hata kaynağı: düzen düzeyinde hiza. Gerçek yazı tipleriyle son satırı kırpar; çevrimdışı (offscreen)
            # ortamda ölçü farkı görünmediği için yapıyı da doğrudan denetliyoruz.
            self.assertEqual(widget.empty_box.layout().alignment().value, 0, "düzene hiza verilmemeli")
            self.assertGreaterEqual(hint.height() + 1, hint.heightForWidth(hint.width()), width)
            self.assertGreaterEqual(widget.empty_add_btn.height() + 1, widget.empty_add_btn.sizeHint().height(), width)
            widget.close()


if __name__ == "__main__":
    unittest.main()
