"""Pencereyi kapatmak (X / Alt+F4) uygulamayı tepsiye gizler; tamamen çıkış yalnızca Ctrl+Q / Çıkış / tepsi menüsü."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


class CloseBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from src.gui.main_window import MainWindow

        w = MainWindow()
        self.addCleanup(w.deleteLater)
        w.show()
        self.app.processEvents()
        return w

    def test_alt_f4_is_not_a_quit_shortcut(self) -> None:
        w = self._window()
        keys = [seq.toString(QKeySequence.SequenceFormat.PortableText) for seq in w.exit_action.shortcuts()]
        self.assertEqual(keys, ["Ctrl+Q"])

    def test_closing_the_window_only_hides_it(self) -> None:
        w = self._window()
        self.assertTrue(w.isVisible())
        w.close()
        self.app.processEvents()
        self.assertFalse(w.isVisible(), "pencere gizlenmeli")


if __name__ == "__main__":
    unittest.main()
