"""Tutarlilik isi (30 Ekim 2026): kapatma/cikis, gonder dugmelerinin pasifligi (T5), tepsi iskeleti, Ctrl+, , ayarlarda
canli onizleme + Iptal'de geri alma, ozel kutu/pencere cercevesi, bildirim yolu, locales bicimi."""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QSystemTrayIcon  # noqa: E402

from src.gui.message_box import MessageBox  # noqa: E402
from src.models.device import Device  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _device(ip="192.168.18.99", name="HP", online=True) -> Device:
    device = Device(ip, 38520, name, name)
    device.is_online = online
    return device


def _no_box(box):
    raise AssertionError(f"kutu acilmamaliydi: {box.windowTitle()!r}")


class _QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        # Ortak (surec capi) ayar nesnesi ve gorunum durumu baska test dosyalarina sizmasin
        import copy

        from src.gui import message_box, palette
        from src.utils.config import get_config

        # Pencereler gercekten silinsin (deleteLater olay dongusu olmadan islenmez): yoksa her MainWindow uygulama
        # duzeyinde olay suzgeci ve buyuk QSS ile yasamaya devam edip sonraki testleri (ag testleri) yavaslatir.
        self.addCleanup(lambda: QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))

        config = get_config()
        snapshot = copy.deepcopy(config.config)

        from src.utils.logger import get_logger

        log = get_logger()
        log_state = (log.logger.level, log.logger.disabled, [(h, h.level) for h in log.logger.handlers])

        def restore() -> None:
            config.config = snapshot
            config.save()
            # Ayarlar'da Kaydet gunluk duzeyini surec capinda degistirir (WARNING): sonraki testlere sizmasin
            log.logger.setLevel(log_state[0])
            log.logger.disabled = log_state[1]
            for handler, level in log_state[2]:
                handler.setLevel(level)
            palette.set_accent_override(None)
            message_box.reset_configuration()
            self.app.setProperty("tt_dark", None)

        self.addCleanup(restore)

        # Gercek "Acilista Baslat" kaydina ne dokunulur ne de ondan okunur: Kaydet gercek HKCU Run'a yazmaya kalkmasin
        for name, value in (("is_in_startup", False), ("add_to_startup", True), ("remove_from_startup", True)):
            patcher = mock.patch(f"src.utils.startup.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        MessageBox.set_test_hook(None)

    def _window(self):
        from src.gui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.deleteLater)
        return window


class CloseAndQuitTest(_QtCase):
    def test_holding_ctrl_while_closing_no_longer_quits(self) -> None:
        """Eski "Ctrl basiliyken kapat = cik" hilesi kalkti: X / Alt+F4 her zaman yalnizca gizler."""
        window = self._window()
        window.show()
        self.app.processEvents()
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.KeyboardModifier.ControlModifier), \
             mock.patch.object(QApplication, "quit") as quit_:
            window.close()
        self.app.processEvents()
        self.assertFalse(window.isVisible())
        quit_.assert_not_called()

    def test_quit_application_is_the_explicit_exit(self) -> None:
        window = self._window()
        with mock.patch.object(QApplication, "quit") as quit_:
            window.quit_application()
        quit_.assert_called_once()

    def test_main_no_longer_shows_an_already_running_box(self) -> None:
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("QMessageBox", source)
        self.assertNotIn("already_running", source)

    def test_maximize_glyph_pair_is_square_and_restore(self) -> None:
        window = self._window()
        self.assertEqual(window.title_bar.maximize_btn.text(), "□")
        with mock.patch.object(window, "isMaximized", return_value=True):
            window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        self.assertEqual(window.title_bar.maximize_btn.text(), "❐")
        with mock.patch.object(window, "isMaximized", return_value=False):
            window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        self.assertEqual(window.title_bar.maximize_btn.text(), "□")


class SendNeedsAReadyTargetTest(_QtCase):
    """T5: cihaz secili degilken / cevrimdisiyken gonderme dugmeleri, birakma alani ve menu eylemi pasif (ipucu var);
    hicbir diyalog acilmaz."""

    def test_no_device_selected(self) -> None:
        window = self._window()
        self.assertFalse(window.drop_zone.select_btn.isEnabled())
        self.assertFalse(window.drop_zone.select_folder_btn.isEnabled())
        self.assertFalse(window.drop_zone.acceptDrops())
        self.assertFalse(window.send_action.isEnabled())
        self.assertTrue(window.send_action.toolTip(), "pasif eylemin nedeni ipucunda yazmali")
        self.assertTrue(window.drop_zone.select_btn.toolTip())

    def test_offline_device_blocks_sending_but_online_enables_it(self) -> None:
        window = self._window()
        window.device_list.add_device(_device(online=False))
        self.app.processEvents()
        self.assertFalse(window.send_action.isEnabled())
        self.assertFalse(window.drop_zone.acceptDrops())
        window.device_list.update_device(_device(online=True))
        self.app.processEvents()
        self.assertTrue(window.send_action.isEnabled())
        self.assertTrue(window.drop_zone.acceptDrops())
        self.assertEqual(window.send_action.toolTip(), window.send_action.text(), "hazirken engel ipucu kalmaz")
        self.assertEqual(window.drop_zone.select_btn.toolTip(), "")

    def test_no_dialog_opens_when_nothing_can_be_sent(self) -> None:
        window = self._window()
        MessageBox.set_test_hook(_no_box)
        with mock.patch.object(QFileDialog, "getOpenFileNames", side_effect=AssertionError("dosya secici acilmamali")), \
             mock.patch.object(QFileDialog, "getExistingDirectory", side_effect=AssertionError("klasor secici acilmamali")):
            window._select_files()
            window._select_folder()
            window.device_list.add_device(_device(online=False))
            window._select_files()
            window._on_device_selected_for_send(_device(online=False))  # cevrimdisi cihaza cift tik
        self.assertEqual(window.device_list.get_selected_device().ip, "192.168.18.99", "cift tik cevrimdisi cihazi secer")

    def test_double_click_selects_the_clicked_device_not_the_first_one(self) -> None:
        window = self._window()
        window.device_list.add_device(_device("10.0.0.1", name="Birinci"))
        window.device_list.add_device(_device("10.0.0.2", name="Ikinci"))
        with mock.patch.object(QFileDialog, "getOpenFileNames", return_value=([], "")):
            window._on_device_selected_for_send(_device("10.0.0.2", name="Ikinci"))
        self.assertEqual(window.device_list.get_selected_device().ip, "10.0.0.2")


class ShortcutsTest(_QtCase):
    def test_ctrl_comma_opens_settings(self) -> None:
        window = self._window()
        keys = [seq.toString(QKeySequence.SequenceFormat.PortableText) for seq in window.settings_action.shortcuts()]
        self.assertEqual(keys, ["Ctrl+,"])
        with mock.patch("src.gui.main_window.SettingsDialog") as dialog_cls:
            window.settings_action.trigger()
        dialog_cls.assert_called_once()
        dialog_cls.return_value.exec.assert_called_once()

    def test_f1_is_still_about(self) -> None:
        window = self._window()
        self.assertEqual([s.toString() for s in window.about_action.shortcuts()], ["F1"])

    def test_file_menu_stays_with_send_and_exit(self) -> None:
        window = self._window()
        texts = [a.text() for a in window.file_menu.actions() if not a.isSeparator()]
        self.assertEqual(len(texts), 2)
        self.assertEqual(window.file_btn.text(), "Dosya" if window.lang == "tr" else "File")
        for action in window.file_menu.actions():
            self.assertFalse(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", action.text()), "menude emoji kalmamali")
        self.assertFalse(window.send_action.icon().isNull())
        self.assertFalse(window.exit_action.icon().isNull())


class TrayMenuSkeletonTest(_QtCase):
    def _tray(self, lang="tr"):
        from src.gui.tray_icon import TrayIcon

        tray = TrayIcon(lang=lang)
        self.addCleanup(tray.tray.deleteLater)
        return tray

    def test_order_is_update_show_settings_theme_language_exit(self) -> None:
        tray = self._tray()
        tray.window_visible = lambda: False  # pencere gizli: "Goster"
        tray.refresh_window_action()
        labels = []
        for action in tray.menu.actions():
            labels.append("---" if action.isSeparator() else ("update" if action is tray.update_action else action.text()))
        self.assertEqual(labels, ["update", "---", "Göster", "---", "Ayarlar", "Tema", "Dil", "---", "Çıkış"])

    def test_show_hide_label_follows_the_window_state(self) -> None:
        tray = self._tray()
        tray.window_visible = lambda: True
        tray.refresh_window_action()
        self.assertEqual(tray.show_action.text(), "Gizle")
        tray.window_visible = lambda: False
        tray.refresh_window_action()
        self.assertEqual(tray.show_action.text(), "Göster")
        tray.retranslate("en")
        self.assertEqual(tray.show_action.text(), "Show")
        tray.window_visible = lambda: True
        tray.refresh_window_action()
        self.assertEqual(tray.show_action.text(), "Hide")

    def test_show_hide_action_toggles(self) -> None:
        tray = self._tray()
        events = []
        tray.show_window.connect(lambda: events.append("show"))
        tray.hide_window.connect(lambda: events.append("hide"))
        tray.window_visible = lambda: True
        tray.show_action.trigger()
        tray.window_visible = lambda: False
        tray.show_action.trigger()
        self.assertEqual(events, ["hide", "show"])

    def test_single_click_and_double_click_both_show_the_window(self) -> None:
        tray = self._tray()
        events = []
        tray.show_window.connect(lambda: events.append(1))
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        tray._on_activated(QSystemTrayIcon.ActivationReason.Context)
        self.assertEqual(len(events), 2)

    def test_menu_icons_follow_the_accent_and_there_is_no_fixed_sky_blue(self) -> None:
        from src.gui import palette
        from src.gui.tray_icon import TrayIcon

        palette.set_accent_override("rose")
        self.addCleanup(palette.set_accent_override, None)
        tray = TrayIcon(lang="tr")
        self.addCleanup(tray.tray.deleteLater)
        tray.refresh_icons()
        image = tray.settings_action.icon().pixmap(20, 20).toImage()
        painted = {image.pixelColor(x, y).name() for x in range(20) for y in range(20) if image.pixelColor(x, y).alpha() > 200}
        self.assertIn(palette.ACCENTS["rose"]["accent"].lower(), painted)
        self.assertNotIn("#38bdf8", painted)


class SettingsPreviewTest(_QtCase):
    """T14: tema / dil / vurgu ayarlarda canli onizlenir; Iptal eski gorunume doner; Kaydet kalici yapar."""

    def _open(self):
        from src.gui import palette
        from src.gui.settings import SettingsDialog
        from src.utils.config import get_config

        self.addCleanup(palette.set_accent_override, None)
        window = self._window()
        config = get_config()
        config.set("ui", "theme", "dark")
        config.set("ui", "language", "tr")
        config.set("ui", "accent", "cyan")
        window.restore_appearance()
        dialog = SettingsDialog(window)
        self.addCleanup(dialog.deleteLater)
        return window, dialog, config

    def test_theme_language_and_accent_preview_without_saving(self) -> None:
        window, dialog, config = self._open()
        self.assertEqual(window.current_theme, "dark")
        dialog.theme_combo.setCurrentIndex(2)  # Acik
        self.assertEqual(window.current_theme, "light")
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))
        self.assertEqual(window.lang, "en")
        self.assertEqual(window.file_btn.text(), "File")
        dialog._on_accent_chosen("rose")
        self.assertEqual(window.color_btn.icon().isNull(), False)
        from src.gui import palette
        self.assertEqual(palette.accent_key(), "rose")
        # hicbiri kaydedilmedi
        self.assertEqual((config.get("ui", "theme"), config.get("ui", "language"), config.get("ui", "accent")),
                         ("dark", "tr", "cyan"))

    def test_cancel_restores_the_previous_look(self) -> None:
        window, dialog, config = self._open()
        dialog.theme_combo.setCurrentIndex(2)
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))
        dialog._on_accent_chosen("rose")
        dialog.reject()
        from src.gui import palette
        self.assertEqual(window.current_theme, "dark")
        self.assertEqual(window.lang, "tr")
        self.assertEqual(window.file_btn.text(), "Dosya")
        self.assertEqual(palette.accent_key(), "cyan")

    def test_save_persists_and_keeps_the_preview(self) -> None:
        window, dialog, config = self._open()
        dialog.theme_combo.setCurrentIndex(2)
        dialog._on_accent_chosen("violet")
        dialog.save_btn.click()
        self.assertEqual(config.get("ui", "theme"), "light")
        self.assertEqual(config.get("ui", "accent"), "violet")
        from src.gui import palette
        self.assertEqual(palette.accent_key(), "violet")
        self.assertEqual(window.current_theme, "light")

    def test_dialog_is_custom_framed_and_tab_title_keeps_the_ampersand(self) -> None:
        window, dialog, _ = self._open()
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(dialog.tab_widget.tabText(2).replace("&&", "&"), "Ağ ve Gelişmiş")
        self.assertEqual(len(dialog._accent_btns), 10)
        self.assertTrue(dialog._accent_btns["cyan"].isChecked())

    def test_update_checkboxes_share_the_same_hint_and_labels(self) -> None:
        from src.utils.locales import t

        window, dialog, _ = self._open()
        self.assertEqual(dialog.auto_update_check.text(), "Güncellemeleri Otomatik Kontrol Et")
        self.assertEqual(dialog.auto_update_install.text(), "Güncellemeleri Otomatik Kur")
        self.assertEqual(dialog.auto_update_check.toolTip(), dialog.auto_update_install.toolTip())
        self.assertEqual(dialog.auto_update_check.toolTip(),
                         "Yeni sürüm bulunduğunda arka planda indirilir ve uygulama kullanılmıyorken kurulur.")
        self.assertEqual(t("auto_start", "tr"), "Açılışta Başlat")
        self.assertEqual(t("auto_start", "en"), "Start at Login")
        self.assertEqual(dialog.auto_start_check.text(), "Açılışta Başlat")

    def test_notification_and_sound_defaults_are_unchanged(self) -> None:
        from src.utils.config import ConfigManager

        defaults = ConfigManager()._default_config["general"]
        self.assertIs(defaults["notifications_enabled"], True)
        self.assertIs(defaults["play_sounds"], True)
        self.assertIs(defaults["auto_start"], False)


class DialogsAreCustomFramedTest(_QtCase):
    def test_no_native_message_boxes_or_dialogs_in_the_source(self) -> None:
        offenders = []
        for folder, _dirs, files in os.walk(os.path.join(ROOT, "src")):
            for name in files:
                if not name.endswith(".py") or name == "message_box.py":
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                code = re.sub(r'""".*?"""', "", text, flags=re.S)
                code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))
                if re.search(r"\bQMessageBox\b|\bQInputDialog\b|class \w+\(QDialog\)|\bQDialog\(", code):
                    offenders.append(os.path.relpath(path, ROOT))
        self.assertEqual(offenders, [], "yerel baslikli QDialog/QMessageBox/QInputDialog kalmamali")

    def test_every_dialog_has_the_custom_title_bar(self) -> None:
        from src.gui.about_dialog import AboutDialog
        from src.gui.history_dialog import HistoryDialog
        from src.gui.manual_device_dialog import ManualDeviceDialog
        from src.gui.settings import SettingsDialog
        from src.gui.trust_dialog import TrustDeviceDialog
        from src.gui.update_dialog import UpdateDialog
        from src.gui.welcome_dialog import WelcomeDialog

        dialogs = [
            AboutDialog(None, "tr", "1.0.0"), HistoryDialog(None, "tr"), ManualDeviceDialog(None, "tr", 38520),
            SettingsDialog(), TrustDeviceDialog("t", "b", "f", "a", "r"), UpdateDialog("1.2.3", "n", False, None, "tr"),
            WelcomeDialog(None, "tr", "PC", "C:/x"),
        ]
        for dialog in dialogs:
            self.addCleanup(dialog.deleteLater)
            self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint, type(dialog).__name__)
            self.assertTrue(hasattr(dialog, "title_bar"), type(dialog).__name__)
            self.assertEqual(dialog.title_bar.title_label.text(), dialog.windowTitle(), type(dialog).__name__)

    def test_history_is_guided_when_empty(self) -> None:
        from src.gui.history_dialog import HistoryDialog
        from src.models.database import get_database
        from src.utils.locales import t

        get_database().clear_history()
        dialog = HistoryDialog(None, "tr")
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.empty_box.isHidden())
        self.assertTrue(dialog.text_edit.isHidden())
        self.assertFalse(dialog.clear_btn.isEnabled())
        self.assertEqual(dialog.empty_title.text(), t("history_empty_title", "tr"))
        self.assertIn("cihaz seçip", dialog.empty_hint.text())

    def test_manual_add_keeps_the_dialog_and_shows_the_error_inline(self) -> None:
        from src.gui.manual_device_dialog import ManualDeviceDialog

        MessageBox.set_test_hook(_no_box)
        dialog = ManualDeviceDialog(None, "tr", 38520)
        self.addCleanup(dialog.deleteLater)
        dialog.ip_edit.setText("abc")
        dialog.try_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertFalse(dialog.error_label.isHidden())
        dialog.ip_edit.setText("192.168.1.42")
        self.assertTrue(dialog.error_label.isHidden(), "yeniden yazinca hata kalkar")
        dialog.try_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_values(), ("192.168.1.42", "192.168.1.42", 38520))

    def test_message_box_palette_follows_the_app_theme_and_accent(self) -> None:
        from src.gui import message_box, palette

        palette.install_message_box()
        self.addCleanup(message_box.reset_configuration)
        self.addCleanup(palette.set_accent_override, None)
        window = self._window()
        window.apply_theme("light", accent="rose")
        pal = message_box.current_palette()
        self.assertEqual(pal["base"], "#e0e0e0")
        self.assertEqual(pal["accent"].lower(), palette.ACCENTS["rose"]["accent"].lower())
        window.apply_theme("dark")
        self.assertEqual(message_box.current_palette()["base"], "#1a1a1a")


class NotificationPathTest(_QtCase):
    def test_toast_goes_through_the_shared_notifier_and_the_tray_balloon(self) -> None:
        from src.gui.toast import SystemToast

        class _Tray:
            shown = []

            def isVisible(self):
                return True

            def showMessage(self, title, body, icon, ms):
                self.shown.append((title, body, ms))

        tray = _Tray()
        self.addCleanup(SystemToast.reset)
        SystemToast.configure(lambda: tray, supports_messages=lambda: True, platform="win32")
        with mock.patch("subprocess.run", side_effect=AssertionError("Windows'ta alt surec acilmamali")):
            self.assertTrue(SystemToast.show("Baslik", "Ileti", duration="long"))
        self.assertEqual(tray.shown, [("Baslik", "Ileti", 10000)])

    def test_without_a_tray_windows_starts_nothing_and_reports_false(self) -> None:
        from src.gui.toast import SystemToast

        self.addCleanup(SystemToast.reset)
        SystemToast.configure(lambda: None, platform="win32")
        with mock.patch("subprocess.run", side_effect=AssertionError("alt surec yok")):
            self.assertFalse(SystemToast.show("a", "b"))

    def test_winotify_is_gone(self) -> None:
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as handle:
            self.assertNotIn("winotify", handle.read().lower())
        with open(os.path.join(ROOT, "TransferTCP.spec"), encoding="utf-8") as handle:
            self.assertNotIn("winotify", handle.read().lower())


class LocalesFormatTest(unittest.TestCase):
    def setUp(self) -> None:
        from src.utils.locales import LOCALES

        self.locales = LOCALES

    def test_both_languages_have_the_same_keys(self) -> None:
        self.assertEqual(set(self.locales["tr"]), set(self.locales["en"]))

    def test_three_dots_are_one_ellipsis_character(self) -> None:
        for lang, table in self.locales.items():
            for key, value in table.items():
                self.assertNotIn("...", value, f"{lang}.{key}")

    def test_labels_have_no_trailing_colon(self) -> None:
        for lang in ("tr", "en"):
            for key in ("device_name", "computer_name", "local_ip", "download_folder", "port", "chunk_size", "speed_limit",
                        "concurrent_transfers", "log_level", "language", "theme", "accent", "update_notes"):
                self.assertFalse(self.locales[lang][key].endswith(":"), f"{lang}.{key}")

    def test_no_user_facing_windows_word_for_the_startup_setting(self) -> None:
        for lang in ("tr", "en"):
            self.assertNotIn("Windows", self.locales[lang]["auto_start"])

    def test_control_labels_are_title_case(self) -> None:
        small = {"ve", "and", "to", "in", "of", "for", "the", "with", "from", "a", "after", "without", "at", "by"}
        keys = ("auto_start", "start_minimized", "show_notifications", "play_sounds", "auto_open", "overwrite_existing",
                "enable_logging", "auto_update", "auto_update_install", "encryption_enabled", "accept_from_anyone",
                "clear_trusted", "check_now", "update_retry", "retry", "update_later", "update_now", "update_notes",
                "reset_defaults", "device_name", "download_folder", "send_file", "clear_history", "welcome_title")
        for lang in ("tr", "en"):
            for key in keys:
                for index, word in enumerate(re.split(r"[\s/]+", self.locales[lang][key])):
                    letters = re.sub(r"[^\w]", "", word)
                    if not letters or letters.lower() in small and index > 0 or letters.isdigit():
                        continue
                    self.assertTrue(letters[0].isupper(), f"{lang}.{key}: {word!r}")

    def test_retry_and_check_use_one_form(self) -> None:
        self.assertEqual(self.locales["tr"]["retry"], self.locales["tr"]["update_retry"])
        self.assertEqual(self.locales["tr"]["check_now"], "Kontrol Et")
        self.assertEqual(self.locales["tr"]["update_retry"], "Tekrar Dene")

    def test_t_without_a_language_uses_the_chosen_one(self) -> None:
        from src.utils.config import get_config
        from src.utils.locales import t

        config = get_config()
        old = config.get("ui", "language", "auto")
        self.addCleanup(config.set, "ui", "language", old)
        config.set("ui", "language", "en")
        self.assertEqual(t("settings"), "Settings")
        config.set("ui", "language", "tr")
        self.assertEqual(t("settings"), "Ayarlar")

    def test_accent_names_come_from_the_tables(self) -> None:
        from src.gui.palette import ACCENTS, accent_label

        self.assertEqual(accent_label("cyan", "tr"), "Turkuaz")
        self.assertEqual(accent_label("cyan", "en"), "Cyan")
        self.assertEqual(len(ACCENTS), 10)
        self.assertEqual(ACCENTS["cyan"]["accent"], "#00ACC1")


if __name__ == "__main__":
    unittest.main()


class RealRegistryIsProtectedTest(unittest.TestCase):
    """Kullanicinin gercek HKCU Run TransferTCP degerine hicbir test yazamaz (yazma girisimi AssertionError)."""

    @unittest.skipUnless(sys.platform == "win32", "winreg yalnizca Windows'ta")
    def test_writing_to_the_real_registry_is_refused(self) -> None:
        import winreg

        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with self.assertRaises(AssertionError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE)
        with self.assertRaises(AssertionError):
            winreg.SetValueEx(winreg.HKEY_CURRENT_USER, "TransferTCP", 0, winreg.REG_SZ, "x")
        with self.assertRaises(AssertionError):
            winreg.DeleteValue(winreg.HKEY_CURRENT_USER, "TransferTCP")
        # okuma serbest
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ)
        winreg.CloseKey(key)

    @unittest.skipUnless(sys.platform == "win32", "winreg yalnizca Windows'ta")
    def test_the_real_startup_api_cannot_change_the_run_value(self) -> None:
        from src.utils import startup

        before = len(support.REGISTRY_WRITE_ATTEMPTS)
        self.assertFalse(startup.add_to_startup(minimized=True), "gercek kayit defterine yazilamaz")
        self.assertFalse(startup.remove_from_startup())
        self.assertGreater(len(support.REGISTRY_WRITE_ATTEMPTS), before)
