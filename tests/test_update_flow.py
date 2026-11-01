"""Güncelleme akışı (src.app.Application): boşta -> indirme -> kurma -> hata -> tekrar dene, iptal, aktarım denetimleri.

Pencere/QApplication açılmaz; Application'ın GERÇEK güncelleme yöntemleri sahte `self` üzerinde çalışır
(`support.make_update_app`). İş parçacıkları, kurucu ve pencere sahtedir; hiçbir QMessageBox çağrılmamalıdır.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401
from support import FakeUpdateDialog, make_update_app  # noqa: E402

import src.app as app_module  # noqa: E402
from src.utils import self_update  # noqa: E402

APP = app_module.Application


def no_modal():
    """Güncelleme hatalarında hiçbir QMessageBox açılmamalı."""
    fail = AssertionError("QMessageBox açılmamalı")
    return mock.patch.multiple("PyQt6.QtWidgets.QMessageBox", critical=mock.Mock(side_effect=fail),
                               warning=mock.Mock(side_effect=fail), information=mock.Mock(side_effect=fail),
                               question=mock.Mock(side_effect=fail))


def supported():
    """Kaynaktan çalışma denetimini geçer (testler paketlenmemiş çalışır)."""
    return mock.patch.object(app_module, "unsupported_reason", return_value=None)


def writable():
    return mock.patch.object(self_update, "check_writable", return_value=None)


class DownloadCompleteTest(unittest.TestCase):
    def test_mandatory_update_without_dialog_still_starts_installation(self) -> None:
        """Eski hata: diyalog yoksa (zorunlu güncelleme) indirme biter ama kurulum hiç başlamazdı."""
        app = make_update_app(dialog=None, mandatory=True)
        app._update_phase = "downloading"
        with mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._on_download_complete(app, "C:/x/update.pkg")
        single_shot.assert_called_once()
        self.assertEqual(single_shot.call_args.args[1], app._start_installation)

    def test_dialog_flow_shows_done_then_installs(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        app._update_phase = "downloading"
        with mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._on_download_complete(app, "C:/x/update.pkg")
        self.assertEqual(dialog.calls, ["complete"])
        single_shot.assert_called_once()

    def test_unverified_download_is_logged(self) -> None:
        app = make_update_app()
        app._update_phase = "downloading"
        app.update_installer.last_verified = False
        with mock.patch.object(app_module.QTimer, "singleShot"):
            APP._on_download_complete(app, "C:/x/update.pkg")
        self.assertTrue(any("doğrulanamadı" in w for w in app.logger.warnings))

    def test_a_package_finished_after_the_user_cancelled_is_never_installed(self) -> None:
        app = make_update_app()
        app._update_phase = "idle"  # iptal edildi
        with mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._on_download_complete(app, "C:/x/update.pkg")
        single_shot.assert_not_called()
        app.update_installer.cleanup.assert_called_once()
        self.assertIsNone(app._ready_update)

    def test_ready_package_is_remembered_with_its_version(self) -> None:
        app = make_update_app()
        app._update_phase = "downloading"
        app._downloading_version = "1.2.3"
        with mock.patch.object(app_module.QTimer, "singleShot"):
            APP._on_download_complete(app, "C:/x/update.pkg")
        self.assertEqual(app._ready_update, {"version": "1.2.3", "path": "C:/x/update.pkg"})


class DownloadFailedTest(unittest.TestCase):
    def test_user_cancellation_is_not_an_error(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        app._update_phase = "idle"
        with no_modal():
            APP._on_download_failed(app, "cancelled")
        self.assertEqual(app.logger.errors, [])
        self.assertEqual(dialog.calls, [], "iptalde satır içi hata gösterilmez")

    def test_real_failure_is_shown_inline_and_the_window_stays_open(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        app._update_phase = "downloading"
        with no_modal(), mock.patch.object(app_module, "get_active_language", return_value="en"):
            APP._on_download_failed(app, "Dosya bütünlüğü doğrulanamadı (checksum).")
        self.assertEqual(dialog.calls, [("error", "File integrity could not be verified (checksum).", True)])
        self.assertNotIn("reject", dialog.calls, "pencere kapanmaz")
        self.assertIs(app.update_dialog, dialog)
        self.assertEqual(app._update_phase, "idle")

    def test_mandatory_download_failure_keeps_the_pending_update_usable(self) -> None:
        """Eski hata: zorunlu güncellemede `_pending_update` silinir, düğme/tepsi öğesi çalışmaz olurdu."""
        app = make_update_app(mandatory=True)
        app._silent_update = True
        with no_modal():
            APP._on_download_failed(app, "ağ koptu")
        self.assertIsNotNone(app._pending_update)
        self.assertEqual(app._pending_update["version"], "1.2.3")
        self.assertFalse(app._silent_update)

    def test_transfer_completion_starting_a_mandatory_update_does_not_clear_it(self) -> None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "app.py"), encoding="utf-8") as handle:
            source = handle.read()
        block = source[source.index("starting pending update"):]
        block = block[:block.index("elif self._auto_update_enabled()")]
        self.assertNotIn("self._pending_update = None", block)


class CancelTest(unittest.TestCase):
    def test_cancel_stops_download_loop_and_remembers_the_decision(self) -> None:
        app = make_update_app()
        app._update_phase = "downloading"
        app._downloading_version = "1.2.3"
        APP._cancel_update_download(app)
        app.update_installer.cancel_download.assert_called_once()
        self.assertEqual(app._update_phase, "idle")
        self.assertEqual(app.config.get("advanced", "declined_update_version"), "1.2.3",
                         "iptal edilen güncelleme arkadan kendiliğinden yeniden indirilmesin")

    def test_closing_the_dialog_during_download_cancels_and_does_not_restart_the_app(self) -> None:
        """Gerçek pencere: indirme sürerken X/Esc -> update_cancelled; sonra indirme tamamlansa da kurulum olmaz."""
        from PyQt6.QtWidgets import QApplication
        from src.gui.update_dialog import UpdateDialog

        support.qt_app()
        app = make_update_app()
        dialog = UpdateDialog("1.2.3", "n", False, None, "tr", 1000)
        self.addCleanup(dialog.deleteLater)
        dialog.update_cancelled.connect(lambda: app._cancel_update_download())
        app._update_phase = "downloading"
        app._downloading_version = "1.2.3"
        dialog.show_downloading_state()
        dialog.reject()
        QApplication.processEvents()
        self.assertEqual(app._update_phase, "idle")
        with mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._on_download_complete(app, "C:/x/update.pkg")  # iptalden sonra biten indirme
        single_shot.assert_not_called()


class StartDownloadTest(unittest.TestCase):
    def start(self, app, **kw):
        info = app._pending_update
        APP._start_update_download(app, info["version"], info["download_url"], info["file_size"], info["checksum"])

    def test_happy_path_starts_one_download_thread(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        with supported(), writable(), no_modal(), mock.patch.object(app_module, "DownloadThread") as thread_cls:
            self.start(app)
        thread_cls.assert_called_once_with(app.update_installer, "https://macik.com.tr/x", 1000, "a" * 64)
        thread_cls.return_value.start.assert_called_once()
        self.assertEqual(app._update_phase, "downloading")
        self.assertEqual(dialog.calls, ["downloading"])

    def test_a_second_download_never_starts_while_one_is_running(self) -> None:
        for phase, thread_running in (("downloading", False), ("installing", False), ("idle", True)):
            with self.subTest(phase=phase, thread=thread_running):
                dialog = FakeUpdateDialog()
                app = make_update_app(dialog=dialog)
                app._update_phase = phase
                if thread_running:
                    app.download_thread = mock.Mock(isRunning=lambda: True)
                with supported(), writable(), mock.patch.object(app_module, "DownloadThread") as thread_cls:
                    self.start(app)
                thread_cls.assert_not_called()

    def test_active_transfer_gives_an_inline_notice_and_returns_to_normal(self) -> None:
        """Pencere 'indiriliyor'da takılmasın: satır içi ileti + normale dön, QMessageBox yok."""
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog, transfers=2)
        with supported(), writable(), no_modal(), mock.patch.object(app_module, "DownloadThread") as thread_cls, \
                mock.patch.object(app_module, "get_active_language", return_value="tr"):
            self.start(app)
        thread_cls.assert_not_called()
        self.assertEqual(app._update_phase, "idle")
        self.assertEqual(len(dialog.calls), 1)
        kind, text = dialog.calls[0]
        self.assertEqual(kind, "notice")
        self.assertIn("2", text)
        self.assertNotIn("downloading", dialog.calls)

    def test_active_transfer_postpones_a_silent_update_without_a_modal(self) -> None:
        app = make_update_app(transfers=1)
        app._silent_update = True
        with supported(), writable(), no_modal(), mock.patch.object(app_module, "DownloadThread") as thread_cls:
            self.start(app)
        thread_cls.assert_not_called()
        self.assertFalse(app._silent_update)

    def test_running_from_source_shows_an_inline_message_and_never_downloads(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        with mock.patch.object(app_module, "unsupported_reason", return_value="source"), no_modal(), \
                mock.patch.object(app_module, "DownloadThread") as thread_cls, \
                mock.patch.object(app_module, "get_active_language", return_value="tr"):
            self.start(app)
        thread_cls.assert_not_called()
        (kind, message, retry), = dialog.calls
        self.assertEqual(kind, "error")
        self.assertIn("kaynak", message)
        self.assertFalse(retry, "yeniden denemenin anlamı yok")

    def test_read_only_folder_is_reported_before_downloading(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        broken = mock.patch.object(self_update, "check_writable", side_effect=self_update.PackageError("izin yok"))
        with supported(), broken, no_modal(), mock.patch.object(app_module, "DownloadThread") as thread_cls, \
                mock.patch.object(app_module, "get_active_language", return_value="tr"), \
                mock.patch.object(app_module, "current_exe", return_value=r"C:\Program Files\TransferTCP\TransferTCP.exe"):
            self.start(app)
        thread_cls.assert_not_called()
        (kind, message, retry), = dialog.calls
        self.assertEqual(kind, "error")
        self.assertIn(r"C:\Program Files\TransferTCP", message)
        self.assertIn("yazılabilir", message)
        self.assertEqual(app._update_phase, "idle")

    def test_ready_package_is_reused_instead_of_downloading_again(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        ready = os.path.join(support.fresh_dir("ready"), "TransferTCP_Update.pkg")
        support.write_file(ready, b"x")
        app._ready_update = {"version": "1.2.3", "path": ready}
        with supported(), writable(), mock.patch.object(app_module, "DownloadThread") as thread_cls, \
                mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            self.start(app)
        thread_cls.assert_not_called()
        self.assertEqual(app.update_installer.downloaded_file, ready)
        single_shot.assert_called_once()
        self.assertEqual(single_shot.call_args.args[1], app._start_installation)

    def test_a_ready_package_of_another_version_is_not_reused(self) -> None:
        app = make_update_app()
        ready = os.path.join(support.fresh_dir("ready"), "TransferTCP_Update.pkg")
        support.write_file(ready, b"x")
        app._ready_update = {"version": "0.9.0", "path": ready}
        with supported(), writable(), mock.patch.object(app_module, "DownloadThread") as thread_cls:
            self.start(app)
        thread_cls.assert_called_once()


class InstallFlowTest(unittest.TestCase):
    def test_transfer_started_after_the_download_postpones_the_install(self) -> None:
        """Kurmadan hemen önce aktarım yeniden denetlenir: başladıysa kurma, beklemeye dön (hazır paket korunur)."""
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog, transfers=1)
        app._update_phase = "downloading"
        app._ready_update = {"version": "1.2.3", "path": "p"}
        with no_modal(), mock.patch.object(app_module, "InstallThread") as thread_cls, \
                mock.patch.object(app_module, "get_active_language", return_value="tr"):
            APP._start_installation(app)
        thread_cls.assert_not_called()
        self.assertEqual(app._update_phase, "idle")
        self.assertEqual(dialog.calls[0][0], "notice")
        self.assertIsNotNone(app._ready_update)

    def test_silent_install_postponed_by_a_new_transfer_goes_back_to_waiting(self) -> None:
        app = make_update_app(transfers=1)
        app._update_phase = "downloading"
        app._silent_update = True
        with mock.patch.object(app_module, "InstallThread") as thread_cls:
            APP._start_installation(app)
        thread_cls.assert_not_called()
        self.assertFalse(app._silent_update)
        self.assertEqual(app._update_phase, "idle")

    def test_install_runs_in_a_thread_and_the_dialog_shows_installing(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        app._update_phase = "downloading"
        with mock.patch.object(app_module, "InstallThread") as thread_cls:
            APP._start_installation(app)
        thread_cls.assert_called_once_with(app.update_installer, False, "1.0.0")
        thread_cls.return_value.start.assert_called_once()
        self.assertEqual(app._update_phase, "installing")
        self.assertEqual(dialog.calls, ["installing"])

    def test_visible_is_true_only_for_a_shown_and_not_minimized_window(self) -> None:
        for visible, minimized, expected in ((True, False, True), (True, True, False), (False, False, False), (False, True, False)):
            with self.subTest(visible=visible, minimized=minimized):
                app = make_update_app(visible=visible, minimized=minimized)
                app._update_phase = "downloading"
                with mock.patch.object(app_module, "InstallThread") as thread_cls:
                    APP._start_installation(app)
                self.assertIs(thread_cls.call_args.args[1], expected)

    def test_install_is_ignored_when_the_flow_was_cancelled(self) -> None:
        app = make_update_app()
        app._update_phase = "idle"
        with mock.patch.object(app_module, "InstallThread") as thread_cls:
            APP._start_installation(app)
        thread_cls.assert_not_called()

    def test_successful_install_quits_cleanly_without_killing_anything(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        app.stop = mock.Mock()
        with mock.patch.object(app_module.QApplication, "quit") as quit_:
            APP._on_install_complete(app)
        quit_.assert_called_once()
        app.tray_icon.hide.assert_called_once()
        self.assertTrue(app._quitting_for_update)
        self.assertIn("install_complete", dialog.calls)
        self.assertIn("hide", dialog.calls, "pencere cikistan once gizlenmeli (gorunur pencereyle cikis Qt kapanisinda crash verebiliyordu)")
        self.assertLess(dialog.calls.index("install_complete"), dialog.calls.index("hide"))
        app.stop.assert_not_called()  # kapanış aboutToQuit -> stop() ile; zorla öldürme yok

    def test_install_failure_is_inline_cleans_the_package_and_allows_retry(self) -> None:
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        app._update_phase = "installing"
        app._ready_update = {"version": "1.2.3", "path": "p"}
        with no_modal(), mock.patch.object(app_module, "get_active_language", return_value="en"):
            APP._on_install_failed(app, "Pakette uygulamanın exe dosyası yok")
        self.assertEqual(dialog.calls, [("error", "The package does not contain the application's exe", True)])
        self.assertEqual(app._update_phase, "idle")
        self.assertIsNone(app._ready_update)
        app.update_installer.cleanup.assert_called_once()
        self.assertIsNotNone(app._pending_update)

    def test_full_cycle_idle_download_install_error_retry_install(self) -> None:
        """boşta -> indirme -> kurma -> hata -> tekrar dene -> indirme -> kurma."""
        dialog = FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        threads = []

        def thread_factory(*args):
            thread = mock.Mock()
            thread.isRunning.return_value = False  # iş parçacıkları hemen biter
            threads.append((args, thread))
            return thread

        with supported(), writable(), no_modal(), \
                mock.patch.object(app_module, "DownloadThread", side_effect=thread_factory), \
                mock.patch.object(app_module, "InstallThread", side_effect=thread_factory), \
                mock.patch.object(app_module.QTimer, "singleShot"), \
                mock.patch.object(app_module, "get_active_language", return_value="tr"):
            APP._on_dialog_update_accepted(app)                    # Şimdi Güncelle
            self.assertEqual(app._update_phase, "downloading")
            APP._on_download_complete(app, "p")                    # indirme bitti
            APP._start_installation(app)                           # kuruluyor
            self.assertEqual(app._update_phase, "installing")
            APP._on_install_failed(app, "Yeni sürüm yerine konamadı: x")  # hata: pencere açık, satır içi
            self.assertEqual(app._update_phase, "idle")
            self.assertEqual(dialog.calls[-1][0], "error")
            APP._on_dialog_update_accepted(app)                    # Tekrar dene
            self.assertEqual(app._update_phase, "downloading")
            APP._on_download_complete(app, "p")
            APP._start_installation(app)
        self.assertEqual(len(threads), 4, "iki indirme + iki kurulum")
        self.assertEqual(app._update_phase, "installing")


class DeferTest(unittest.TestCase):
    def test_later_records_the_declined_version_and_keeps_the_tray_item(self) -> None:
        app = make_update_app()
        APP._defer_update(app)
        self.assertEqual(app.config.get("advanced", "declined_update_version"), "1.2.3")
        app.tray_icon.set_update_available.assert_called_with(True, "1.2.3")


if __name__ == "__main__":
    unittest.main()
