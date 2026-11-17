"""Geçmiş tablosu (arama, sıralama, aç/klasörde göster), transfer gruplama, cihaz sayısı yazısı, vektör rozetler,
başlık menü düğmeleri ve ilk bölme genişliği."""

import os
import re
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.models.device import Device  # noqa: E402
from src.models.transfer import Transfer, TransferDirection, TransferStatus  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _transfer(tid, name, size, status, direction=TransferDirection.RECEIVE, path=None, when=None):
    transfer = Transfer(tid, path or f"C:/yok/{name}", name, size, "192.168.1.37", "Pixel 8", direction)
    transfer.start()
    if when is not None:
        transfer.start_time = when
    if status == TransferStatus.COMPLETED:
        transfer.complete()
    elif status == TransferStatus.FAILED:
        transfer.fail("Bağlantı koptu")
    elif status == TransferStatus.CANCELLED:
        transfer.cancel()
    return transfer


class HistoryTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from src.models.database import get_database

        self.db = get_database()
        self.db.clear_history()
        self.addCleanup(self.db.clear_history)
        fd, self.real_file = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        self.addCleanup(os.remove, self.real_file)
        self.db.add_transfer(_transfer("h1", "Rapor.pdf", 4_000_000, TransferStatus.COMPLETED, path=self.real_file,
                                       when=datetime(2026, 11, 17, 15, 24, 31)))
        self.db.add_transfer(_transfer("h2", "Butce.xlsx", 600_000, TransferStatus.FAILED,
                                       direction=TransferDirection.SEND, when=datetime(2026, 11, 16, 9, 5)))
        self.db.add_transfer(_transfer("h3", "Notlar.txt", 12_000, TransferStatus.CANCELLED,
                                       when=datetime(2026, 11, 15, 8, 0)))

    def _dialog(self, lang="tr"):
        from src.gui.history_dialog import HistoryDialog

        dialog = HistoryDialog(None, lang)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _row_of(self, dialog, filename):
        from src.gui.history_dialog import COL_FILE

        for row in range(dialog.table.rowCount()):
            if dialog.table.item(row, COL_FILE).text() == filename:
                return row
        self.fail(f"{filename} tabloda yok")

    def test_columns_and_readable_cells(self) -> None:
        from src.gui.history_dialog import COL_DATE, COL_DEVICE, COL_SIZE
        from src.utils.helpers import format_bytes

        dialog = self._dialog()
        self.assertFalse(dialog.table.isHidden())
        self.assertTrue(dialog.empty_box.isHidden())
        self.assertEqual(dialog.table.columnCount(), 5)
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertEqual(dialog.table.horizontalHeaderItem(COL_SIZE).text(), "Boyut")
        done = self._row_of(dialog, "Rapor.pdf")
        self.assertEqual(dialog.table.item(done, COL_SIZE).text(), format_bytes(4_000_000))
        self.assertEqual(dialog.table.item(done, COL_DATE).text(), "17.11.2026 15:24")
        self.assertEqual(dialog.table.item(done, COL_DEVICE).toolTip(), "192.168.1.37")
        failed = self._row_of(dialog, "Butce.xlsx")
        self.assertEqual(dialog.table.item(failed, COL_SIZE).text(), "Başarısız", "0 B yerine durum yazmalı")
        self.assertIn("Bağlantı koptu", dialog.table.item(failed, COL_SIZE).toolTip())
        cancelled = self._row_of(dialog, "Notlar.txt")
        self.assertEqual(dialog.table.item(cancelled, COL_SIZE).text(), "İptal Edildi")
        self.assertEqual(dialog.count_label.text(), "3 kayıt")

    def test_english_headers_and_date(self) -> None:
        from src.gui.history_dialog import COL_DATE, COL_FILE

        dialog = self._dialog("en")
        self.assertEqual(dialog.table.horizontalHeaderItem(COL_FILE).text(), "File")
        row = self._row_of(dialog, "Rapor.pdf")
        self.assertEqual(dialog.table.item(row, COL_DATE).text(), "2026-11-17 15:24")

    def test_waiting_transfer_shows_a_dash_instead_of_an_empty_date(self) -> None:
        from src.gui.history_dialog import COL_DATE

        self.db.add_transfer(Transfer("h4", "C:/yok/Bekleyen.zip", "Bekleyen.zip", 1_000, "192.168.1.37", "Pixel 8",
                                      TransferDirection.SEND))
        dialog = self._dialog()
        self.assertEqual(dialog.table.item(self._row_of(dialog, "Bekleyen.zip"), COL_DATE).text(), "—")

    def test_columns_sort_by_value_not_by_text(self) -> None:
        from src.gui.history_dialog import COL_DATE, COL_FILE, COL_SIZE

        dialog = self._dialog()
        self.assertEqual(dialog.table.item(0, COL_FILE).text(), "Rapor.pdf", "varsayılan: en yeni üstte")
        dialog.table.sortByColumn(COL_SIZE, Qt.SortOrder.AscendingOrder)
        self.assertEqual([dialog.table.item(r, COL_FILE).text() for r in range(3)],
                         ["Notlar.txt", "Butce.xlsx", "Rapor.pdf"])
        dialog.table.sortByColumn(COL_DATE, Qt.SortOrder.AscendingOrder)
        self.assertEqual(dialog.table.item(0, COL_FILE).text(), "Notlar.txt")

    def test_search_uses_the_database_and_explains_no_match(self) -> None:
        dialog = self._dialog()
        with mock.patch.object(dialog._db, "search_transfers", wraps=dialog._db.search_transfers) as search:
            dialog.search_edit.setText("butce")
            QTest.qWait(300)
            search.assert_called()
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.search_edit.setText("pixel")
        dialog._reload()
        self.assertEqual(dialog.table.rowCount(), 3, "cihaz adıyla da aranır")
        dialog.search_edit.setText("yok-boyle-bir-sey")
        dialog._reload()
        self.assertTrue(dialog.table.isHidden())
        self.assertFalse(dialog.empty_box.isHidden())
        self.assertEqual(dialog.empty_title.text(), "Eşleşen transfer yok")
        self.assertTrue(dialog.search_edit.isEnabled(), "eşleşme yokken arama düzeltilebilmeli")

    def test_open_and_reveal_only_for_files_that_exist(self) -> None:
        from src.gui import history_dialog

        dialog = self._dialog()
        present = self._row_of(dialog, "Rapor.pdf")
        missing = self._row_of(dialog, "Notlar.txt")
        self.assertTrue(all(act.isEnabled() for act in dialog.context_actions(present)))
        missing_actions = dialog.context_actions(missing)
        self.assertFalse(any(act.isEnabled() for act in missing_actions))
        self.assertEqual(missing_actions[0].toolTip(), "Dosya artık bu konumda değil")
        with mock.patch.object(history_dialog, "open_path") as opener, \
                mock.patch.object(history_dialog, "reveal_path") as revealer:
            dialog._open_row(missing)
            opener.assert_not_called()
            dialog.table.cellDoubleClicked.emit(present, 1)
            opener.assert_called_once_with(self.real_file)
            dialog.context_actions(present)[1].trigger()
            revealer.assert_called_once_with(self.real_file)

    def test_clear_empties_the_table_and_guides(self) -> None:
        from src.gui import history_dialog

        dialog = self._dialog()
        dialog.search_edit.setText("rapor")
        dialog._reload()
        with mock.patch.object(history_dialog, "ask_confirm", return_value=True):
            dialog._do_clear()
        self.assertEqual(dialog.search_edit.text(), "")
        self.assertTrue(dialog.table.isHidden())
        self.assertEqual(dialog.empty_title.text(), "Henüz transfer geçmişi yok")
        self.assertFalse(dialog.clear_btn.isEnabled())


class TransferGroupingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_finished_transfers_sink_below_running_ones_and_keep_their_cards(self) -> None:
        from src.gui.transfer_item import TransferListWidget

        widget = TransferListWidget()
        self.addCleanup(widget.deleteLater)
        transfers = [Transfer(f"t{i}", f"C:/x/{i}.bin", f"{i}.bin", 1000, "1.2.3.4", "P", TransferDirection.SEND)
                     for i in range(3)]
        for transfer in transfers:
            widget.add_transfer(transfer)
            self.addCleanup(widget.transfers[transfer.transfer_id][1].update_timer.stop)

        def order():
            lw = widget.list_widget
            return [lw.itemWidget(lw.item(r)).transfer.transfer_id for r in range(lw.count())]

        self.assertEqual(order(), ["t2", "t1", "t0"], "en yeni üstte")
        cards = {tid: card for tid, (_, card) in widget.transfers.items()}
        transfers[2].start()
        transfers[2].complete()
        widget.update_transfer(transfers[2])
        self.assertEqual(order(), ["t1", "t0", "t2"])
        transfers[1].start()
        transfers[1].fail("x")
        widget.update_transfer(transfers[1])
        self.assertEqual(order(), ["t0", "t1", "t2"], "son biten, bitenlerin en üstünde")
        for tid, (_, card) in widget.transfers.items():
            self.assertIs(card, cards[tid], "sıralama kartları yeniden yaratmamalı")
        # yeniden denenen transfer tekrar üste çıkar
        retry = Transfer("t1", "C:/x/1.bin", "1.bin", 1000, "1.2.3.4", "P", TransferDirection.SEND)
        widget.add_transfer(retry)
        self.assertEqual(order()[:2], ["t1", "t0"])


class DeviceCountLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_count_says_online_when_there_is_room_and_always_explains(self) -> None:
        from src.gui.device_list import DeviceListWidget

        widget = DeviceListWidget()
        self.addCleanup(widget.deleteLater)
        widget.retranslate("tr")
        for i, online in enumerate((True, True, False)):
            device = Device(f"192.168.1.{i + 2}", 38520, f"PC{i}", f"PC{i}")
            device.is_online = online
            widget.add_device(device)
        widget.show()
        widget.resize(600, 300)
        self.app.processEvents()
        self.assertEqual(widget.device_count_label.text(), "2/3 çevrimiçi")
        self.assertEqual(widget.device_count_label.toolTip(), "3 cihazın 2 tanesi çevrimiçi")
        widget.resize(widget.minimumSizeHint().width(), 300)
        self.app.processEvents()
        self.assertEqual(widget.device_count_label.text(), "2/3")
        self.assertEqual(widget.device_count_label.toolTip(), "3 cihazın 2 tanesi çevrimiçi")


class BadgeGlyphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_paused_and_cancelled_use_drawn_icons_not_characters(self) -> None:
        from src.gui.transfer_item import TransferItemWidget

        transfer = Transfer("b1", "C:/x/a", "a", 1000, "1.2.3.4", "P", TransferDirection.SEND)
        card = TransferItemWidget(transfer)
        self.addCleanup(card.update_timer.stop)
        self.addCleanup(card.deleteLater)
        transfer.start()
        transfer.pause()
        card._update_ui()
        self.assertEqual(card.direction_label.glyph(), "pause")
        self.assertEqual(card.direction_label.text(), "", "rozette yazı karakteri kalmamalı")
        transfer.cancel()
        card._update_ui()
        self.assertEqual(card.direction_label.glyph(), "close")
        self.assertEqual(card.direction_label.property("badge"), "muted")
        card.resize(80, 60)
        card.grab()  # paintEvent simgeyi çizerken hata vermemeli


class TitleMenuButtonTest(unittest.TestCase):
    def test_both_themes_draw_the_menu_buttons_as_raised_boxes(self) -> None:
        for name in ("dark", "light"):
            with open(os.path.join(ROOT, "assets", "styles", f"{name}.qss"), encoding="utf-8") as fh:
                qss = fh.read()
            rule = re.search(r'QPushButton\[class="menu-button"\] \{(.*?)\}', qss, re.S).group(1)
            self.assertNotIn("transparent", rule, name)
            self.assertRegex(rule, r"border: 1px solid #[0-9a-f]{6}", name)
            self.assertIn("border-top-color", rule, name)


class InitialSplitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_left_panel_opens_wider_on_a_wide_window(self) -> None:
        from src.gui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.deleteLater)
        window.resize(1300, 760)
        window.show()
        self.app.processEvents()
        left, right = window.splitter.sizes()
        self.assertGreaterEqual(left, 370)
        self.assertLessEqual(left, 380)
        window.hide()


if __name__ == "__main__":
    unittest.main()
