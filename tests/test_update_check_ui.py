"""Ayarlardaki "Kontrol et" düğmesi canlandırması: en az süre, dönen simge, kalıcı renkli sonuç."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: F401

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from src.gui.widgets.update_check_ui import UpdateCheckAnimator


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class UpdateCheckAnimatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_ = QApplication.instance() or QApplication([])

    def setUp(self):
        self.box = QWidget()
        lay = QVBoxLayout(self.box)
        self.btn = QPushButton("Kontrol et")
        self.lbl = QLabel("v1.0.0")
        lay.addWidget(self.btn)
        lay.addWidget(self.lbl)
        self.box.show()
        self.anim = UpdateCheckAnimator(self.btn, self.lbl, self.box)
        self.anim.MIN_MS = 150

    def tearDown(self):
        self.box.close()

    def test_button_keeps_spinning_until_minimum_time_even_if_result_is_instant(self):
        self.anim.start("Kontrol ediliyor…")
        self.assertFalse(self.btn.isEnabled())
        self.assertEqual(self.btn.text(), "Kontrol ediliyor…")
        self.assertFalse(self.btn.icon().isNull())
        self.anim.finish("ok", "Güncel · v1.0.0")  # sonuç anında geldi
        wait(40)
        self.assertTrue(self.anim.running, "en az süre dolmadan eski haline dönmemeli")
        self.assertFalse(self.btn.isEnabled())
        self.assertNotIn("Güncel", self.lbl.text())
        wait(300)
        self.assertFalse(self.anim.running)
        self.assertTrue(self.btn.isEnabled())
        self.assertEqual(self.btn.text(), "Kontrol et")
        self.assertTrue(self.btn.icon().isNull())
        self.assertIn("Güncel · v1.0.0", self.lbl.text())

    def test_result_stays_on_the_label(self):
        self.anim.start("Kontrol ediliyor…")
        self.anim.finish("new", "Yeni sürüm: v1.4.0")
        wait(500)
        self.assertTrue(self.lbl.text().startswith("↑"))
        self.assertIn("color:", self.lbl.styleSheet())
        wait(300)
        self.assertIn("Yeni sürüm: v1.4.0", self.lbl.text(), "sonuç kendiliğinden silinmemeli")

    def test_failure_has_its_own_mark_and_color(self):
        self.anim.start("Kontrol ediliyor…")
        self.anim.finish("fail", "Denetlenemedi")
        wait(400)
        self.assertTrue(self.lbl.text().startswith("✕"))

    def test_spinner_frames_rotate(self):
        self.anim.start("Kontrol ediliyor…")
        first = self.btn.icon().pixmap(16, 16).toImage()
        self.anim._tick()
        second = self.btn.icon().pixmap(16, 16).toImage()
        self.assertNotEqual(first, second)
        self.anim.cancel()

    def test_cancel_restores_the_button_without_a_result(self):
        self.anim.start("Kontrol ediliyor…")
        self.anim.cancel()
        self.assertTrue(self.btn.isEnabled())
        self.assertEqual(self.btn.text(), "Kontrol et")
        self.assertFalse(self.anim.running)

    def test_second_start_while_running_is_ignored(self):
        self.anim.start("Kontrol ediliyor…")
        self.anim.start("başka")
        self.assertEqual(self.btn.text(), "Kontrol ediliyor…")
        self.anim.cancel()

    def test_result_without_a_running_check_is_still_shown(self):
        self.anim.finish("ok", "Güncel · v1.0.0")
        wait(400)
        self.assertIn("Güncel", self.lbl.text())
        self.assertTrue(self.btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
