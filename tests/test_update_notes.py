"""Güncelleme penceresi sürüm notları: düz metinde satır sonları korunur, HTML ise HTML olarak gösterilir."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401

from PyQt6.QtWidgets import QApplication, QTextEdit  # noqa: E402

from src.gui.update_dialog import UpdateDialog  # noqa: E402


class UpdateNotesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _notes(self, text):
        dialog = UpdateDialog("1.2.3", text, False, None, "tr")
        self.addCleanup(dialog.deleteLater)
        return dialog.findChild(QTextEdit)

    def test_plain_text_keeps_its_line_breaks(self):
        box = self._notes("Yenilikler:\n- bir\n- iki")
        self.assertEqual(box.toPlainText().splitlines(), ["Yenilikler:", "- bir", "- iki"])

    def test_html_notes_are_still_rendered_as_html(self):
        box = self._notes("<p>Merhaba</p><ul><li>madde</li></ul>")
        self.assertIn("madde", box.toPlainText())
        self.assertNotIn("<li>", box.toPlainText())

    def test_empty_notes_fall_back_to_a_default_line(self):
        self.assertTrue(self._notes("").toPlainText().strip())


if __name__ == "__main__":
    unittest.main()
