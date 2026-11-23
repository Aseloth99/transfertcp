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


def _rgb(color: str) -> tuple:
    h = color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lumina_mix(a: str, b: str, amount: float) -> str:
    (ra, ga, ba), (rb, gb, bb) = _rgb(a), _rgb(b)
    return "#" + "".join(f"{max(0, min(255, round(x + (y - x) * amount))):02x}" for x, y in ((ra, rb), (ga, gb), (ba, bb)))


def _lumina_contrast(a: str, b: str) -> float:
    def lum(color):
        def lin(v):
            s = v / 255.0
            return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

        r, g, b = (lin(v) for v in _rgb(color))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _close(a: str, b: str, tolerance: int = 1) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(_rgb(a), _rgb(b)))


def _same_icon(a, b, size: int = 32) -> bool:
    return a.pixmap(size, size).toImage() == b.pixmap(size, size).toImage()


def _top_colors(icon, size: int = 32, count: int = 3) -> list:
    from collections import Counter

    img = icon.pixmap(size, size).toImage()
    seen = Counter(img.pixelColor(x, y).name() for x in range(size) for y in range(size)
                   if img.pixelColor(x, y).alpha() == 255)
    return [name for name, _ in seen.most_common(count)]


def _rule(qss: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", qss)
    assert match, selector
    return " ".join(match.group(1).split())


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
        """Vektör işaret (yazı değil): durum değişimi düğmeden gelmese de (Win+Yukarı, Aero Snap) işaret değişir."""
        window = self._window()
        button = window.title_bar.maximize_btn
        self.assertEqual(button.text(), "")
        self.assertEqual(button.kind(), "maximize")
        with mock.patch.object(window, "isMaximized", return_value=True):
            window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        self.assertEqual(button.kind(), "restore")
        with mock.patch.object(window, "isMaximized", return_value=False):
            window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        self.assertEqual(button.kind(), "maximize")


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
        from src.gui.icons import menu_icon

        for action, name in ((window.send_action, "send"), (window.exit_action, "exit"),
                             (window.settings_action, "settings"), (window.about_action, "info")):
            self.assertTrue(_same_icon(action.icon(), menu_icon(name)), name)


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
        # dil küresi mavi/gök aileden: vurguyu izler; ayarlar dişlisi anlam rengi (mor) taşır
        image = tray.lang_menu.icon().pixmap(32, 32).toImage()
        painted = {image.pixelColor(x, y).name() for x in range(32) for y in range(32) if image.pixelColor(x, y).alpha() > 200}
        self.assertIn(palette.ACCENTS["rose"]["accent"].lower(), painted)
        self.assertNotIn("#38bdf8", painted)
        self.assertEqual(_top_colors(tray.settings_action.icon(), count=1), ["#8b5cf6"])

    def test_rows_use_the_colored_semantic_icons(self) -> None:
        from src.gui.icons import menu_icon

        tray = self._tray()
        tray.refresh_icons()
        for item, name in ((tray.update_action, "update"), (tray.show_action, "view"), (tray.settings_action, "settings"),
                           (tray.lang_menu, "globe"), (tray.quit_action, "exit")):
            self.assertTrue(_same_icon(item.icon(), menu_icon(name)), name)
        tray.set_language_choice("tr", "tr")
        self.assertTrue(_same_icon(tray.lang_menu.icon(), menu_icon("globe")))


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
        self.assertEqual(dialog.nav_buttons[2].text().replace("&&", "&"), "Ağ ve Gelişmiş")
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
        self.assertTrue(dialog.table.isHidden())
        self.assertFalse(dialog.search_edit.isEnabled(), "geçmiş yokken arama kutusu kapalı")
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


class CheckboxAndDestructiveTest(_QtCase):
    """Onay kutusu FlexiKey/MediaCompressor/Lumina ile aynı (18 px kutu, 5 px köşe, 1 px kenar, vurgu dolgu + 4x
    çizilmiş beyaz tik, pasif+seçili gri); yıkıcı düğmeler duruşta kardeşleri gibi nötr (22 Kasım 2026)."""

    @staticmethod
    def _rule(qss: str, selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", qss)
        assert match, selector
        return " ".join(match.group(1).split())

    def test_checkbox_follows_the_shared_spec_and_the_chosen_accent(self) -> None:
        from src.gui import palette

        self.addCleanup(palette.set_accent_override, None)
        window = self._window()
        for theme, accent, fill, border, muted in (("dark", "violet", "#262626", "#454545", "9e9e9e"),
                                                   ("light", "rose", "#ececec", "#b0b0b0", "616161")):
            window.apply_theme(theme, accent=accent)
            qss = self.app.styleSheet()
            self.assertNotIn("__CHECK_TICK", qss)
            base = self._rule(qss, "QCheckBox::indicator")
            for decl in ("width: 18px;", "height: 18px;", "border-radius: 5px;", f"background-color: {fill};",
                         f"border: 1px solid {border};"):
                self.assertIn(decl, base, theme)
            spec = palette.ACCENTS[accent]
            self.assertIn(f"border-color: {spec['accent']};", self._rule(qss, "QCheckBox::indicator:unchecked:hover"))
            checked = self._rule(qss, "QCheckBox::indicator:checked")
            self.assertIn(f"background-color: {spec['accent2']};", checked)
            self.assertRegex(checked, r'image: url\("[^"]*transfertcp_check_ffffff_x4\.png"\)')
            disabled = self._rule(qss, "QCheckBox::indicator:checked:disabled")
            self.assertIn(f"background-color: {border};", disabled)
            self.assertIn(f"transfertcp_check_{muted}_x4.png", disabled)

    def test_tick_is_drawn_at_four_times_the_box(self) -> None:
        from PyQt6.QtGui import QImage

        from src.gui.icons import checkmark_png

        img = QImage(checkmark_png("#ffffff"))
        self.assertEqual((img.width(), img.height()), (64, 64))
        self.assertEqual(img.pixelColor(24, 44).name(), "#ffffff")  # (6, 11) köşesi x4
        self.assertEqual(img.pixelColor(2, 2).alpha(), 0)

    def test_cancel_all_is_neutral_at_rest_like_clear_list(self) -> None:
        for name in ("dark", "light"):
            with open(os.path.join(ROOT, "assets", "styles", f"{name}.qss"), encoding="utf-8") as fh:
                qss = fh.read()
            self.assertEqual(self._rule(qss, "QPushButton#cancelAllBtn"), self._rule(qss, "QPushButton#clearListBtn"),
                             name)


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


# ---------------------------------------------------------------------------------------------------------------
# Ayarlar iskeleti (Lumina ile aynı): üst sekmeler yerine solda renkli simgeli sekmeler; seçili sekme vurgu tonlu zemin
# + okunur vurgu yazı + solda 3 px vurgu çizgisi. Menü satırlarında renkli anlam simgeleri (aynı anlam aynı renk).
# ---------------------------------------------------------------------------------------------------------------
class SettingsNavTest(_QtCase):
    def _dialog(self):
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
        return window, dialog

    def test_sidebar_has_checkable_nav_buttons_with_colored_icons(self) -> None:
        from PyQt6.QtWidgets import QTabWidget

        from src.gui.icons import menu_icon

        _window, dialog = self._dialog()
        self.assertEqual(dialog.sidebar.objectName(), "sidebar")
        self.assertEqual(dialog.settings_pane.objectName(), "settingsPane")
        self.assertEqual([b.text().replace("&&", "&") for b in dialog.nav_buttons],
                         ["Genel", "Transfer", "Ağ ve Gelişmiş"])
        self.assertEqual(dialog.stack.count(), 3)
        self.assertEqual(dialog.findChildren(QTabWidget), [], "üst sekme çubuğu kalmadı")
        for btn, name in zip(dialog.nav_buttons, ("settings", "send", "network")):
            self.assertEqual(btn.objectName(), "nav_btn")
            self.assertTrue(btn.isCheckable() and btn.autoExclusive())
            btn.ensurePolished()   # stil sayfası uygulandıktan sonra da 38 px (QSS min/max-height sabit boyu ezmesin)
            self.assertEqual((btn.minimumHeight(), btn.maximumHeight()), (38, 38))
            self.assertTrue(_same_icon(btn.icon(), menu_icon(name)), name)
        self.assertEqual([b.isChecked() for b in dialog.nav_buttons], [True, False, False])
        dialog.nav_buttons[2].click()
        self.assertEqual(dialog.stack.currentIndex(), 2)
        self.assertEqual([b.isChecked() for b in dialog.nav_buttons], [False, False, True])
        self.assertTrue(dialog.stack.widget(0).isAncestorOf(dialog.theme_combo))
        self.assertGreaterEqual(dialog.sidebar.width(), 150)
        dialog.prepare_content()
        self.assertGreaterEqual(dialog.width(), dialog.sidebar.width() + dialog._MIN_W)

    def test_nav_rules_match_lumina(self) -> None:
        from src.gui import palette

        self.addCleanup(palette.set_accent_override, None)
        window = self._window()
        for theme, accent in (("dark", "violet"), ("light", "rose"), ("dark", "blue"), ("light", "yellow")):
            window.apply_theme(theme, accent)
            qss = window.styleSheet()
            self.assertNotIn("__NAV_", qss)
            spec = palette.ACCENTS[accent]
            side = re.search(r"background-color: (#[0-9a-fA-F]{6});", _rule(qss, "QFrame#sidebar")).group(1)
            nav = _rule(qss, "QPushButton#nav_btn")
            for decl in ("padding: 0px 10px 0px 7px;", "border: none;", "border-left: 3px solid transparent;",
                         "border-radius: 6px;", "min-height: 38px;", "max-height: 38px;"):
                self.assertIn(decl, nav)
            # sayfa yığını şeffaf: panelin içinde genel QWidget zemininden gri bir kutu kalmaz
            self.assertIn("background-color: transparent;", _rule(qss, "QStackedWidget#settingsStack"))
            checked = _rule(qss, "QPushButton#nav_btn:checked")
            tint = re.search(r"background-color: (#[0-9a-fA-F]{6});", checked).group(1)
            ink = re.search(r"(?<!-)color: (#[0-9a-fA-F]{6});", checked).group(1)
            dark = theme == "dark"
            self.assertTrue(_close(tint, _lumina_mix(side, spec["accent"], 0.16 if dark else 0.13)), (tint, accent))
            self.assertGreaterEqual(_lumina_contrast(ink, tint), 4.5, (ink, tint))
            wanted = spec["hi_dark"] if dark else spec["accent2"]
            if _lumina_contrast(wanted, tint) >= 4.5:
                self.assertEqual(ink.lower(), wanted.lower())
            self.assertIn(f"border-left: 3px solid {spec['accent']};", checked)
            self.assertIn("font-weight: 700;", checked)
            self.assertLess(qss.index("QPushButton#nav_btn:hover"), qss.index("QPushButton#nav_btn:checked"))


class MenuIconTableTest(_QtCase):
    """Renk anlamla gelir (Lumina `MENU_PALETTE`): ayarlar mor, güncelle zümrüt, çıkış/sil kırmızı, göz/kılavuz çivit,
    klasör amber; mavi/gök aile (bilgi, küre, kopya, belge) seçili vurguyu izler."""

    FIXED = {"settings": "#8b5cf6", "update": "#10b981", "exit": "#ef4444", "view": "#7c7ff5", "guide": "#7c7ff5",
             "trash": "#ef4444", "folder": "#fcd34d", "backup": "#d97706", "add": "#22c55e", "trim": "#22c55e",
             "adjust": "#f97316", "send": "#14b8a6", "network": "#06b6d4", "open_with": "#a855f7",
             "rename": "#f59e0b", "star": "#eab308", "bolt": "#eab308", "pause": "#f59e0b", "play": "#22c55e"}

    def test_same_meaning_same_color(self) -> None:
        from src.gui.icons import MENU_ICON_NAMES, menu_icon

        self.assertLessEqual(set(self.FIXED), set(MENU_ICON_NAMES))
        for name, color in self.FIXED.items():
            self.assertIn(color, _top_colors(menu_icon(name)), name)

    def test_blue_family_follows_the_accent(self) -> None:
        from src.gui import palette
        from src.gui.icons import menu_icon

        self.addCleanup(palette.set_accent_override, None)
        for key in ("rose", "green"):
            palette.set_accent_override(key)
            self.assertEqual(_top_colors(menu_icon("info"), count=1), [palette.ACCENTS[key]["accent"].lower()], key)
            self.assertEqual(_top_colors(menu_icon("settings"), count=1), ["#8b5cf6"], "mor dişli vurguyu izlemez")

    def test_device_context_menu_rows_have_colored_icons(self) -> None:
        from PyQt6.QtWidgets import QMenu

        from src.gui.icons import menu_icon

        window = self._window()
        window.resize(1000, 680)
        window.show()
        self.addCleanup(window.hide)
        window.device_list.add_device(_device())
        self.app.processEvents()
        item, _card = window.device_list.devices["192.168.18.99:38520"]
        seen = []

        def fake_exec(menu, *args, **kwargs):
            seen.append([(a.text(), a.icon()) for a in menu.actions() if not a.isSeparator()])

        with mock.patch.object(QMenu, "exec", fake_exec):
            lw = window.device_list.list_widget
            window.device_list._show_context_menu(lw.visualItemRect(item).center())
        self.assertEqual(len(seen), 1)
        rows = seen[0]
        self.assertEqual(len(rows), 4, [text for text, _ in rows])
        for (text, icon), name in zip(rows, ("send", "star", "copy", "trash")):
            self.assertTrue(_same_icon(icon, menu_icon(name)), (name, text))

    def test_history_context_actions_have_colored_icons(self) -> None:
        from PyQt6.QtWidgets import QWidget

        from src.gui.history_dialog import HistoryDialog
        from src.gui.icons import menu_icon

        class _Owner(QWidget):
            lang = "tr"

            def _existing_path(self, row):
                return "C:/yok.txt"

            def _open_row(self, row):
                pass

            def _reveal_row(self, row):
                pass

        owner = _Owner()
        self.addCleanup(owner.deleteLater)
        open_act, reveal_act = HistoryDialog.context_actions(owner, 0)
        self.assertTrue(_same_icon(open_act.icon(), menu_icon("open_with")))
        self.assertTrue(_same_icon(reveal_act.icon(), menu_icon("folder")))


# Aktarım kartının sağ tık menüsü: sıra, duruma göre açık/pasif satırlar, kartın düğmeleriyle aynı yollar
TRANSFER_MENU = ["Duraklat", "İptal", "", "Dosyayı Aç", "Klasörde Göster", "", "Tekrar Dene", "Listeden Kaldır"]


def _menu_rows(menu) -> list:
    return [("" if a.isSeparator() else a.text()) for a in menu.actions()]


def _enabled(menu) -> list:
    return [a.isEnabled() for a in menu.actions() if not a.isSeparator()]


class TransferCardMenuTest(_QtCase):
    def setUp(self) -> None:
        super().setUp()
        import tempfile

        from src.gui.transfer_item import TransferListWidget

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = os.path.join(tmp.name, "rapor.pdf")
        with open(self.file, "wb") as fh:
            fh.write(b"x" * 10)
        self.missing = os.path.join(tmp.name, "yok.pdf")
        self.list = TransferListWidget()
        self.list.lang = "tr"
        self.list.resize(640, 420)
        self.list.move(-6000, 0)
        self.list.show()
        self.addCleanup(self.list.deleteLater)
        self.addCleanup(self.list.hide)
        self.device = _device()
        self.list.retry_target = lambda transfer: self.device if self.device.is_online else None
        self._seq = 0
        # Gezgin / varsayılan uygulama asla açılmaz: aç / göster yardımcıları sahte, alt süreç başlatmak hata
        self.opened, self.revealed = [], []
        for name, sink in (("open_path", self.opened), ("reveal_path", self.revealed)):
            patcher = mock.patch(f"src.gui.history_dialog.{name}", side_effect=sink.append)
            patcher.start()
            self.addCleanup(patcher.stop)
        popen = mock.patch("subprocess.Popen", side_effect=AssertionError("Gezgin açılmamalı"))
        popen.start()
        self.addCleanup(popen.stop)

    def _add(self, status, path=None, direction=None, relative_path=None):
        from src.models.transfer import Transfer, TransferDirection

        self._seq += 1
        transfer = Transfer(f"t{self._seq}", path or self.file, "rapor.pdf", 10, "192.168.18.99", "HP",
                            direction or TransferDirection.SEND, relative_path=relative_path, device_port=38520)
        transfer.status = status
        self.list.add_transfer(transfer)
        self.list.transfers[transfer.transfer_id][1].update_timer.stop()
        return transfer.transfer_id

    def _menu(self, transfer_id):
        menu = self.list.context_menu(transfer_id)
        self.addCleanup(menu.deleteLater)
        return menu

    def _act(self, menu, text):
        return next(a for a in menu.actions() if a.text() == text)

    def test_order_labels_and_icons(self) -> None:
        from src.gui.icons import menu_icon
        from src.models.transfer import TransferStatus as S

        menu = self._menu(self._add(S.TRANSFERRING))
        self.assertEqual(_menu_rows(menu), TRANSFER_MENU)
        self.assertTrue(menu.toolTipsVisible())
        icons = [a.icon() for a in menu.actions() if not a.isSeparator()]
        for icon, name in zip(icons, ("pause", "exit", "file", "folder", "update", "trash")):
            self.assertTrue(_same_icon(icon, menu_icon(name)), name)
        paused = self._menu(self._add(S.PAUSED))
        self.assertEqual(_menu_rows(paused)[0], "Sürdür", "tek satır, etiket duruma göre")
        self.assertTrue(_same_icon(paused.actions()[0].icon(), menu_icon("play")))
        self.list.lang = "en"
        self.assertEqual(_menu_rows(self._menu(self._add(S.PAUSED))),
                         ["Resume", "Cancel", "", "Open File", "Show in Folder", "", "Retry", "Remove from List"])

    def test_entries_are_enabled_only_when_they_make_sense(self) -> None:
        from src.models.transfer import TransferStatus as S

        #                       Duraklat İptal  Aç     Göster Tekrar Kaldır
        cases = {S.PENDING:      [False, True, False, False, False, False],
                 S.CONNECTING:   [False, True, False, False, False, False],
                 S.TRANSFERRING: [True, True, False, False, False, False],
                 S.PAUSED:       [True, True, False, False, False, False],
                 S.COMPLETED:    [False, False, True, True, False, True],
                 S.FAILED:       [False, False, False, False, True, True],
                 S.CANCELLED:    [False, False, False, False, True, True]}
        for status, expected in cases.items():
            self.assertEqual(_enabled(self._menu(self._add(status))), expected, status)
        missing = self._menu(self._add(S.COMPLETED, path=self.missing))
        self.assertEqual(_enabled(missing), [False, False, False, False, False, True], "dosya yerinde değil")
        self.assertEqual(self._act(missing, "Klasörde Göster").toolTip(), "Dosya artık bu konumda değil")

    def test_retry_is_offered_only_for_a_send_that_can_go_again(self) -> None:
        from src.models.transfer import TransferDirection, TransferStatus as S

        def retry(transfer_id):
            action = self._act(self._menu(transfer_id), "Tekrar Dene")
            tip = action.toolTip()   # ipucu verilmemişse Qt yazının kendisini döndürür (menüde ipucu çıkmaz)
            return action.isEnabled(), "" if tip == action.text() else tip

        self.assertEqual(retry(self._add(S.FAILED)), (True, ""))
        self.assertEqual(retry(self._add(S.FAILED, direction=TransferDirection.RECEIVE)),
                         (False, "Bu dosyayı gönderen taraf yeniden gönderebilir"))
        self.assertEqual(retry(self._add(S.CANCELLED, relative_path="Tatil/rapor.pdf")),
                         (False, "Klasördeki dosya için klasörü yeniden gönderin"))
        self.assertEqual(retry(self._add(S.FAILED, path=self.missing)), (False, "Dosya artık bu konumda değil"))
        self.device.is_online = False
        self.assertEqual(retry(self._add(S.FAILED)), (False, "HP çevrimdışı"))

    def test_each_entry_uses_the_cards_existing_path(self) -> None:
        from src.models.transfer import TransferStatus as S

        seen = []
        for name in ("pause_transfer", "resume_transfer", "cancel_transfer", "retry_transfer"):
            getattr(self.list, name).connect(lambda tid, n=name: seen.append((n, tid)))
        running, paused = self._add(S.TRANSFERRING), self._add(S.PAUSED)
        self._act(self._menu(running), "Duraklat").trigger()
        self._act(self._menu(paused), "Sürdür").trigger()
        self._act(self._menu(running), "İptal").trigger()
        failed = self._add(S.FAILED)
        self._act(self._menu(failed), "Tekrar Dene").trigger()
        self.assertEqual(seen, [("pause_transfer", running), ("resume_transfer", paused),
                                ("cancel_transfer", running), ("retry_transfer", failed)])
        done = self._add(S.COMPLETED)
        self._act(self._menu(done), "Dosyayı Aç").trigger()
        self._act(self._menu(done), "Klasörde Göster").trigger()
        self.assertEqual((self.opened, self.revealed), ([self.file], [self.file]))
        self._act(self._menu(done), "Listeden Kaldır").trigger()
        self.assertNotIn(done, self.list.transfers)
        self._act(self._menu(running), "Listeden Kaldır").trigger()   # pasif: süren aktarım listeden düşmez
        self.assertIn(running, self.list.transfers)

    def test_right_click_on_a_card_opens_its_menu_without_moving_the_selection(self) -> None:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QContextMenuEvent
        from PyQt6.QtWidgets import QMenu

        from src.models.transfer import TransferStatus as S

        first, second = self._add(S.COMPLETED), self._add(S.TRANSFERRING)
        self.app.processEvents()
        lw = self.list.list_widget
        lw.setCurrentItem(self.list.transfers[second][0])
        item, card = self.list.transfers[first]
        opened = []

        def fake_exec(menu, *args, **kwargs):
            opened.append((_enabled(menu), args[0] if args else None))

        where = card.mapToGlobal(QPoint(30, 20))
        with mock.patch.object(QMenu, "exec", fake_exec):
            QApplication.sendEvent(card, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(30, 20), where))
            lw.customContextMenuRequested.emit(QPoint(2, lw.viewport().height() - 2))  # kartsız boşluk: menü yok
        self.assertEqual(opened, [([False, False, True, True, False, True], where)])
        self.assertIs(lw.currentItem(), self.list.transfers[second][0], "sağ tık seçimi değiştirmez")

    def test_disabled_rows_are_greyed_text_and_icon(self) -> None:
        from src.models.transfer import TransferStatus as S

        with open(os.path.join(ROOT, "assets", "styles", "dark.qss"), encoding="utf-8") as fh:
            qss = fh.read()
        menu = self._menu(self._add(S.TRANSFERRING))
        menu.setStyleSheet(qss)
        menu.ensurePolished()
        menu.adjustSize()
        image = menu.grab().toImage()
        ratio = image.devicePixelRatio()

        def colors(action, x0, x1):
            geo = menu.actionGeometry(action)
            return {image.pixelColor(x, y).name()
                    for y in range(int(geo.top() * ratio), int(geo.bottom() * ratio))
                    for x in range(int((geo.left() + x0) * ratio), int(min(geo.left() + x1, geo.right()) * ratio))}

        def saturated(name):
            r, g, b = _rgb(name)
            return max(r, g, b) - min(r, g, b) > 40

        background = image.pixelColor(2, int(menu.actionGeometry(menu.actions()[0]).center().y() * ratio)).name()
        trash, open_file = self._act(menu, "Listeden Kaldır"), self._act(menu, "Dosyayı Aç")
        self.assertTrue(any(saturated(c) for c in colors(self._act(menu, "İptal"), 0, 34)), "açık satırın simgesi renkli")
        self.assertFalse([c for c in colors(trash, 0, 34) | colors(open_file, 0, 34) if saturated(c)],
                         "pasif satırın simgesi gri")
        self.assertIn("#666666", colors(open_file, 38, 10_000), "pasif yazı soluk")
        self.assertNotIn("#e8e8e8", colors(open_file, 38, 10_000) - {background})
        self.assertIn("#e8e8e8", colors(self._act(menu, "İptal"), 38, 10_000), "açık satırın yazısı normal")

    def test_main_window_retry_sends_the_same_file_to_the_same_device(self) -> None:
        from src.models.transfer import Transfer, TransferDirection, TransferStatus as S

        window = self._window()
        window.device_list.add_device(_device())
        transfer = Transfer("r1", self.file, "rapor.pdf", 10, "192.168.18.99", "HP", TransferDirection.SEND,
                            device_port=38520)
        transfer.status = S.FAILED
        window.add_transfer(transfer)
        window.transfer_list.transfers["r1"][1].update_timer.stop()
        sent = []
        window.send_files_requested.connect(lambda files, device, folder: sent.append((files, device.ip, folder)))
        menu = window.transfer_list.context_menu("r1")
        self.addCleanup(menu.deleteLater)
        self.assertTrue(self._act(menu, "Tekrar Dene").isEnabled())
        self._act(menu, "Tekrar Dene").trigger()
        self.assertEqual(sent, [([self.file], "192.168.18.99", "")])
        self.assertNotIn("r1", window.transfer_list.transfers, "eski kartın yerini yeni gönderim alır")

        offline = Transfer("r2", self.file, "rapor.pdf", 10, "192.168.18.50", "Yok", TransferDirection.SEND,
                           device_port=38520)
        offline.status = S.CANCELLED
        window.add_transfer(offline)
        window.transfer_list.transfers["r2"][1].update_timer.stop()
        boxes = []
        MessageBox.set_test_hook(lambda box: boxes.append(box.text()))
        window._retry_transfer("r2")                     # menü açıkken cihaz düştüyse: gönderim yok, nedeni kutuda
        self.assertEqual(len(sent), 1)
        self.assertEqual(boxes, ["Yok çevrimdışı"])
        self.assertIn("r2", window.transfer_list.transfers)


# ---------------------------------------------------------------------------------------------------------------
# Dört uygulamada aynı görünüm (23 Kasım 2026): düğme köşeleri (normal/vurgulu 10 px, küçük/araç 6 px), 36 px
# açılır liste ve aynı satırdaki alanlar, aynı chevron oku (soluk yazı renginde, düz ok alanı), MediaCompressor
# ölçüsünde kaydırma çubuğu, ortak yazı boyları (gövde 10 pt, pencere başlığı 9.5 pt/600, bölüm başlığı 12 pt/700,
# ipucu 9 pt, düğme 10 pt/600, küçük düğme 9 pt/600).
# ---------------------------------------------------------------------------------------------------------------
def _flat_qss(qss: str) -> str:
    return " ".join(re.sub(r"/\*.*?\*/", " ", qss, flags=re.S).split())


def _strict_rule(qss: str, selector: str) -> str:
    """Seçici kuralın başında durmalı (ör. "QPushButton" araması "QMessageBox QPushButton"a takılmasın)."""
    match = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", _flat_qss(qss))
    assert match, selector
    return match.group(1).strip()


class SharedLookTest(_QtCase):
    def _sheets(self, accent="violet"):
        from src.gui import palette

        self.addCleanup(palette.set_accent_override, None)
        window = self._window()
        for theme in ("dark", "light"):
            window.apply_theme(theme, accent)
            yield theme, window.styleSheet(), palette.ACCENTS[accent]["accent"]

    def test_button_corners_normal_and_primary_10_small_6(self) -> None:
        for theme, qss, _accent in self._sheets():
            flat = _flat_qss(qss)
            for selector in ("QPushButton", "QWidget#settingsDialog QPushButton#settingsFooterBtn",
                             "QPushButton#dialogCompactBtn"):
                self.assertIn("border-radius: 10px;", _strict_rule(qss, selector), (theme, selector))
            self.assertRegex(flat, r"QPushButton#manualSecondaryButton \{[^}]*border-radius: 10px;")
            for selector in ('QPushButton[class="menu-button"]', 'QPushButton[class="title-button"]',
                             'QPushButton[class="title-button-close"]', "QPushButton#clearListBtn",
                             "QPushButton#cancelAllBtn", "QPushButton#transferActionBtn, QPushButton#transferCancelBtn",
                             "QPushButton#favoriteBtn"):
                self.assertIn("border-radius: 6px;", _strict_rule(qss, selector), (theme, selector))
            self.assertNotRegex(flat, r"QPushButton[^{]*\{[^}]*border-radius: 14px", "eski 14 px koyu tema düğmesi")
        self.assertIn("border-radius: 6px;", _strict_rule(qss, "QToolButton"), "açık tema araç düğmesi")

    def test_combo_rows_and_manual_fields_are_36_px(self) -> None:
        from PyQt6.QtWidgets import QComboBox, QLineEdit, QWidget

        from src.gui.manual_device_dialog import ManualDeviceDialog
        from src.gui.settings import SettingsDialog
        from src.gui.widgets.stepper_spinbox import StepperSpinBox
        from src.utils.config import get_config

        window = self._window()
        config = get_config()
        config.set("ui", "language", "tr")
        for theme in ("dark", "light"):
            config.set("ui", "theme", theme)
            window.apply_theme(theme, "cyan")
            dialog = SettingsDialog(window)
            self.addCleanup(dialog.deleteLater)
            dialog.prepare_content()
            dialog.show()
            seen = 0
            for index in range(len(dialog.nav_buttons)):
                dialog._switch_tab(index)
                self.app.processEvents()
                for w in dialog.stack.widget(index).findChildren(QWidget):
                    field = isinstance(w, (QComboBox, StepperSpinBox)) or (
                        isinstance(w, QLineEdit) and w.objectName() == "settingsLineEdit")
                    if field and w.isVisible():
                        seen += 1
                        self.assertEqual(w.height(), 36, (theme, index, type(w).__name__, w.objectName()))
            self.assertGreaterEqual(seen, 5)
            dialog.close()
            manual = ManualDeviceDialog(None, "tr")
            self.addCleanup(manual.deleteLater)
            manual.show()
            self.app.processEvents()
            heights = {w.height() for w in manual.findChildren(QWidget) if w.objectName() == "manualField"}
            self.assertEqual(heights, {36}, theme)
            manual.close()

    def test_combo_arrow_is_the_shared_chevron(self) -> None:
        from PyQt6.QtGui import QColor, QImage

        from src.gui.icons import chevron_png

        for theme, qss, _accent in self._sheets():
            muted = "#9e9e9e" if theme == "dark" else "#616161"
            self.assertNotIn("__COMBO_CHEVRON__", qss)
            drop = _strict_rule(qss, "QComboBox::drop-down")
            for decl in ("subcontrol-origin: padding;", "subcontrol-position: center right;", "width: 28px;",
                         "border: none;", "background: transparent;"):
                self.assertIn(decl, drop, theme)
            arrow = _strict_rule(qss, "QComboBox::down-arrow")
            self.assertIn(f"transfertcp_chev_{muted.lstrip('#')}_x4.png", arrow)
            self.assertIn("width: 12px; height: 12px;", arrow)
            self.assertNotRegex(_flat_qss(qss), r"QComboBox::(down-arrow|drop-down):(hover|on|disabled|pressed)",
                                "ok alanı üzerine gelince/açıkken/pasifken değişmez (açık temadaki gri kutu kalktı)")
            img = QImage(chevron_png(muted))
            s = 4
            self.assertEqual((img.width(), img.height()), (12 * s, 12 * s))
            self.assertEqual(img.pixelColor(6 * s, 8 * s - 1).name(), QColor(muted).name(), "uç")
            self.assertGreater(img.pixelColor(round(4.25 * s), round(6.25 * s)).alpha(), 200, "sol kol")
            self.assertEqual(img.pixelColor(6 * s, round(5.5 * s)).alpha(), 0, "içi boş")
            self.assertEqual(img.pixelColor(2, 2).alpha(), 0)

    def test_scrollbar_is_the_shared_spec(self) -> None:
        for theme, qss, accent in self._sheets():
            track, handle = ("#1f1f1f", "#575757") if theme == "dark" else ("#d8d8d8", "#a3a3a3")
            for axis, size, minimum in (("vertical", "width", "min-height"), ("horizontal", "height", "min-width")):
                bar = _strict_rule(qss, f"QScrollBar:{axis}")
                for decl in (f"background: {track};", f"{size}: 10px;", "margin: 2px;", "border-radius: 5px;"):
                    self.assertIn(decl, bar, (theme, axis))
                grip = _strict_rule(qss, f"QScrollBar::handle:{axis}")
                for decl in (f"background: {handle};", "border-radius: 5px;", f"{minimum}: 28px;"):
                    self.assertIn(decl, grip, (theme, axis))
                hover = _strict_rule(qss, f"QScrollBar::handle:{axis}:hover, QScrollBar::handle:{axis}:pressed")
                self.assertIn(f"background: {accent};", hover, "vurgu rengini izler")

    def test_font_roles(self) -> None:
        for theme, qss, _accent in self._sheets():
            self.assertEqual(self.app.font().pointSizeF(), 10, "gövde 10 pt (uygulama yazı tipi)")
            header = _strict_rule(qss, "QGroupBox::title")
            self.assertIn("font-size: 12pt;", header, theme)
            self.assertIn("font-weight: 700;", header, theme)
            for selector in ("QLabel#settingsHint", "QLabel#manualDialogHint"):
                self.assertIn("font-size: 9pt;", _strict_rule(qss, selector), (theme, selector))
            for selector in ("QPushButton", "QWidget#settingsDialog QPushButton#settingsFooterBtn",
                             "QPushButton#dialogCompactBtn"):
                rule = _strict_rule(qss, selector)
                self.assertIn("font-size: 10pt;", rule, (theme, selector))
                self.assertIn("font-weight: 600;", rule, (theme, selector))
            for selector in ('QPushButton[class="menu-button"]', "QPushButton#clearListBtn", "QPushButton#cancelAllBtn"):
                rule = _strict_rule(qss, selector)
                self.assertIn("font-size: 9pt;", rule, (theme, selector))
                self.assertIn("font-weight: 600;", rule, (theme, selector))
        from PyQt6.QtWidgets import QLabel

        titles = [lab for lab in self._window().findChildren(QLabel) if lab.text() == "TransferTCP"]
        self.assertEqual(len(titles), 1)
        self.assertIn("font-size: 9.5pt;", titles[0].styleSheet(), "pencere başlığı")
        self.assertIn("font-weight: 600;", titles[0].styleSheet())


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
