"""Ilk kurulum: eski uc ardisik kutu (cihaz adi / klasor / "kurulum tamam") yerine TEK karsilama penceresi.

* "Basla": secilen ad + klasor kaydedilir; bos ad bilgisayar adina doner.
* Esc / X: varsayilanlarla (bilgisayar adi + Indirilenler) devam edilir; kimse kutularla yuzlesmez.
* Cikis (ornegin tepsiden) pencere acikken istenirse hicbir sey kaydedilmez (first_run acik kalir, sonraki acilista sorulur).

(Eski sozlesme: iptal -> "Cikmak istiyor musunuz?" sorusu. Karsilama ekraniyla bu soru kalkti; test yeni davranisa
gore guncellendi, "cikis istenince dongu yeni pencere acmaz" korumasi korundu.)
"""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from src.app import Application  # noqa: E402
from src.gui.welcome_dialog import WelcomeDialog  # noqa: E402


class _Cfg:
    def __init__(self):
        self.values = {}

    def get(self, *a, **k):
        return k.get("default") if "default" in k else (a[2] if len(a) > 2 else None)

    def set(self, section, key, value):
        self.values[(section, key)] = value


def _fake_app():
    window = QWidget()  # karsilama penceresinin sahibi (gercek bir QWidget olmali)
    return types.SimpleNamespace(config=_Cfg(), window=window, logger=mock.Mock())


def _run(fake, exec_side_effect):
    with mock.patch.object(WelcomeDialog, "exec", new=lambda dialog: exec_side_effect(dialog)), \
         mock.patch("src.app.get_active_language", return_value="tr"), \
         mock.patch("src.app.get_hostname", return_value="BILGISAYAR"), \
         mock.patch("src.app.get_default_download_dir", return_value="C:/Indirilenler"):
        Application._run_first_time_setup(fake)


class FirstSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_start_saves_the_chosen_name_and_folder(self) -> None:
        fake = _fake_app()

        def user_starts(dialog):
            dialog.name_edit.setText("  Ofis PC  ")
            dialog.folder_edit.setText("D:/Gelenler")
            dialog.start_btn.click()
            return 1

        _run(fake, user_starts)
        self.assertEqual(fake.config.values[("general", "device_name")], "Ofis PC")
        self.assertEqual(fake.config.values[("transfer", "download_folder")], "D:/Gelenler")
        self.assertIs(fake.config.values[("general", "first_run")], False)

    def test_blank_name_falls_back_to_the_computer_name(self) -> None:
        fake = _fake_app()

        def blank(dialog):
            dialog.name_edit.setText("   ")
            dialog.start_btn.click()
            return 1

        _run(fake, blank)
        self.assertEqual(fake.config.values[("general", "device_name")], "BILGISAYAR")
        self.assertEqual(fake.config.values[("transfer", "download_folder")], "C:/Indirilenler")

    def test_escape_continues_with_the_defaults_without_asking_anything(self) -> None:
        fake = _fake_app()

        def user_cancels(dialog):
            dialog.name_edit.setText("yazdim ama vazgectim")
            dialog.reject()  # Esc / X
            return 0

        _run(fake, user_cancels)
        self.assertEqual(fake.config.values[("general", "device_name")], "BILGISAYAR")
        self.assertEqual(fake.config.values[("transfer", "download_folder")], "C:/Indirilenler")
        self.assertIs(fake.config.values[("general", "first_run")], False)

    def test_quit_while_the_welcome_is_open_saves_nothing(self) -> None:
        fake = _fake_app()
        app = self.app

        def tray_quit(dialog):
            app.aboutToQuit.emit()  # tepsiden "Cikis": acik pencere aninda doner
            return 0

        _run(fake, tray_quit)
        self.assertEqual(fake.config.values, {}, "kurulum yarim kaldi: first_run dahil hicbir sey yazilmamali")

    def test_welcome_dialog_has_a_custom_title_bar_and_no_native_frame(self) -> None:
        from PyQt6.QtCore import Qt

        dialog = WelcomeDialog(None, "tr", "PC", "C:/x")
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(dialog.title_bar.title_label.text(), "TransferTCP'ye Hoş Geldiniz")
        self.assertEqual(dialog.values(), ("PC", "C:/x"))


if __name__ == "__main__":
    unittest.main()
