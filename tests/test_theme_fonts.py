"""ui_font_families: tray_icon.py bu işlevi içe aktarır (eksikliği exe'yi açılışta çökertiyordu)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.theme import ui_font_families  # noqa: E402


class UiFontFamiliesTests(unittest.TestCase):
    def test_windows_prefers_segoe_ui(self) -> None:
        self.assertEqual(ui_font_families("win32")[0], "Segoe UI")

    def test_every_platform_returns_non_empty_list_of_strings(self) -> None:
        for plat in ("win32", "darwin", "linux"):
            fams = ui_font_families(plat)
            self.assertTrue(fams and all(isinstance(f, str) and f for f in fams), plat)

    def test_tray_icon_module_imports(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import src.gui.tray_icon  # noqa: F401


if __name__ == "__main__":
    unittest.main()
