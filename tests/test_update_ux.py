"""Güncelleme deneyimi: pop-up yok; başlık çubuğunda ve tepsinin en üstünde "Güncelle · vX"; kullanılmıyorken otomatik kurulum."""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401
from support import FakeConfig, make_update_app  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import src.app as app_module  # noqa: E402
from src.gui.main_window import CustomTitleBar  # noqa: E402

APP = app_module.Application


class IdleRuleTest(unittest.TestCase):
    def test_truth_table(self):
        idle = APP.update_is_idle
        self.assertFalse(idle(1, False, False), "aktarım sürerken kurulmaz")
        self.assertFalse(idle(0, True, False), "pencere ekrandayken kurulmaz")
        self.assertFalse(idle(0, False, True), "açık bir diyalog varken kurulmaz")
        self.assertTrue(idle(0, False, False), "pencere gizli/simge durumundayken ve aktarım yokken uygun")


def make_app(**extra):
    """Gerçek güncelleme yöntemleri + kaydedici sahte çağrılar (`calls`)."""
    app = make_update_app(pending=False)
    app.calls = calls = []
    app.window.set_update_available = lambda v: calls.append(("pill", v))
    app.tray_icon = types.SimpleNamespace(
        set_update_available=lambda v, version="": calls.append(("tray", v, version)),
        show_message=lambda *a: calls.append(("balloon", a[1])) or True,
    )
    app._schedule_auto_update = lambda: calls.append(("schedule",))
    app._start_silent_update = lambda: calls.append(("silent",))
    app._notify_silent_failure = lambda m: calls.append(("failure", m))
    for k, v in extra.items():
        setattr(app, k, v)
    return app


def supported():
    return mock.patch.object(app_module, "unsupported_reason", return_value=None)


class OnUpdateAvailableTest(unittest.TestCase):
    def test_optional_update_shows_button_and_never_a_dialog(self):
        app = make_app()
        with mock.patch("src.gui.update_dialog.UpdateDialog", side_effect=AssertionError("pop-up açılmamalı")):
            APP._on_update_available(app, "1.2.3", "https://x", "notlar", False, 100, "ab")
        self.assertIn(("pill", "1.2.3"), app.calls)
        self.assertIn(("tray", True, "1.2.3"), app.calls, "tepsi satırı sürüm numarasını da alır")
        self.assertIn(("schedule",), app.calls)
        self.assertNotIn(("silent",), app.calls)
        self.assertEqual(app._pending_update["version"], "1.2.3")

    def test_mandatory_update_installs_in_background_when_no_transfer(self):
        app = make_app()
        APP._on_update_available(app, "2.0.0", "https://x", "", True, 100, "ab")
        self.assertIn(("silent",), app.calls)

    def test_mandatory_update_waits_for_running_transfers(self):
        app = make_app(transfer_manager=types.SimpleNamespace(get_active_transfers=lambda: [object()]))
        APP._on_update_available(app, "2.0.0", "https://x", "", True, 100, "ab")
        self.assertNotIn(("silent",), app.calls)
        self.assertIn(("pill", "2.0.0"), app.calls)
        self.assertIsNotNone(app._pending_update)

    def test_a_newer_version_discards_the_stale_ready_package(self):
        app = make_app(_ready_update={"version": "1.2.3", "path": "p"})
        APP._on_update_available(app, "1.3.0", "https://x", "", False, 100, "ab")
        self.assertIsNone(app._ready_update, "eski sürümün indirilmiş paketi yeni sürüm diye kurulmasın")
        app.update_installer.cleanup.assert_called_once()

    def test_the_update_signal_carries_sizes_above_two_gigabytes(self):
        from src.utils.updater import UpdateChecker

        support.qt_app()
        seen = []
        checker = UpdateChecker()
        checker.update_available.connect(lambda *a: seen.append(a))
        checker.update_available.emit("1.2.3", "u", "", False, 5_000_000_000, "")
        self.assertEqual(seen[0][4], 5_000_000_000)


class AutoUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_ = QApplication.instance() or QApplication([])

    def _fake(self, *, enabled, idle, pending=True):
        app = make_app()
        app._pending_update = {"version": "1.2.3", "download_url": "u", "file_size": 1, "checksum": "a" * 64} if pending else None
        app._auto_update_enabled = lambda: enabled
        app._is_idle_for_update = lambda: idle
        return app

    def test_installs_only_when_enabled_idle_and_pending(self):
        for enabled, idle, pending, expect in (
            (True, True, True, True),
            (False, True, True, False),
            (True, False, True, False),
            (True, True, False, False),
        ):
            app = self._fake(enabled=enabled, idle=idle, pending=pending)
            with supported():
                APP._try_auto_update(app)
            self.assertEqual(("silent",) in app.calls, expect, (enabled, idle, pending))

    def test_update_without_a_checksum_is_never_installed_automatically(self):
        for checksum in ("", None, "abc", "zz" * 32):
            app = self._fake(enabled=True, idle=True)
            app._pending_update["checksum"] = checksum
            with supported():
                APP._try_auto_update(app)
            self.assertNotIn(("silent",), app.calls, checksum)

    def test_does_not_start_a_second_download(self):
        app = self._fake(enabled=True, idle=True)
        app.download_thread = types.SimpleNamespace(isRunning=lambda: True)
        with supported():
            APP._try_auto_update(app)
        self.assertNotIn(("silent",), app.calls)

    def test_a_declined_version_is_not_installed_automatically(self):
        """"Daha sonra" dedikten sonra otomatik kurulum o sürümü kurmaz; tepsi/düğme kalır."""
        app = self._fake(enabled=True, idle=True)
        app.config = FakeConfig(declined_update_version="1.2.3")
        with supported():
            APP._try_auto_update(app)
        self.assertNotIn(("silent",), app.calls)
        self.assertIsNotNone(app._pending_update)

    def test_a_newer_version_than_the_declined_one_is_installed_again(self):
        app = self._fake(enabled=True, idle=True)
        app.config = FakeConfig(declined_update_version="1.2.2")
        with supported():
            APP._try_auto_update(app)
        self.assertIn(("silent",), app.calls)

    def test_a_mandatory_update_ignores_the_declined_version(self):
        app = self._fake(enabled=True, idle=True)
        app._pending_update["is_mandatory"] = True
        app.config = FakeConfig(declined_update_version="1.2.3")
        with supported():
            APP._try_auto_update(app)
        self.assertIn(("silent",), app.calls)

    def test_running_from_source_never_installs_automatically(self):
        app = self._fake(enabled=True, idle=True)
        with mock.patch.object(app_module, "unsupported_reason", return_value="source"):
            APP._try_auto_update(app)
        self.assertNotIn(("silent",), app.calls)

    def test_scheduler_does_nothing_when_auto_install_is_off(self):
        app = make_app()
        app._auto_update_enabled = lambda: False
        APP._schedule_auto_update(app)
        self.assertIsNone(app._auto_update_timer)

    def test_enabled_needs_both_settings(self):
        for check, install, expect in ((True, True, True), (True, False, False), (False, True, False)):
            values = {"auto_update_check": check, "auto_update_install": install}
            app = types.SimpleNamespace(config=types.SimpleNamespace(get=lambda sec, key, default=None, v=values: v.get(key, default)))
            self.assertEqual(APP._auto_update_enabled(app), expect)

    def test_default_is_on(self):
        from src.utils.config import get_config

        self.assertIs(get_config().get("advanced", "auto_update_install", None), True)


class SilentFailureTest(unittest.TestCase):
    def test_background_download_failure_has_no_modal(self):
        app = make_app(_silent_update=True)
        with mock.patch.object(QMessageBox, "critical", side_effect=AssertionError("modal açılmamalı")):
            APP._on_download_failed(app, "ağ koptu")
        self.assertIn(("failure", "ağ koptu"), app.calls)
        self.assertFalse(app._silent_update)

    def test_background_install_failure_has_no_modal(self):
        app = make_app(_silent_update=True)
        with mock.patch.object(QMessageBox, "critical", side_effect=AssertionError("modal açılmamalı")):
            APP._on_install_failed(app, "izin yok")
        self.assertIn(("failure", "izin yok"), app.calls)

    def test_silent_download_is_postponed_without_modal_when_a_transfer_starts(self):
        app = make_app(_silent_update=True,
                       transfer_manager=types.SimpleNamespace(get_active_transfers=lambda: [object()]))
        with supported(), mock.patch.object(QMessageBox, "warning", side_effect=AssertionError("modal açılmamalı")):
            APP._start_update_download(app, "1.2.3", "https://x", 10, "")
        self.assertFalse(app._silent_update)

    def test_check_message_never_opens_a_box(self):
        app = make_app()
        with mock.patch.object(QMessageBox, "information", side_effect=AssertionError("pop-up")), \
             mock.patch.object(QMessageBox, "warning", side_effect=AssertionError("pop-up")):
            APP._on_update_check_message(app, "info", "başlık", "metin")
            APP._on_update_check_message(app, "warning", "başlık", "metin")


class SilentFailureBalloonTest(unittest.TestCase):
    """Sessiz hata bildirimi GERÇEK TrayIcon API'siyle (`show_message`) çalışmalı: eskiden var olmayan `showMessage`
    çağrılıyor, hata `except` ile yutuluyor ve bildirim hiç görünmüyordu; sahte `showMessage` testi gerçeği gizliyordu."""

    @classmethod
    def setUpClass(cls):
        cls.app_ = support.qt_app()

    def test_the_balloon_is_really_shown_through_the_tray_icon(self):
        from PyQt6.QtWidgets import QSystemTrayIcon
        from src.gui.tray_icon import TrayIcon
        from src.utils.locales import t

        tray = TrayIcon(lang="tr")
        self.assertFalse(hasattr(tray, "showMessage"), "TrayIcon'un showMessage'ı yok: show_message var")
        app = make_update_app(pending=False)
        app.tray_icon = tray
        with mock.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True), \
             mock.patch.object(QSystemTrayIcon, "showMessage") as show, \
             mock.patch.object(app_module, "get_active_language", return_value="tr"):
            APP._notify_silent_failure(app, "ağ koptu")
        show.assert_called_once()
        title, message, icon = show.call_args.args[:3]
        self.assertEqual((title, message), ("TransferTCP", t("update_auto_failed", "tr")))
        self.assertEqual(icon, QSystemTrayIcon.MessageIcon.Warning)
        self.assertTrue(any("ağ koptu" in e for e in app.logger.errors))

    def test_without_a_tray_the_fallback_toast_is_used(self):
        from src.gui.tray_icon import TrayIcon

        tray = TrayIcon(lang="tr")
        app = make_update_app(pending=False)
        app.tray_icon = tray
        with mock.patch.object(TrayIcon, "is_system_tray_available", staticmethod(lambda: False)), \
             mock.patch.object(app_module.SystemToast, "show") as toast, \
             mock.patch.object(app_module, "get_active_language", return_value="en"):
            APP._notify_silent_failure(app, "x")
        toast.assert_called_once()
        self.assertIn("automatic update", toast.call_args.args[1].lower())


class TrayUpdateRowTest(unittest.TestCase):
    """Tepsi menüsü: "Güncelle · v{sürüm}" EN ÜSTTE, kalın, yalnızca güncelleme bekliyorsa görünür; menü yeniden
    kurulsa da durum korunur (tepsi kapat-aç sonrası satır gizli kalıyordu)."""

    @classmethod
    def setUpClass(cls):
        cls.app_ = support.qt_app()

    def tray(self, lang="tr"):
        from src.gui.tray_icon import TrayIcon

        tray = TrayIcon(lang=lang)
        self.addCleanup(tray.menu.deleteLater)
        return tray

    def test_row_is_first_with_a_separator_below_and_hidden_until_an_update_is_pending(self):
        tray = self.tray()
        actions = tray.menu.actions()
        self.assertIs(actions[0], tray.update_action, "güncelleme satırı menünün EN ÜSTÜNDE")
        self.assertTrue(actions[1].isSeparator(), "altına ayırıcı")
        self.assertFalse(tray.update_action.isVisible())
        self.assertFalse(actions[1].isVisible())
        tray.set_update_available(True, "1.2.3")
        self.assertTrue(tray.update_action.isVisible())
        self.assertTrue(actions[1].isVisible())
        tray.set_update_available(False)
        self.assertFalse(tray.update_action.isVisible())
        self.assertFalse(actions[1].isVisible())

    def test_text_is_bold_and_follows_the_language(self):
        tray = self.tray("tr")
        tray.set_update_available(True, "1.2.3")
        self.assertEqual(tray.update_action.text(), "Güncelle · v1.2.3")
        self.assertTrue(tray.update_action.font().bold())
        self.assertFalse(tray.update_action.icon().isNull(), "güncelleme ikonu")
        tray.retranslate("en")
        self.assertEqual(tray.update_action.text(), "Update · v1.2.3")
        tray.retranslate("tr")
        self.assertEqual(tray.update_action.text(), "Güncelle · v1.2.3")

    def test_the_old_bottom_row_is_gone(self):
        from src.utils.locales import LOCALES

        tray = self.tray()
        tray.set_update_available(True, "1.2.3")
        texts = [a.text() for a in tray.menu.actions()]
        self.assertFalse(any("Güncelleme mevcut" in x for x in texts))
        self.assertNotIn("update_available", LOCALES["tr"])
        self.assertIs(tray.menu.actions()[-1], tray.quit_action)

    def test_state_survives_a_menu_rebuild(self):
        tray = self.tray()
        tray.set_update_available(True, "1.2.3")
        tray._create_menu()  # menü sonradan (yeniden) kuruldu
        self.addCleanup(tray.menu.deleteLater)
        self.assertIs(tray.menu.actions()[0], tray.update_action)
        self.assertTrue(tray.update_action.isVisible())
        self.assertEqual(tray.update_action.text(), "Güncelle · v1.2.3")
        self.assertTrue(tray.menu.actions()[1].isVisible())

    def test_a_rebuild_keeps_the_externally_bound_state_sync(self):
        tray = self.tray()
        tray.sync_state = lambda: None
        marker = tray.sync_state
        tray._create_menu()
        self.addCleanup(tray.menu.deleteLater)
        self.assertIs(tray.sync_state, marker)

    def test_click_asks_for_the_update_window_and_never_installs(self):
        tray = self.tray()
        got = []
        tray.update_requested.connect(lambda: got.append("window"))
        tray.set_update_available(True, "1.2.3")
        tray.update_action.trigger()
        self.assertEqual(got, ["window"])

    def test_tooltip_follows_the_pending_update_and_language(self):
        tray = self.tray("tr")
        tray.set_update_available(True, "1.2.3")
        self.assertIn("1.2.3", tray.tray.toolTip())
        tray.retranslate("en")
        self.assertIn("Update available", tray.tray.toolTip())
        tray.set_update_available(False)
        self.assertEqual(tray.tray.toolTip(), "TransferTCP")

    def test_application_wires_the_tray_row_to_the_update_window(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "app.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("self.tray_icon.update_requested.connect(self.show_pending_update)", source)


class _DialogStub(support.FakeUpdateDialog):
    """UpdateDialog yerine geçer: kurucu argümanlarını saklar, exec() hemen döner."""

    last = None

    def __init__(self, **kwargs):
        super().__init__()
        _DialogStub.last = self
        self.kwargs = kwargs
        for name in ("update_accepted", "update_deferred", "update_cancelled"):
            setattr(self, name, types.SimpleNamespace(connect=lambda f: None))

    def exec(self):
        self.calls.append("exec")
        return 0


class OpenDialogTest(unittest.TestCase):
    """Tepsiden açılan pencere ana pencere gizliyken de öne gelir; açıkken ikinci pencere açılmaz."""

    @classmethod
    def setUpClass(cls):
        cls.app_ = support.qt_app()

    def open(self, app):
        timers = []
        with mock.patch("src.gui.update_dialog.UpdateDialog", _DialogStub), \
             mock.patch.object(app_module.QTimer, "singleShot", lambda ms, fn: timers.append(fn)), \
             mock.patch.object(app_module, "get_active_language", return_value="tr"):
            APP._open_update_dialog(app)
        return timers

    def test_dialog_is_shown_with_size_and_brought_to_front_when_the_main_window_is_hidden(self):
        app = make_update_app(visible=False)
        timers = self.open(app)
        kwargs = _DialogStub.last.kwargs
        self.assertIsNone(kwargs["parent"], "ana pencere gizliyken diyalog ona bağlanmaz (kendi görev çubuğu düğmesi)")
        self.assertEqual(kwargs["file_size"], 1000)
        self.assertEqual(kwargs["version"], "1.2.3")
        self.assertIn("exec", _DialogStub.last.calls)
        self.assertIsNone(app.update_dialog, "kapanınca referans temizlenir")
        self.assertEqual(len(timers), 1, "öne getirme zamanlayıcısı kuruldu")
        timers[0]()
        self.assertIn("raise", _DialogStub.last.calls)
        self.assertIn("activate", _DialogStub.last.calls)

    def test_visible_main_window_becomes_the_parent(self):
        app = make_update_app(visible=True)
        self.open(app)
        self.assertIs(_DialogStub.last.kwargs["parent"], app.window)

    def test_second_request_raises_the_open_dialog_instead_of_opening_another(self):
        dialog = support.FakeUpdateDialog()
        app = make_update_app(dialog=dialog)
        with mock.patch("src.gui.update_dialog.UpdateDialog", side_effect=AssertionError("ikinci pencere açılmamalı")):
            APP._open_update_dialog(app)
        self.assertEqual(dialog.calls, ["raise", "activate"])

    def test_dialog_opened_during_a_background_download_shows_the_downloading_state(self):
        app = make_update_app()
        app._update_phase = "downloading"
        self.open(app)
        self.assertIn("downloading", _DialogStub.last.calls)


class TitleBarPillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_ = QApplication.instance() or QApplication([])

    def _bar(self):
        window = types.SimpleNamespace(
            showMinimized=lambda: None, close=lambda: None,
            isMaximized=lambda: False,
        )
        from PyQt6.QtWidgets import QWidget

        parent = QWidget()
        parent.showMinimized = lambda: None
        return CustomTitleBar(parent), parent, window

    def test_pill_shows_version_follows_language_and_hides(self):
        bar, _parent, _ = self._bar()
        self.assertTrue(bar.update_btn.isHidden())
        bar.set_update_available("1.2.3")
        self.assertFalse(bar.update_btn.isHidden())
        self.assertEqual(bar.update_btn.text(), "Güncelle · v1.2.3")
        bar.retranslate("en")
        self.assertEqual(bar.update_btn.text(), "Update · v1.2.3")
        bar.set_update_available("")
        self.assertTrue(bar.update_btn.isHidden())

    def test_click_emits_signal(self):
        bar, _parent, _ = self._bar()
        got = []
        bar.update_clicked.connect(lambda: got.append(1))
        bar.set_update_available("1.2.3")
        bar.update_btn.click()
        self.assertEqual(got, [1])


class LocaleTest(unittest.TestCase):
    def test_new_strings_exist_in_both_languages(self):
        from src.utils.locales import t

        for lang in ("tr", "en"):
            for key in ("update_pill", "update_pill_tip", "update_new_version", "update_status_current",
                        "update_status_failed", "auto_update_install", "update_auto_failed", "check_now",
                        "tray_update_now", "update_size_line", "update_failed_inline", "update_retry",
                        "update_installed_toast", "update_no_write", "update_blocked_inline", "update_busy_inline",
                        "update_unsupported_source", "update_unsupported_os"):
                self.assertNotEqual(t(key, lang), key, (lang, key))
        self.assertEqual(t("check_now", "tr"), "Kontrol Et")
        self.assertEqual(t("tray_update_now", "tr").format(version="1.2.3"), "Güncelle · v1.2.3")
        self.assertEqual(t("tray_update_now", "en").format(version="1.2.3"), "Update · v1.2.3")
        self.assertEqual(t("update_size_line", "tr").format(size="40.00 MB"), "İndirme boyutu: 40.00 MB")
        self.assertEqual(t("update_size_line", "en").format(size="40.00 MB"), "Download size: 40.00 MB")
        self.assertEqual(t("update_failed_inline", "tr").format(error="x"), "Güncelleme tamamlanamadı: x")
        self.assertEqual(t("update_failed_inline", "en").format(error="x"), "The update could not be completed: x")
        self.assertEqual(t("update_retry", "tr"), "Tekrar Dene")
        self.assertEqual(t("update_installed_toast", "tr").format(app="TransferTCP", version="1.2.3"),
                         "TransferTCP v1.2.3 sürümüne güncellendi.")
        self.assertEqual(t("update_installed_toast", "en").format(app="TransferTCP", version="1.2.3"),
                         "TransferTCP was updated to v1.2.3.")

    def test_removed_popup_texts_are_gone(self):
        from src.utils.locales import LOCALES

        for key in ("update_cancel_title", "update_cancel_confirm", "update_blocked_title", "update_blocked_message",
                    "download_error_title", "download_error_message", "install_error_title", "install_error_message"):
            for lang in ("tr", "en"):
                self.assertNotIn(key, LOCALES[lang], f"{lang}: {key} (QMessageBox metni) kalkmalıydı")


class ManualCheckFailureTest(unittest.TestCase):
    """Elle denetim başarısızsa (çevrimdışı, bozuk yanıt) "Güncel" değil "Denetlenemedi" gösterilmeli."""

    @classmethod
    def setUpClass(cls):
        cls.app_ = QApplication.instance() or QApplication([])

    @staticmethod
    def _reply(body: bytes):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body
        return mock.Mock(return_value=response)

    def _settings_result(self, urlopen):
        """Gerçek denetim + ayarlar penceresinin sonuç mantığı: ((finish durumu, metin), [(düzey, ileti)])."""
        from src.gui.settings import SettingsDialog
        from src.utils.updater import UpdateChecker

        checker = UpdateChecker()
        dialog = types.SimpleNamespace(_check_failed=False, _checking_updates=True, lang="tr",
                                       update_check=mock.Mock(), _pending_update_version=lambda: "")
        messages = []

        def on_message(level, title, text):
            messages.append((level, text))
            SettingsDialog._on_check_message(dialog, level, title, text)

        checker.check_message.connect(on_message)
        with mock.patch("src.utils.updater.urllib.request.urlopen", urlopen), \
             mock.patch("src.utils.updater.get_active_language", return_value="tr"):
            checker._check_for_updates_sync(True)
        SettingsDialog._on_manual_update_done(dialog)
        return dialog.update_check.finish.call_args.args, messages

    def test_offline_and_broken_replies_report_could_not_check(self):
        import urllib.error
        from src.utils.locales import t

        for urlopen in (mock.Mock(side_effect=urllib.error.URLError("getaddrinfo failed")),
                        mock.Mock(side_effect=TimeoutError("timed out")),
                        self._reply(b"<html>not json"),
                        self._reply(b'{"updateAvailable": true}')):
            with self.subTest(urlopen=urlopen):
                result, messages = self._settings_result(urlopen)
                self.assertEqual(result, ("fail", t("update_status_failed", "tr")), "başarısız denetim 'Güncel' gösterdi")
                self.assertEqual(messages, [("warning", t("update_check_failed_msg", "tr"))])

    def test_up_to_date_reply_still_reports_current(self):
        (state, _text), messages = self._settings_result(self._reply(b'{"updateAvailable": false}'))
        self.assertEqual(state, "ok")
        self.assertEqual([level for level, _ in messages], ["info"])


if __name__ == "__main__":
    unittest.main()
