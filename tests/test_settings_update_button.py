"""Bekleyen güncelleme başlık çubuğunda değil Ayarlar'da: "↑ Güncelle · vX" düğmesi (FlexiKey'deki gibi).

Düğme durum satırının yerini alır; tıklanınca Ayarlar kapanır (kalıcı pencere: üstünde açılan güncelleme penceresi
tıklanamazdı) ve ardından güncelleme penceresi istenir. Tepsi satırı ayrıca durur (test_update_ux).
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtCore import QEvent, QObject, pyqtSignal  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402

from src.utils.locales import t  # noqa: E402


class _FakeChecker(QObject):
    """Ağa çıkmayan denetleyici: denetim sırasında `on_check` çalışır (uygulamanın sürüm bildirimi gibi)."""

    manual_check_finished = pyqtSignal()
    check_message = pyqtSignal(str, str, str)

    def __init__(self, on_check=None):
        super().__init__()
        self._on_check = on_check

    def check_for_updates(self, show_message=False):
        if self._on_check:
            self._on_check()
        self.check_message.emit("info", "", "")
        self.manual_check_finished.emit()


class SettingsUpdateButtonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.utils.config import get_config

        self.addCleanup(lambda: QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        config = get_config()
        snapshot = copy.deepcopy(config.config)

        def restore():
            config.config = snapshot
            config.save()

        self.addCleanup(restore)
        config.set("ui", "language", "tr")
        for name, value in (("is_in_startup", False), ("add_to_startup", True), ("remove_from_startup", True)):
            patcher = mock.patch(f"src.utils.startup.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        from src.gui.main_window import MainWindow

        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.requested = []
        self.window.update_requested.connect(lambda: self.requested.append(1))

    def _dialog(self):
        from src.gui.settings import SettingsDialog

        dialog = SettingsDialog(self.window)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def assert_button(self, dialog, version):
        self.assertFalse(dialog.update_open_btn.isHidden())
        self.assertTrue(dialog.update_status.isHidden(), "düğme durum metninin yerini alır")
        self.assertEqual(dialog.update_open_btn.text(), "↑  " + t("update_pill", "tr").format(version=version))
        self.assertEqual(dialog.update_open_btn.toolTip(), t("update_pill_tip", "tr").format(version=version))
        self.assertEqual(dialog.update_open_btn.property("class"), "primary")

    def test_title_bar_has_no_update_pill(self):
        """Başlıkta yazılı hap yok; yalnızca pencere düğmesi boyutunda, yazısız ↑ simgesi."""
        self.window.set_update_available("1.2.3")
        bar = self.window.title_bar
        texts = [b.text() for b in bar.findChildren(QPushButton)]
        self.assertFalse([x for x in texts if "1.2.3" in x], texts)
        self.assertEqual(self.window.update_version, "1.2.3", "sürüm yine pencerede tutulur")
        self.assertFalse(bar.update_btn.isHidden())
        self.assertEqual(bar.update_btn.text(), "")
        self.assertEqual(bar.update_btn.size(), bar.minimize_btn.size())

    def test_no_pending_version_no_button(self):
        dialog = self._dialog()
        self.assertTrue(dialog.update_open_btn.isHidden())

    def test_pending_version_shows_the_button_when_settings_opens(self):
        self.window.set_update_available("1.2.3")
        self.assert_button(self._dialog(), "1.2.3")

    def test_version_arriving_while_settings_is_open_updates_it_live(self):
        dialog = self._dialog()
        self.window.set_update_available("2.0.0")
        self.assert_button(dialog, "2.0.0")
        self.window.set_update_available("")
        self.assertTrue(dialog.update_open_btn.isHidden())

    def test_click_closes_settings_then_requests_the_update_dialog(self):
        self.window.set_update_available("1.2.3")
        dialog = self._dialog()
        dialog.show()
        dialog.update_open_btn.click()
        self.assertFalse(dialog.isVisible(), "Ayarlar kapanır")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected, "kaydedilmeden kapanır")
        self.assertEqual(self.requested, [], "güncelleme penceresi Ayarlar kapandıktan sonra açılır")
        QTest.qWait(20)
        self.assertEqual(self.requested, [1])

    def test_manual_check_that_finds_an_update_shows_the_button(self):
        self.window.update_checker = _FakeChecker(lambda: self.window.set_update_available("1.2.3"))
        dialog = self._dialog()
        idle_text = dialog.check_update_btn.text()
        dialog.check_update_btn.click()
        self.assert_button(dialog, "1.2.3")
        self.assertFalse(dialog.update_check.running, "dönen simge durur")
        self.assertTrue(dialog.check_update_btn.isEnabled())
        self.assertEqual(dialog.check_update_btn.text(), idle_text)

    def test_manual_check_without_update_keeps_the_status_line(self):
        from src.gui.widgets.update_check_ui import UpdateCheckAnimator
        from src.utils.updater import UpdateChecker

        self.window.update_checker = _FakeChecker()
        dialog = self._dialog()
        with mock.patch.object(UpdateCheckAnimator, "MIN_MS", 0):
            dialog.check_update_btn.click()
        self.assertTrue(dialog.update_open_btn.isHidden())
        self.assertFalse(dialog.update_status.isHidden())
        expected = t("update_status_current", "tr").format(version=UpdateChecker().get_current_version())
        self.assertTrue(dialog.update_status.text().endswith(expected), dialog.update_status.text())


if __name__ == "__main__":
    unittest.main()
