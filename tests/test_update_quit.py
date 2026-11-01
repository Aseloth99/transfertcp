"""Kurulum bitince eski süreç GERÇEKTEN çıkmalı: görünür "Kuruluyor" penceresi `QApplication.quit()`'i iptal ettirmemeli.

E2E'de (gerçek exe) bulundu: pencereli akışta pencere INSTALLING durumunda kapanmayı reddeder; Qt 6'da `quit()` görünür pencereleri
kapatmayı dener, reddeden varsa çıkış iptal olur → eski süreç sonsuza dek yaşıyor, yeni süreç `--wait-pid` için 15 sn bekleyip vazgeçiyordu.
Önceki birim testleri pencereyi sahte nesneyle değiştirdiği için görmedi: burada GERÇEK UpdateDialog ve gerçek olay döngüsü var.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402

from src.gui.update_dialog import UpdateDialog  # noqa: E402


class QuitForUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = support.qt_app()

    def _app(self):
        dialog = UpdateDialog("1.2.3", "notlar", False, None, "tr", 1000)
        dialog.show_installing_state()
        dialog.show()
        self.assertTrue(dialog.isVisible())
        # kurulum durumundaki pencere close()'u reddeder: gerçekten yok et (modal pencere sızmasın); çıkış yolu zaten yok etmiş olabilir
        self.addCleanup(lambda: None if sip.isdeleted(dialog) else sip.delete(dialog))
        return support.make_update_app(dialog=dialog)

    def _run_loop(self, app) -> int:
        QTimer.singleShot(0, lambda: app._quit_for_update())
        QTimer.singleShot(3000, lambda: QCoreApplication.exit(99))
        return self.qapp.exec()

    def test_the_event_loop_ends_even_though_the_installing_dialog_refuses_to_close(self):
        self.assertEqual(self._run_loop(self._app()), 0, "döngü 0 ile bitmeli (99 = açık pencere çıkışı iptal ettirdi)")

    def test_the_update_dialog_is_hidden_before_the_process_exits(self):
        """E2E (A3): görünür pencereyle çıkış bazı koşularda Qt kapanışında yerel `access violation` verdi (crash.log)."""
        app = self._app()
        dialog = app.update_dialog
        seen = []

        def at_exit():
            seen.append(dialog.isVisible())

        self.qapp.aboutToQuit.connect(at_exit)
        self.addCleanup(self.qapp.aboutToQuit.disconnect, at_exit)
        self.assertEqual(self._run_loop(app), 0)
        self.assertEqual(seen, [False], "çıkış anında güncelleme penceresi hâlâ görünür")

    def test_the_update_dialog_is_destroyed_while_qapplication_is_still_alive(self):
        """E2E (FlexiKey v3, 100'er koşu): yalnızca `hide()` çökmeyi azalttı (16/100 -> 5/100) ama BİTİRMEDİ. `hide()` `finished`
        sinyalini vermez; pencere Python sonlandırmasına kadar yaşar ve yıkım sırası rastgele kalır. Pencere çıkıştan ÖNCE yok edilmeli."""
        app = self._app()
        dialog = app.update_dialog
        self.assertEqual(self._run_loop(app), 0)
        self.assertTrue(sip.isdeleted(dialog), "güncelleme penceresi çıkışta yok edilmedi (yalnızca gizlendi)")
        self.assertIsNone(app.update_dialog, "uygulama silinmiş pencereye referans tutmamalı")

    def test_quitting_without_an_update_dialog_still_works(self):
        self.assertEqual(self._run_loop(support.make_update_app(dialog=None)), 0)

    def test_gui_objects_are_destroyed_in_a_fixed_order_before_python_finalizes(self):
        """E2E: `hide()+deleteLater()` sonrası bile çökme sürdü (düzeltmesiz %12-16, kalan ~%1). VEH yığını: Py_FinalizeEx -> PyQt6
        atexit temizliği -> sip.pyd okuma hatası. PyQt6 sahipsiz QObject'leri (ana pencere, tepsi, menüler) koşudan koşuya değişen
        sırayla siler. GUI nesneleri `exec()` sonrası BİLİNEN sırayla (pencere -> menüler -> tepsi -> ana pencere) yok edilir."""
        import types
        from PyQt6.QtCore import QObject
        from PyQt6.QtWidgets import QMenu, QWidget
        import src.app as app_module

        order = []

        def track(name, obj):
            obj.destroyed.connect(lambda *_: order.append(name))
            return obj

        tray = track("tray_icon", QObject())
        tray.menu = track("menu", QMenu())
        tray.theme_menu = track("theme_menu", QMenu())
        tray.lang_menu = track("lang_menu", QMenu())
        tray.tray = track("tray", QObject())
        fake = types.SimpleNamespace(
            tray_icon=tray, window=track("window", QWidget()), update_dialog=track("dialog", QWidget()),
        )
        everything = [tray, tray.menu, tray.theme_menu, tray.lang_menu, tray.tray, fake.window, fake.update_dialog]
        app_module.Application.teardown_qt_objects(fake)
        self.assertTrue(all(sip.isdeleted(o) for o in everything), "bazı GUI nesneleri yok edilmedi")
        self.assertEqual(order, ["dialog", "lang_menu", "theme_menu", "menu", "tray", "tray_icon", "window"])
        app_module.Application.teardown_qt_objects(fake)  # ikinci çağrı zararsız (silinmiş nesneler atlanır)

    def test_teardown_ignores_missing_or_fake_objects(self):
        import types
        from unittest import mock
        import src.app as app_module

        app_module.Application.teardown_qt_objects(types.SimpleNamespace(tray_icon=mock.Mock(), window=mock.Mock(), update_dialog=None))
        app_module.Application.teardown_qt_objects(types.SimpleNamespace())  # hiçbir öznitelik yok

    def test_the_hard_exit_watchdog_is_armed_only_for_the_frozen_app(self):
        import src.app as app_module
        with mock.patch.object(app_module.self_update, "arm_exit_watchdog") as arm, \
                mock.patch("src.utils.update_policy.is_frozen", return_value=False):
            self._run_loop(self._app())
        arm.assert_not_called()
        with mock.patch.object(app_module.self_update, "arm_exit_watchdog") as arm, \
                mock.patch("src.utils.update_policy.is_frozen", return_value=True):
            self._run_loop(self._app())
        arm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
