"""Uzun cihaz/dosya adlari kesilip atilmamali: '…' ile kisalmali ve tam ad ipucunda olmali."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (yalitilmis kullanici dizini; Qt offscreen)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.gui.widgets.elided_label import ElidedLabel  # noqa: E402


class ElidedLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_long_text_is_elided_with_the_full_text_as_tooltip(self):
        label = ElidedLabel("Tatil_2025_Antalya_Kas_Gezisi_Tum_Videolar_Birlestirilmis_Son_Hali.mp4")
        label.resize(160, 20)
        label.show()
        self.app.processEvents()
        self.assertTrue(label.text().endswith("…"))
        self.assertLess(len(label.text()), len(label.full_text()))
        self.assertEqual(label.toolTip(), label.full_text())
        label.close()

    def test_short_text_is_left_alone(self):
        label = ElidedLabel("rapor.pdf")
        label.resize(300, 20)
        label.show()
        self.app.processEvents()
        self.assertEqual(label.text(), "rapor.pdf")
        self.assertEqual(label.toolTip(), "")
        label.close()

    def test_text_can_be_replaced(self):
        label = ElidedLabel("a")
        label.resize(300, 20)
        label.show()
        label.set_full_text("yeni ad")
        self.assertEqual(label.text(), "yeni ad")
        label.close()


if __name__ == "__main__":
    unittest.main()
