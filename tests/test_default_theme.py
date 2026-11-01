"""İlk açılışta tema "Sistem" gelmeli; otomatik başlatma varsayılan kapalı kalmalı (ilk kurulum sorusu hariç)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)


class DefaultsTest(unittest.TestCase):
    def test_fresh_config_follows_the_system_theme(self) -> None:
        from src.utils.config import get_config

        self.assertEqual(get_config().get("ui", "theme", "BOS"), "system")

    def test_window_fallbacks_do_not_force_dark(self) -> None:
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "gui" / "main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("'ui', 'theme', 'dark'", source)


if __name__ == "__main__":
    unittest.main()
