"""Arayüz geri bildirimi ve cilası: pencere içi bildirim (durum çubuğu yerine), kısayollar, tepsiden geri getirme,
menü sonrası takılı hover, görev çubuğu ilerlemesi, "Geri Al", "Kopyalandı", duyuru satırı geçişi, pencere konumunun
hatırlanması, hız/kalan süre yazısı, biten kartın beklemesi ve yenilemede listenin korunması."""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QCursor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from src.models.device import Device  # noqa: E402
from src.models.transfer import Transfer, TransferDirection  # noqa: E402


def _device(ip="192.168.1.24", name="Ofis-PC", online=True) -> Device:
    device = Device(ip, 38520, name, name)
    device.is_online = online
    return device


def _transfer(tid="t1", size=1000, direction=TransferDirection.SEND) -> Transfer:
    return Transfer(tid, f"C:/x/{tid}.bin", f"{tid}.bin", size, "192.168.1.24", "Ofis-PC", direction)


def _enter(widget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    QApplication.sendEvent(widget, QEvent(QEvent.Type.Enter))


def _close_popup_soon(app) -> None:
    def close():
        popup = app.activePopupWidget()
        if popup is not None:
            popup.close()
        else:
            QTimer.singleShot(20, close)

    QTimer.singleShot(50, close)


class _QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = support.qt_app()

    def _window(self):
        from src.gui.main_window import MainWindow

        win = MainWindow()
        self.addCleanup(win.deleteLater)
        self.addCleanup(lambda: QApplication.instance().removeEventFilter(win))
        return win

    def _clear_saved_geometry(self):
        from src.utils.config import get_config

        get_config().set("ui", "window_geometry", None)
        get_config().set("ui", "splitter_left", None)


class StatusToastTest(_QtCase):
    def test_status_messages_appear_in_the_window_with_tone_from_the_glyph(self) -> None:
        win = self._window()
        win.resize(1000, 680)
        win.show()
        self.addCleanup(win.hide)
        win.show_status_message("✓ Ayarlar kaydedildi", 2000)
        self.assertTrue(win.toast.is_showing())
        self.assertTrue(win.toast.isVisible())
        self.assertEqual(win.toast.text(), "Ayarlar kaydedildi", "baştaki ✓ simge olarak çizilir, yazıda tekrarlanmaz")
        self.assertEqual(win.toast.tone(), "ok")
        self.assertTrue(win.statusBar().isHidden(), "durum çubuğu gizli kalır")
        # yeni ileti eskisinin yerine geçer (kuyruk yok)
        win.show_status_message("✕ a.bin aktarılamadı")
        self.assertEqual((win.toast.text(), win.toast.tone()), ("a.bin aktarılamadı", "err"))
        # içeriğin alt-ortasında, pencerenin içinde
        geo = win.toast.geometry()
        host = win.main_container.rect()
        self.assertTrue(host.contains(geo), (geo, host))
        self.assertLess(abs(geo.center().x() - host.center().x()), 3)
        self.assertGreater(geo.top(), host.height() // 2)

    def test_toast_expires_and_respects_disabled_animations(self) -> None:
        win = self._window()
        win.show()
        self.addCleanup(win.hide)
        with mock.patch("src.gui.widgets.inline_toast._system_animations_enabled", return_value=False):
            win.show_status_message("bilgi", 1200)
            self.assertTrue(win.toast.is_showing())
            win.toast.dismiss()
            self.assertTrue(win.toast.isHidden(), "animasyon kapalıyken hemen kaybolur")

    def test_toast_fades_out_with_animations(self) -> None:
        win = self._window()
        win.show()
        self.addCleanup(win.hide)
        with mock.patch("src.gui.widgets.inline_toast._system_animations_enabled", return_value=True):
            win.show_status_message("bilgi", 1200)
            win.toast.dismiss()
            self.assertFalse(win.toast.isHidden(), "sönme sürerken hâlâ çizilir")
            QTest.qWait(400)
            self.assertTrue(win.toast.isHidden())

    def test_long_text_is_elided_with_full_text_in_tooltip(self) -> None:
        win = self._window()
        win.resize(900, 600)
        win.show()
        self.addCleanup(win.hide)
        long_text = "Çok uzun bir ileti " * 20
        win.show_status_message(long_text)
        self.assertLessEqual(win.toast.width(), win.main_container.width())
        self.assertEqual(win.toast.toolTip(), long_text.strip())

    def test_toast_follows_the_theme(self) -> None:
        win = self._window()
        win.apply_theme("dark")
        dark_sheet = win.toast.styleSheet()
        win.apply_theme("light")
        self.assertNotEqual(win.toast.styleSheet(), dark_sheet)


class ShortcutTest(_QtCase):
    def test_send_and_quit_shortcuts_live_on_the_window(self) -> None:
        win = self._window()
        self.assertIn(win.send_action, win.actions(), "Ctrl+O yalnızca açılmamış menüde kalmamalı")
        self.assertIn(win.exit_action, win.actions(), "Ctrl+Q yalnızca açılmamış menüde kalmamalı")
        self.assertEqual(win.exit_action.shortcut().toString(), "Ctrl+Q")
        self.assertEqual(win.send_action.shortcut().toString(), "Ctrl+O")

    def test_ctrl_q_reaches_quit(self) -> None:
        win = self._window()
        win.show()
        self.addCleanup(win.hide)
        win.activateWindow()
        QApplication.processEvents()
        if not win.isActiveWindow():
            self.skipTest("bu platformda pencere etkinleştirilemiyor")
        with mock.patch.object(QApplication, "quit") as quit_:
            QTest.keyClick(win, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
        quit_.assert_called_once()


class TrayRestoreTest(_QtCase):
    def test_restore_keeps_a_maximized_window_maximized(self) -> None:
        win = self._window()
        self.addCleanup(self._clear_saved_geometry)
        win.showMaximized()
        QApplication.processEvents()
        win.hide()  # tepsiye
        win.restore_from_tray()
        QApplication.processEvents()
        self.assertTrue(win.windowState() & Qt.WindowState.WindowMaximized, "showNormal ekranı kaplamayı bozuyordu")
        win.hide()

    def test_restore_from_minimized_returns_to_previous_state(self) -> None:
        win = self._window()
        self.addCleanup(self._clear_saved_geometry)
        win.show()
        win.setWindowState(Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized)
        win.restore_from_tray()
        state = win.windowState()
        self.assertFalse(state & Qt.WindowState.WindowMinimized)
        self.assertTrue(state & Qt.WindowState.WindowMaximized)
        win.hide()

    def test_app_show_window_uses_restore_from_tray(self) -> None:
        import types
        from src.app import Application

        window = mock.Mock()
        Application._show_window(types.SimpleNamespace(window=window, logger=mock.Mock()))
        window.restore_from_tray.assert_called_once()
        window.showNormal.assert_not_called()


class HoverSettleTest(_QtCase):
    def test_helper_clears_stale_hover_only_when_the_cursor_left(self) -> None:
        from src.gui.widgets.hover_fix import settle_hover

        btn = QPushButton("x")
        btn.resize(40, 30)
        btn.show()
        self.addCleanup(btn.deleteLater)
        QApplication.processEvents()
        _enter(btn)
        QCursor.setPos(btn.mapToGlobal(QPoint(5000, 5000)))
        settle_hover(btn)
        self.assertFalse(btn.underMouse())
        settle_hover(None)  # sessizce geçer

    def test_title_bar_menu_buttons_do_not_stay_hovered(self) -> None:
        win = self._window()
        win.resize(1000, 680)
        win.show()
        self.addCleanup(win.hide)
        QApplication.processEvents()
        for button in (win.file_btn, win.theme_btn, win.lang_btn, win.color_btn):
            _enter(button)
            QCursor.setPos(win.mapToGlobal(QPoint(500, 500)))  # menü dışında boş bir yer
            _close_popup_soon(self.app)
            button.showMenu()  # Qt 6: menü açılır ve hemen döner; popup kapanana dek bekle
            QTest.qWait(250)
            self.assertIsNone(self.app.activePopupWidget())
            self.assertFalse(button.underMouse(), f"{button.text()} menü kapandıktan sonra hover'da kaldı")

    def test_device_context_menu_settles_the_card(self) -> None:
        win = self._window()
        win.resize(1000, 680)
        win.show()
        self.addCleanup(win.hide)
        device = _device()
        win.device_list.add_device(device)
        QApplication.processEvents()
        item, card = win.device_list.devices["192.168.1.24:38520"]
        _enter(card)
        QCursor.setPos(win.mapToGlobal(QPoint(700, 500)))
        _close_popup_soon(self.app)
        lw = win.device_list.list_widget
        win.device_list._show_context_menu(lw.visualItemRect(item).center())
        self.assertFalse(card.underMouse())


class TaskbarProgressTest(_QtCase):
    class _Backend:
        def __init__(self):
            self.calls = []

        def set_state(self, hwnd, flag):
            self.calls.append(("state", flag))

        def set_value(self, hwnd, done, total):
            self.calls.append(("value", done, total))

    def test_progress_is_deduplicated_and_cleared(self) -> None:
        from src.gui.widgets import taskbar_progress as tp

        backend = self._Backend()
        bar = tp.TaskbarProgress(lambda: 1234, backend=backend)
        bar.update(0.5)
        bar.update(0.5)
        self.assertEqual(backend.calls, [("state", tp.TBPF_NORMAL), ("value", 500, 1000)], "aynı değer yeniden gitmez")
        bar.update(0.5, paused=True)
        self.assertEqual(bar.state(), (tp.TBPF_PAUSED, 500))
        bar.clear()
        self.assertEqual(backend.calls[-1], ("state", tp.TBPF_NOPROGRESS))
        bar.forget()
        bar.clear()
        self.assertEqual(backend.calls[-1], ("state", tp.TBPF_NOPROGRESS), "gösterimden sonra yeniden gönderilir")

    def test_no_window_handle_sends_nothing(self) -> None:
        from src.gui.widgets.taskbar_progress import TaskbarProgress

        backend = self._Backend()
        TaskbarProgress(lambda: 0, backend=backend).update(0.3)
        self.assertEqual(backend.calls, [])

    def test_window_aggregates_the_batch_and_keeps_finished_files(self) -> None:
        from src.gui.widgets import taskbar_progress as tp

        win = self._window()
        backend = self._Backend()
        win.taskbar = tp.TaskbarProgress(lambda: 99, backend=backend)
        a, b = _transfer("a", 1000), _transfer("b", 3000)
        for tr in (a, b):
            tr.start()
        a.bytes_transferred, b.bytes_transferred = 500, 1500
        win.refresh_taskbar_progress([a, b])
        self.assertEqual(win.taskbar.state(), (tp.TBPF_NORMAL, 500))
        a.complete()
        win.refresh_taskbar_progress([b])  # biten dosya toplamdan düşmez: çubuk geri gitmez
        self.assertEqual(win.taskbar.state(), (tp.TBPF_NORMAL, 625))
        b.pause()
        win.refresh_taskbar_progress([b])
        self.assertEqual(win.taskbar.state()[0], tp.TBPF_PAUSED)
        win.refresh_taskbar_progress([])
        self.assertEqual(win.taskbar.state(), (tp.TBPF_NOPROGRESS, 0))

    def test_alert_only_when_window_is_visible_but_not_active(self) -> None:
        win = self._window()
        with mock.patch.object(QApplication, "alert") as alert:
            win.notify_transfers_finished()  # gizli (tepside): yanıp sönecek düğme yok
            alert.assert_not_called()
            win.show()
            self.addCleanup(win.hide)
            with mock.patch.object(win, "isActiveWindow", return_value=False):
                win.notify_transfers_finished()
            alert.assert_called_once_with(win, 0)
            with mock.patch.object(win, "isActiveWindow", return_value=True):
                win.notify_transfers_finished()
            alert.assert_called_once()

    def test_app_alerts_when_the_last_transfer_finishes(self) -> None:
        import types
        from src.app import Application

        done = _transfer("z")
        done.start()
        done.complete()
        fake = types.SimpleNamespace(
            _handled_completion_ids=set(), _pending_update=None, logger=mock.Mock(),
            config=mock.Mock(get=lambda section, key, default=None: default), window=mock.Mock(),
            database=mock.Mock(), tray_icon=mock.Mock(),
            transfer_manager=mock.Mock(get_active_transfers=mock.Mock(return_value=[]),
                                       get_statistics=mock.Mock(return_value={"total_sent": 0, "total_received": 0})),
            _find_folder_transfer_info=mock.Mock(return_value=(False, None, None)),
        )
        with mock.patch("src.app.get_active_language", return_value="tr"), mock.patch("src.app.SystemToast"):
            Application._handle_transfer_complete_gui(fake, done)
        fake.window.notify_transfers_finished.assert_called_once()
        fake.window.refresh_taskbar_progress.assert_called_with([])


class DeviceUndoAndCopyTest(_QtCase):
    def test_removing_a_device_offers_undo_that_restores_it_and_its_selection(self) -> None:
        win = self._window()
        win.show()
        self.addCleanup(win.hide)
        device = _device()
        other = _device("192.168.1.37", "Pixel 8")
        win.device_list.add_device(device)
        win.device_list.add_device(other)
        win.device_list.select_device(device)
        removed, restored = [], []
        win.device_remove_requested.connect(removed.append)
        win.device_restore_requested.connect(restored.append)
        win.device_list._request_remove(device)
        self.assertEqual(removed, [device])
        self.assertNotIn("192.168.1.24:38520", win.device_list.devices)
        self.assertIn("Ofis-PC", win.toast.text())
        self.assertEqual(win.toast.action_text(), "Geri Al")
        win.toast._button.click()
        self.assertEqual(restored, [device])
        self.assertIn("192.168.1.24:38520", win.device_list.devices)
        self.assertIs(win.device_list.get_selected_device(), device, "seçili cihaz geri gelince yine seçili")

    def test_discovery_restore_lifts_the_block(self) -> None:
        from src.core.discovery import NetworkDiscovery

        discovery = NetworkDiscovery()
        device = _device()
        discovery.devices["192.168.1.24:38520"] = device
        discovery.forget_device(device.ip, device.port)
        self.assertIn("192.168.1.24:38520", discovery._blocked)
        discovery.restore_device(device)
        self.assertNotIn("192.168.1.24:38520", discovery._blocked)
        self.assertIs(discovery.get_device(device.ip, device.port), device)

    def test_copy_ip_shows_copied_feedback(self) -> None:
        win = self._window()
        win.show()
        self.addCleanup(win.hide)
        win.device_list._copy_ip_to_clipboard("192.168.1.24")
        self.assertEqual(QApplication.clipboard().text(), "192.168.1.24")
        self.assertEqual(win.toast.text(), "IP adresi kopyalandı: 192.168.1.24")
        self.assertEqual(win.toast.tone(), "ok")

    def test_message_box_copy_shows_copied_tip(self) -> None:
        from src.gui import message_box

        with mock.patch.object(message_box.QToolTip, "showText") as tip:
            message_box.flash_copied(QWidget())
        self.assertIn(tip.call_args.args[1], ("Kopyalandı", "Copied"))


class NoticeBarAnimationTest(_QtCase):
    def _bar(self):
        from src.gui.notice_bar import NoticeBar

        host = QWidget()
        self.addCleanup(host.deleteLater)
        QVBoxLayout(host).addWidget(bar := NoticeBar())
        host.resize(600, 200)
        host.show()
        return bar

    def test_slides_in_and_out(self) -> None:
        from src.utils import remote_notice as rn

        bar = self._bar()
        with mock.patch("src.gui.notice_bar._system_animations_enabled", return_value=True):
            bar.show_notice(rn.Notice("n1", "Merhaba", ""))
            self.assertTrue(bar.isVisible())
            self.assertLess(bar.maximumHeight(), 40, "yükseklik sıfırdan açılır (birden itmez)")
            QTest.qWait(350)
            self.assertEqual(bar.maximumHeight(), 16777215, "geçiş bitince sınır kalkar")
            self.assertGreater(bar.height(), 10)
            bar.dismiss()
            self.assertTrue(bar.isVisible(), "kapanırken bir an daha görünür")
            self.assertTrue(bar.is_closing())
            QTest.qWait(350)
            self.assertFalse(bar.isVisible())
            self.assertEqual(bar.maximumHeight(), 16777215)

    def test_reopening_during_close_cancels_the_close(self) -> None:
        from src.utils import remote_notice as rn

        bar = self._bar()
        with mock.patch("src.gui.notice_bar._system_animations_enabled", return_value=True):
            bar.show_notice(rn.Notice("n1", "a", ""))
            QTest.qWait(300)
            bar.dismiss()
            bar.show_notice(rn.Notice("n2", "b", ""))
            QTest.qWait(350)
            self.assertTrue(bar.isVisible())


class GeometryMemoryTest(_QtCase):
    def test_clamp_keeps_on_screen_rects_and_rescues_lost_ones(self) -> None:
        from src.gui.main_window import clamp_to_screens

        primary = QRect(0, 0, 1920, 1040)
        second = QRect(1920, 0, 1280, 984)
        inside = QRect(100, 80, 1000, 680)
        self.assertEqual(clamp_to_screens(inside, [primary, second]), inside)
        on_second = QRect(2000, 100, 1000, 680)
        self.assertEqual(clamp_to_screens(on_second, [primary, second]), on_second)
        lost = QRect(5000, 100, 1000, 680)  # ikinci ekran çıkarıldı
        self.assertEqual(clamp_to_screens(lost, [primary]), QRect(460, 180, 1000, 680))
        above = QRect(200, -300, 1000, 680)  # başlık çubuğu ekranın üstünde
        self.assertEqual(clamp_to_screens(above, [primary]).top(), 0)
        huge = QRect(0, 0, 4000, 3000)
        self.assertEqual(clamp_to_screens(huge, [primary]).size(), primary.size())
        straddle = QRect(1500, 100, 1000, 680)  # iki ekran arasında: çoğunun olduğu ekranda kalır
        self.assertTrue(primary.contains(clamp_to_screens(straddle, [primary, second])) or
                        second.contains(clamp_to_screens(straddle, [primary, second])))

    def test_size_position_maximized_and_splitter_survive_a_restart(self) -> None:
        from src.utils.config import get_config

        self.addCleanup(self._clear_saved_geometry)
        # offscreen ekranı (800x600) pencerenin en küçük boyutundan dar: sığdırma ayrı test edilir, burada devre dışı
        patcher = mock.patch("src.gui.main_window.clamp_to_screens", side_effect=lambda rect, screens: QRect(rect))
        patcher.start()
        self.addCleanup(patcher.stop)
        win = self._window()
        win.enable_geometry_memory()
        target = QRect(40, 30, 950, 640)
        win.setGeometry(target)
        win.show()
        QApplication.processEvents()
        win.splitter.setSizes([320, win.splitter.width() - 320])
        left = win.splitter.sizes()[0]  # tutamaç genişliği nedeniyle 320'den birkaç px sapabilir
        self.assertLess(abs(left - 320), 6)
        win.hide()  # tepsiye gizleme kaydeder
        saved = get_config().get("ui", "window_geometry")
        self.assertEqual((saved["w"], saved["h"], saved["maximized"]), (target.width(), target.height(), False))
        self.assertEqual(get_config().get("ui", "splitter_left"), left)

        again = self._window()
        again.enable_geometry_memory()
        self.assertEqual(again.geometry(), target)
        again.show()
        QApplication.processEvents()
        self.assertLess(abs(again.splitter.sizes()[0] - left), 6)
        again.showMaximized()
        QApplication.processEvents()
        again.hide()
        self.assertTrue(get_config().get("ui", "window_geometry")["maximized"])
        third = self._window()
        third.enable_geometry_memory()
        self.assertTrue(third.windowState() & Qt.WindowState.WindowMaximized)

    def test_windows_without_memory_neither_read_nor_write_the_settings(self) -> None:
        from src.utils.config import get_config

        self.addCleanup(self._clear_saved_geometry)
        get_config().set("ui", "window_geometry", {"x": 5, "y": 5, "w": 950, "h": 650, "maximized": True})
        win = self._window()  # testler / ekran görüntüsü araçları: kayıt uygulanmaz
        self.assertFalse(win.windowState() & Qt.WindowState.WindowMaximized)
        win.show()
        win.hide()
        self.assertEqual(get_config().get("ui", "window_geometry")["w"], 950, "kayıt değişmez")

    def test_garbage_saved_geometry_is_ignored(self) -> None:
        from src.utils.config import get_config

        self.addCleanup(self._clear_saved_geometry)
        get_config().set("ui", "window_geometry", {"x": "a"})
        win = self._window()
        win.enable_geometry_memory()
        self.assertEqual(win.size().width(), 1000)


class SpeedEtaTextTest(unittest.TestCase):
    def test_speed_has_three_significant_digits(self) -> None:
        from src.utils.helpers import format_speed

        mb = 1024 * 1024
        self.assertEqual(format_speed(0), "0 B/s")
        self.assertEqual(format_speed(512), "512 B/s")
        self.assertEqual(format_speed(45.64 * 1024), "45.6 KB/s")
        self.assertEqual(format_speed(1.234 * mb), "1.23 MB/s")
        self.assertEqual(format_speed(12.34 * mb), "12.3 MB/s")
        self.assertEqual(format_speed(118.4 * mb), "118 MB/s")
        self.assertEqual(format_speed(999.7 * 1024), "0.98 MB/s", "\"1000 KB/s\" yazılmaz")

    def test_eta_is_rounded_to_sensible_units(self) -> None:
        from src.utils.helpers import format_eta

        self.assertEqual(format_eta(3.4, "tr"), "3 sn")
        self.assertEqual(format_eta(44, "tr"), "45 sn")
        self.assertEqual(format_eta(95, "tr"), "~2 dk")
        self.assertEqual(format_eta(1800, "tr"), "~30 dk")
        self.assertEqual(format_eta(3600, "tr"), "~1 sa")
        self.assertEqual(format_eta(4800, "tr"), "~1 sa 20 dk")
        self.assertEqual(format_eta(95, "en"), "~2 min")
        self.assertEqual(format_eta(4800, "en"), "~1 h 20 min")

    def test_card_speed_text_refreshes_twice_a_second_with_smoothing(self) -> None:
        support.qt_app()
        from src.gui.transfer_item import TransferItemWidget

        transfer = _transfer("s", 100 * 1024 * 1024)
        transfer.start()
        transfer.bytes_transferred = 10 * 1024 * 1024
        transfer.speed = 10 * 1024 * 1024
        card = TransferItemWidget(transfer)
        card.update_timer.stop()
        self.addCleanup(card.deleteLater)
        first = card._speed_eta_text("tr", now=100.0)
        self.assertTrue(first.startswith("10.0 MB/s"), first)
        self.assertIn("kaldı", first)
        transfer.speed = 30 * 1024 * 1024
        self.assertEqual(card._speed_eta_text("tr", now=100.2), first, "0.5 sn dolmadan yazı değişmez")
        second = card._speed_eta_text("tr", now=100.6)
        self.assertTrue(second.startswith("20.0 MB/s"), f"yumuşatılmış (10 ile 30 arası): {second}")


class FinishedCardDelayTest(unittest.TestCase):
    def test_finished_card_stays_in_place_briefly_then_sinks(self) -> None:
        support.qt_app()
        from src.gui.transfer_item import TransferListWidget

        widget = TransferListWidget()
        widget.REGROUP_DELAY_MS = 150
        self.addCleanup(widget.deleteLater)
        transfers = [_transfer(f"t{i}") for i in range(2)]
        for transfer in transfers:
            widget.add_transfer(transfer)
            self.addCleanup(widget.transfers[transfer.transfer_id][1].update_timer.stop)

        def order():
            lw = widget.list_widget
            return [lw.itemWidget(lw.item(r)).transfer.transfer_id for r in range(lw.count())]

        self.assertEqual(order(), ["t1", "t0"])
        transfers[1].start()
        transfers[1].complete()
        widget.update_transfer(transfers[1])
        self.assertEqual(order(), ["t1", "t0"], "biten kart hemen yer değiştirmez")
        QTest.qWait(300)
        self.assertEqual(order(), ["t0", "t1"], "bekleme bitince bitenlerin arasına iner")


class RefreshKeepsListTest(_QtCase):
    def test_refresh_keeps_devices_and_selection(self) -> None:
        win = self._window()
        a, b = _device(), _device("192.168.1.37", "Pixel 8")
        win.device_list.add_device(a)
        win.device_list.add_device(b)
        win.device_list.select_device(b)
        emitted = []
        win.refresh_devices_requested.connect(lambda: emitted.append(True))
        win.device_list.refresh_btn.click()
        self.assertEqual(emitted, [True])
        self.assertEqual(len(win.device_list.devices), 2, "liste boşaltılmaz")
        self.assertIs(win.device_list.get_selected_device(), b)
        self.assertTrue(win.device_list.empty_box.isHidden())

    def test_only_user_refresh_announces_the_result(self) -> None:
        import types
        from src.app import Application

        calls = []
        fake = types.SimpleNamespace(_on_refresh_devices=lambda announce=False: calls.append(announce))
        Application._on_user_refresh_devices(fake)
        self.assertEqual(calls, [True])
        import inspect
        default = inspect.signature(Application._on_refresh_devices).parameters["announce"].default
        self.assertIs(default, False, "açılıştaki otomatik yenileme ileti göstermez")


class ThemePassTest(_QtCase):
    def test_empty_transfer_title_uses_the_main_text_tone_in_both_themes(self) -> None:
        from PyQt6.QtGui import QColor
        from src.gui.transfer_item import EMPTY_HINT_COLORS, _EmptyHintList

        app = QApplication.instance()
        old = app.property("tt_dark")
        self.addCleanup(lambda: app.setProperty("tt_dark", old))
        for theme, dark in (("dark", True), ("light", False)):
            app.setProperty("tt_dark", dark)
            title, hint = (QColor(c) for c in EMPTY_HINT_COLORS[theme])
            self.assertGreater(abs(title.lightness() - hint.lightness()), 40, "başlık açıklamadan belirgin")
            widget = _EmptyHintList()
            self.addCleanup(widget.deleteLater)
            widget.setStyleSheet("background: %s;" % ("#202020" if dark else "#f5f5f5"))
            widget.resize(600, 300)
            widget.set_hint("Henüz transfer yok", "Soldan bir cihaz seçin")
            widget.show()
            QApplication.processEvents()
            image = widget.viewport().grab().toImage()
            pixels = [image.pixelColor(x, y).lightness() for x in range(0, image.width(), 2)
                      for y in range(image.height() // 2 - 45, image.height() // 2 - 15)]
            extreme = max(pixels) if dark else min(pixels)
            self.assertLess(abs(extreme - title.lightness()), 30, f"{theme}: başlık ana metin tonunda çizilir")

    def test_notice_bar_edge_has_small_left_radius(self) -> None:
        from src.gui.notice_bar import NoticeBar
        from src.utils.remote_notice import Notice

        bar = NoticeBar()
        self.addCleanup(bar.deleteLater)
        bar.show_notice(Notice(id="n1", text="Duyuru"))
        sheet = bar.styleSheet()
        self.assertIn("border-top-left-radius: 3px", sheet)
        self.assertIn("border-bottom-left-radius: 3px", sheet)


if __name__ == "__main__":
    unittest.main()
