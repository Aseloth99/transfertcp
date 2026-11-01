"""Güncelleme penceresi (UpdateDialog): durumlar, boyut satırı, satır içi hata, Esc/X ile iptal. Hiçbir QMessageBox açılmaz."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox, QTextEdit  # noqa: E402

from src.gui.update_dialog import UpdateDialog, _wrappable  # noqa: E402
from src.utils.locales import t  # noqa: E402


def no_message_boxes():
    fail = AssertionError("QMessageBox açılmamalı")
    return mock.patch.multiple(QMessageBox, critical=mock.Mock(side_effect=fail), warning=mock.Mock(side_effect=fail),
                               information=mock.Mock(side_effect=fail), question=mock.Mock(side_effect=fail))


class DialogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_ = support.qt_app()

    def dialog(self, lang="tr", notes="Yenilikler:\n- bir\n- iki", mandatory=False, size=41_943_040):
        dlg = UpdateDialog("1.2.3", notes, mandatory, None, lang, size)
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        self.addCleanup(dlg.close)
        self.events = []
        dlg.update_accepted.connect(lambda: self.events.append("accepted"))
        dlg.update_deferred.connect(lambda: self.events.append("deferred"))
        dlg.update_cancelled.connect(lambda: self.events.append("cancelled"))
        return dlg

    @staticmethod
    def shown(*widgets):
        return [not w.isHidden() for w in widgets]


class IdleStateTest(DialogCase):
    def test_idle_shows_version_size_notes_and_two_buttons(self):
        for lang in ("tr", "en"):
            with self.subTest(lang=lang):
                dlg = self.dialog(lang)
                self.assertEqual(dlg.update_btn.text(), t("update_now", lang))
                self.assertEqual(dlg.later_btn.text(), t("update_later", lang))
                self.assertEqual(self.shown(dlg.update_btn, dlg.later_btn), [True, True])
                self.assertTrue(dlg.cancel_btn.isHidden(), "İptal yalnızca indirme sırasında görünür")
                self.assertFalse(dlg.size_label.isHidden())
                self.assertEqual(dlg.size_label.text(), t("update_size_line", lang).format(size="40.00 MB"))
                self.assertTrue(dlg.progress_bar.isHidden())
                self.assertTrue(dlg.error_label.isHidden())
                self.assertIn("bir", dlg.findChild(QTextEdit).toPlainText())

    def test_the_size_line_is_hidden_when_the_size_is_unknown(self):
        for size in (None, 0, -1, "abc"):
            dlg = self.dialog(size=size)
            self.assertTrue(dlg.size_label.isHidden(), size)

    def test_mandatory_has_no_later_button(self):
        dlg = self.dialog(mandatory=True)
        self.assertTrue(dlg.later_btn.isHidden())
        self.assertFalse(dlg.update_btn.isHidden())

    def test_pressing_update_asks_the_app_once_and_blocks_a_double_click(self):
        dlg = self.dialog()
        dlg.update_btn.click()
        self.assertEqual(self.events, ["accepted"])
        self.assertFalse(dlg.update_btn.isEnabled(), "çift tıklama ikinci indirme başlatmasın")

    def test_later_emits_deferred_exactly_once_and_closes(self):
        dlg = self.dialog()
        dlg.later_btn.click()
        self.assertEqual(self.events, ["deferred"])
        self.assertFalse(dlg.isVisible())


class DownloadingStateTest(DialogCase):
    def test_downloading_shows_progress_speed_and_only_cancel(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        self.assertEqual(self.shown(dlg.cancel_btn, dlg.update_btn, dlg.later_btn), [True, False, False])
        self.assertFalse(dlg.progress_bar.isHidden())
        self.assertFalse(dlg.progress_label.isHidden())
        dlg.update_download_progress(10 * 1024 * 1024, 40 * 1024 * 1024, 2.5)
        self.assertEqual(dlg.progress_bar.value(), 25)
        self.assertIn("10.00 MB / 40.00 MB (25%)", dlg.progress_label.text())
        self.assertIn("2.50 MB/s", dlg.progress_label.text())

    def test_unknown_total_shows_a_busy_bar(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        dlg.update_download_progress(1024, 0, 0.0)
        self.assertEqual((dlg.progress_bar.minimum(), dlg.progress_bar.maximum()), (0, 0))
        self.assertIn("1.00 KB", dlg.progress_label.text())

    def test_progress_handles_sizes_above_two_gigabytes(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        dlg.update_download_progress(3_000_000_000, 5_000_000_000, 1.0)
        self.assertEqual(dlg.progress_bar.value(), 60)

    def test_cancel_button_cancels_and_closes_without_a_question(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        with no_message_boxes():
            dlg.cancel_btn.click()
        self.assertEqual(self.events, ["cancelled"], "indirme iptali 'daha sonra' sayılmaz")
        self.assertFalse(dlg.isVisible())

    def test_escape_during_download_cancels_and_closes(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        with no_message_boxes():
            QApplication.sendEvent(dlg, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.events, ["cancelled"])
        self.assertFalse(dlg.isVisible())

    def test_the_window_close_button_during_download_cancels_and_closes(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        with no_message_boxes():
            dlg.close()
        self.assertEqual(self.events, ["cancelled"])
        self.assertFalse(dlg.isVisible())

    def test_progress_after_the_dialog_left_the_downloading_state_is_ignored(self):
        dlg = self.dialog()
        dlg.update_download_progress(5, 10, 1.0)  # indirme hiç başlamadı
        self.assertTrue(dlg.progress_bar.isHidden())


class InstallingStateTest(DialogCase):
    def test_installing_has_no_buttons_and_cannot_be_closed(self):
        dlg = self.dialog()
        dlg.show_downloading_state()
        dlg.show_download_complete()
        dlg.show_installing_state()
        self.assertEqual(self.shown(dlg.cancel_btn, dlg.update_btn, dlg.later_btn), [False, False, False])
        self.assertFalse(dlg.status_label.isHidden())
        self.assertEqual(dlg.status_label.text(), t("update_installing", "tr"))
        QApplication.sendEvent(dlg, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        dlg.close()
        self.assertTrue(dlg.isVisible(), "kurulum yarıda kesilemez")
        self.assertEqual(self.events, [])
        dlg.show_install_complete()
        self.assertEqual(dlg.status_label.text(), t("update_restarting", "tr"))


class ErrorStateTest(DialogCase):
    def test_error_is_inline_red_keeps_the_window_open_and_offers_retry(self):
        for lang in ("tr", "en"):
            with self.subTest(lang=lang):
                dlg = self.dialog(lang)
                dlg.update_btn.click()
                self.events.clear()
                with no_message_boxes():
                    dlg.show_error("ağ koptu")
                self.assertTrue(dlg.isVisible())
                self.assertFalse(dlg.error_label.isHidden())
                self.assertEqual(dlg.error_label.text(), t("update_failed_inline", lang).format(error="ağ koptu"))
                self.assertEqual(dlg.error_label.property("tone"), "err")
                self.assertEqual(dlg.update_btn.text(), t("update_retry", lang))
                self.assertTrue(dlg.update_btn.isEnabled())
                self.assertEqual(self.shown(dlg.update_btn, dlg.later_btn, dlg.cancel_btn), [True, True, False])
                self.assertTrue(dlg.progress_bar.isHidden())
                dlg.update_btn.click()
                self.assertEqual(self.events, ["accepted"], "Tekrar dene yeniden denemeyi ister")

    def test_error_without_retry_offers_only_close(self):
        dlg = self.dialog()
        dlg.show_error("kaynaktan çalışıyor", retry=False)
        self.assertTrue(dlg.update_btn.isHidden())
        self.assertEqual(dlg.later_btn.text(), t("close", "tr"))
        self.assertFalse(dlg.later_btn.isHidden())

    def test_mandatory_error_without_retry_still_has_a_close_button(self):
        dlg = self.dialog(mandatory=True)
        dlg.show_error("x", retry=False)
        self.assertFalse(dlg.later_btn.isHidden())

    def test_long_paths_get_break_opportunities_so_nothing_is_cut_off(self):
        text = _wrappable(r"C:\Program Files\TransferTCP\TransferTCP.exe.new")
        self.assertIn("\\\u200b", text)
        self.assertEqual(text.replace("\u200b", ""), r"C:\Program Files\TransferTCP\TransferTCP.exe.new")
        dlg = self.dialog()
        dlg.show_error(r"C:\Çok\Uzun\Bir\Klasör\Yolu\TransferTCP.exe")
        self.assertTrue(dlg.error_label.wordWrap())

    def test_closing_after_an_error_counts_as_later(self):
        dlg = self.dialog()
        dlg.show_error("x")
        dlg.later_btn.click()
        self.assertEqual(self.events, ["deferred"])

    def test_notice_returns_to_normal_and_is_not_an_error(self):
        dlg = self.dialog()
        dlg.update_btn.click()  # düğme kilitlendi
        dlg.show_notice("2 aktarım sürüyor")
        self.assertFalse(dlg.notice_label.isHidden())
        self.assertEqual(dlg.notice_label.text(), "2 aktarım sürüyor")
        self.assertTrue(dlg.error_label.isHidden())
        self.assertTrue(dlg.update_btn.isEnabled())
        self.assertEqual(dlg.update_btn.text(), t("update_now", "tr"), "normal duruma dönüldü, 'Tekrar dene' değil")
        self.assertEqual(self.shown(dlg.update_btn, dlg.later_btn, dlg.cancel_btn), [True, True, False])
        dlg.update_btn.click()
        self.assertEqual(self.events[-1], "accepted")

    def test_a_new_attempt_hides_the_old_error(self):
        dlg = self.dialog()
        dlg.show_error("x")
        dlg.update_btn.click()
        self.assertTrue(dlg.error_label.isHidden())
        dlg.show_downloading_state()
        self.assertTrue(dlg.error_label.isHidden())
        self.assertEqual(self.shown(dlg.cancel_btn, dlg.update_btn), [True, False])


class NotesAndLayoutTest(DialogCase):
    def test_long_notes_stay_scrollable_inside_the_dialog(self):
        notes = "Yenilikler:\n" + "\n".join(f"• Çok uzun bir sürüm notu satırı {i}" for i in range(80))
        dlg = self.dialog(notes=notes)
        box = dlg.findChild(QTextEdit)
        self.assertTrue(box.isReadOnly())
        self.assertGreater(box.verticalScrollBar().maximum(), 0, "uzun notlar kaydırılabilir")
        self.assertLess(dlg.height(), 900, "pencere notlarla birlikte ekranı aşacak kadar büyümez")

    def test_the_dialog_grows_to_fit_a_long_inline_error(self):
        dlg = self.dialog()
        before = dlg.height()
        dlg.show_error("Yeni sürüm uygulamanın klasörüne yazılamadı: " + "çok uzun açıklama " * 30)
        QApplication.processEvents()
        QApplication.processEvents()
        self.assertGreaterEqual(dlg.height(), min(before, dlg.sizeHint().height()))
        self.assertGreaterEqual(dlg.height(), dlg.minimumSizeHint().height())


if __name__ == "__main__":
    unittest.main()
