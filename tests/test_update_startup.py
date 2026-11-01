"""Güncelleme sonrası açılış: `--wait-pid` / `--show-window` / `--updated`, sürüm koruması (kilitten sonra), sağlıklı-sürüm onayı, port yeniden bağlama.

Gerçek exe başlatılmaz, gerçek pencere/tepsi açılmaz; süreç bekleme ve başlatma sahte, dosyalar geçici klasörde.
"""

import os
import socket
import sys
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401
from support import FakeConfig, free_port, make_update_app  # noqa: E402

import main as main_module  # noqa: E402
import src.app as app_module  # noqa: E402
from src.utils import self_update as su  # noqa: E402

APP = app_module.Application


class ShouldShowWindowTest(unittest.TestCase):
    def test_truth_table(self):
        show = APP._should_show_window
        self.assertTrue(show(True, True, ["x"]), "ilk kurulumda pencere her zaman açılır")
        self.assertTrue(show(False, True, ["x", "--show-window"]), "--show-window 'simge durumunda başlat'ı geçersiz kılar")
        self.assertFalse(show(False, True, ["x", "--minimized"]), "--minimized tepside kalır")
        self.assertFalse(show(False, True, ["x"]), "ayar: simge durumunda başlat")
        self.assertTrue(show(False, False, ["x"]), "ayar kapalıysa pencere açılır")
        self.assertFalse(show(False, False, ["x", "--minimized"]), "otomatik başlatma bayrağı yine de gizler")

    def test_start_uses_it(self):
        import inspect

        self.assertIn("self._should_show_window(was_first_run, start_minimized, sys.argv)", inspect.getsource(APP.start))


class UpdateRestartFlagsTest(unittest.TestCase):
    def test_is_update_restart(self):
        self.assertTrue(APP._is_update_restart(["TransferTCP.exe", "--wait-pid", "123", "--minimized"]))
        self.assertTrue(APP._is_update_restart(["TransferTCP.exe", "--updated", "1.0.0"]))
        self.assertFalse(APP._is_update_restart(["TransferTCP.exe", "--minimized"]))
        self.assertFalse(APP._is_update_restart(["TransferTCP.exe"]))

    def test_followups_announce_only_after_an_update(self):
        fake = types.SimpleNamespace(_announce_update_installed=lambda: None, _arm_health_confirmation=mock.Mock())
        with mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._schedule_update_followups(fake, ["x", "--wait-pid", "5", "--updated", "1.0.0", "--minimized"])
        single_shot.assert_called_once()
        self.assertEqual(single_shot.call_args.args[0], 1500)
        fake._arm_health_confirmation.assert_called_once()
        fake._arm_health_confirmation.reset_mock()
        with mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._schedule_update_followups(fake, ["x", "--minimized"])
        single_shot.assert_not_called()
        fake._arm_health_confirmation.assert_called_once()

    def test_updated_toast_text_and_notification_setting(self):
        from src.utils.locales import t

        for lang, expected in (("tr", "TransferTCP v1.2.3 sürümüne güncellendi."), ("en", "TransferTCP was updated to v1.2.3.")):
            for enabled in (True, False):
                config = FakeConfig(notifications_enabled=enabled)
                status = []
                fake = types.SimpleNamespace(
                    config=config, logger=mock.Mock(),
                    update_checker=types.SimpleNamespace(current_version="1.2.3"),
                    window=types.SimpleNamespace(show_status_message=lambda text, ms=3000: status.append(text)),
                )
                with mock.patch.object(app_module, "get_active_language", return_value=lang), \
                        mock.patch.object(app_module.SystemToast, "show") as toast:
                    APP._announce_update_installed(fake)
                self.assertEqual(status, [expected])
                self.assertEqual(toast.call_count, 1 if enabled else 0, (lang, enabled))
                if enabled:
                    self.assertEqual(toast.call_args.args, ("TransferTCP", expected))
                self.assertEqual(expected, t("update_installed_toast", lang).format(app="TransferTCP", version="1.2.3"))


class SelfUpdateStartupTest(unittest.TestCase):
    """main: kilitten ÖNCE eski süreci bekle; sürüm koruması kilit alındıktan SONRA (ikinci çift tıklama sağlam yeni
    sürümü geri aldırmasın)."""

    class Lock:
        def __init__(self):
            self.unlocked = 0

        def unlock(self):
            self.unlocked += 1

    def run_guard(self, frozen, guard_result=su.Guard.NORMAL):
        lock, order = self.Lock(), []
        with mock.patch.object(su, "startup_guard", side_effect=lambda e, v: order.append(("guard", e, v)) or guard_result), \
                mock.patch.object(su, "spawn", side_effect=lambda e, a: order.append(("spawn", e, list(a)))), \
                mock.patch.object(sys, "frozen", frozen, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\TransferTCP.exe"):
            result = main_module._startup_guard(lock)
        return result, order, lock

    def test_waits_for_the_previous_process_with_the_command_line(self):
        calls = []
        with mock.patch.object(main_module, "argv", ["TransferTCP.exe", "--wait-pid", "99"]),                 mock.patch.object(su, "wait_for_previous_instance", side_effect=lambda a: calls.append(list(a))):
            main_module._wait_for_previous_instance()
        self.assertEqual(calls, [["TransferTCP.exe", "--wait-pid", "99"]])

    def test_a_wait_error_never_blocks_the_start(self):
        with mock.patch.object(su, "wait_for_previous_instance", side_effect=RuntimeError("boom")):
            main_module._wait_for_previous_instance()

    def test_the_guard_checks_the_running_exe_and_version(self):
        result, order, lock = self.run_guard(True)
        self.assertTrue(result)
        self.assertEqual(order, [("guard", r"C:\Apps\TransferTCP.exe", "1.0.0")])
        self.assertEqual(lock.unlocked, 0)

    def test_a_rolled_back_version_releases_the_lock_launches_the_old_exe_minimized_and_exits(self):
        result, order, lock = self.run_guard(True, guard_result=su.Guard.ROLLED_BACK)
        self.assertFalse(result, "bu (bozuk) süreç hemen çıkmalı")
        self.assertEqual(order[-1], ("spawn", r"C:\Apps\TransferTCP.exe", ["--minimized"]))
        self.assertEqual(lock.unlocked, 1, "geri gelen sürüm kilidi alabilsin")

    def test_probation_continues_normally(self):
        result, order, lock = self.run_guard(True, guard_result=su.Guard.PROBATION)
        self.assertTrue(result)
        self.assertNotIn("spawn", [step[0] for step in order])

    def test_source_runs_never_touch_the_guard(self):
        result, order, _lock = self.run_guard(False)
        self.assertTrue(result)
        self.assertEqual(order, [])

    def test_a_guard_error_never_blocks_the_start(self):
        with mock.patch.object(sys, "frozen", True, create=True),                 mock.patch.object(su, "startup_guard", side_effect=RuntimeError("boom")):
            self.assertTrue(main_module._startup_guard(self.Lock()))

    def test_main_order_wait_then_lock_then_guard_then_qt(self):
        import inspect

        source = inspect.getsource(main_module.main)
        wait = source.index("_wait_for_previous_instance()")
        lock = source.index("QLockFile(lock_path)")
        guard = source.index("_startup_guard(lock)")
        qt = source.index("# Create QApplication")
        self.assertLess(wait, lock, "eski süreci beklemek kilitten ÖNCE")
        self.assertLess(lock, guard, "sürüm koruması kilitten SONRA: kilide takılan ikinci başlatma 'açılış' sayılmaz")
        self.assertLess(guard, qt)
        self.assertIn("_acquire_lock(lock, Application._is_update_restart(argv))", source)

    def test_lock_retry_is_patient_only_after_an_update_restart(self):
        class Lock:
            def __init__(self, free_after):
                self.calls, self.free_after = 0, free_after

            def tryLock(self, ms):
                self.calls += 1
                return self.calls > self.free_after

        with mock.patch("time.sleep"):
            self.assertTrue(main_module._acquire_lock(Lock(0), False))
            impatient = Lock(3)
            self.assertFalse(main_module._acquire_lock(impatient, False))
            self.assertEqual(impatient.calls, 1, "normal açılışta beklenmez (başka kopya çalışıyor)")
            patient = Lock(5)
            self.assertTrue(main_module._acquire_lock(patient, True), "güncelleme yeniden başlatması kilit boşalana dek bekler")
            self.assertGreater(patient.calls, 1)
            stuck = Lock(10**6)
            self.assertFalse(main_module._acquire_lock(stuck, True))
            self.assertLessEqual(stuck.calls, 41, "sonsuza dek beklemez")

    def test_the_wait_helper_really_waits_for_a_live_process(self):
        if os.name != "nt":
            self.skipTest("Windows")
        import subprocess

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.0)"])
        try:
            started = time.monotonic()
            self.assertTrue(su.wait_for_previous_instance(["x", "--wait-pid", str(child.pid)], timeout=15))
            self.assertGreater(time.monotonic() - started, 0.4)
        finally:
            child.kill()
            child.wait()


class HealthConfirmationTest(unittest.TestCase):
    """Yeni sürüm 60 sn sonra ve (>= 10 sn çalışmışsa) temiz çıkışta kendini kanıtlar; güncelleme için çıkışta kanıtlamaz."""

    def fake(self):
        return make_update_app(pending=False)

    def bind(self, fake):
        for name in ("_confirm_healthy", "_confirm_healthy_on_quit"):
            setattr(fake, name, types.MethodType(getattr(APP, name), fake))
        fake._started_at = time.monotonic()
        return fake

    def test_not_frozen_arms_nothing(self):
        with mock.patch("src.utils.update_policy.is_frozen", return_value=False), \
                mock.patch.object(app_module.QTimer, "singleShot") as single_shot:
            APP._arm_health_confirmation(self.fake())
        single_shot.assert_not_called()

    def test_frozen_arms_a_sixty_second_timer_and_the_quit_hook(self):
        fake = self.bind(self.fake())
        qt = support.qt_app()
        with mock.patch("src.utils.update_policy.is_frozen", return_value=True), \
                mock.patch.object(app_module, "current_exe", return_value=r"C:\Apps\TransferTCP.exe"), \
                mock.patch.object(app_module.QTimer, "singleShot") as single_shot, \
                mock.patch.object(qt, "aboutToQuit") as quit_signal:
            APP._arm_health_confirmation(fake)
        self.assertEqual(single_shot.call_args.args[0], 60_000)
        quit_signal.connect.assert_called_once()

    def test_timer_confirms_unless_we_are_quitting_for_an_update(self):
        fake = self.bind(self.fake())
        with mock.patch.object(su, "confirm_healthy") as confirm:
            fake._confirm_healthy("exe")
            confirm.assert_called_once_with("exe")
            confirm.reset_mock()
            fake._quitting_for_update = True
            fake._confirm_healthy("exe")
            confirm.assert_not_called()

    def test_clean_quit_confirms_only_after_ten_seconds(self):
        fake = self.bind(self.fake())
        with mock.patch.object(su, "confirm_healthy") as confirm:
            fake._started_at = time.monotonic() - 3
            fake._confirm_healthy_on_quit("exe")
            confirm.assert_not_called()
            fake._started_at = time.monotonic() - 11
            fake._confirm_healthy_on_quit("exe")
            confirm.assert_called_once_with("exe")

    def test_the_updating_process_never_deletes_its_own_image_on_quit(self):
        """Güncellemeyi yapan süreç `.old` olarak yeniden adlandırılmış kendi exe'sidir; çıkışta onu silmeye çalışmamalı."""
        fake = self.bind(self.fake())
        fake._started_at = time.monotonic() - 600
        fake._quitting_for_update = True
        with mock.patch.object(su, "confirm_healthy") as confirm:
            fake._confirm_healthy_on_quit("exe")
        confirm.assert_not_called()


class StopCleanupTest(unittest.TestCase):
    def test_running_download_is_cancelled_and_awaited_on_quit(self):
        installer = mock.Mock()
        thread = mock.Mock(isRunning=lambda: True)
        install = mock.Mock(isRunning=lambda: True)
        app = types.SimpleNamespace(update_installer=installer, download_thread=thread, install_thread=install)
        app_module._stop_update_threads(app)
        installer.cancel_download.assert_called_once()
        thread.wait.assert_called_once_with(3000)
        install.wait.assert_called_once_with(10000)

    def test_a_download_stuck_in_a_network_read_is_terminated_so_qt_does_not_abort(self):
        thread = mock.Mock(isRunning=lambda: True)
        thread.wait.side_effect = [False, True]
        app_module._stop_update_threads(types.SimpleNamespace(update_installer=mock.Mock(), download_thread=thread))
        thread.terminate.assert_called_once()

    def test_missing_attributes_are_tolerated(self):
        app_module._stop_update_threads(types.SimpleNamespace())


class PortRebindTest(unittest.TestCase):
    """Güncelleme yeniden başlatması: eski süreç çıkarken port kısa süre meşgul kalabilir; kalıcı port kayması olmaz."""

    def setUp(self):
        from src.core.server import TCPServer
        from src.core.transfer import TransferManager
        from src.utils.config import get_config

        support.qt_app()
        self.config = get_config()
        self.port = self._free_run(3)
        self.config.config.setdefault("transfer", {})["port"] = self.port
        self.server = TCPServer(TransferManager())
        self.addCleanup(self.server.stop, 0.2)
        self.blockers = []
        self.addCleanup(self._release)

    @staticmethod
    def _free_run(length):
        """Art arda `length` boş port. Dinamik aralığın (49152+) DIŞINDA seçilir: orada başka programların giden
        bağlantıları rastgele portları tutar ve özel-kullanım bağlamayı (EACCES) beklenmedik biçimde bozar."""
        import random
        from src.core.netio import make_listen_socket

        for _ in range(200):
            first = random.randint(20000, 45000)
            probes = []
            try:
                for offset in range(length):
                    probes.append(make_listen_socket(first + offset))
                return first
            except OSError:
                continue
            finally:
                for probe in probes:
                    probe.close()
        raise RuntimeError("art arda boş port bulunamadı")

    def _release(self):
        for blocker in self.blockers:
            try:
                blocker.close()
            except OSError:
                pass

    def block(self, port):
        from src.core.netio import make_listen_socket

        blocker = make_listen_socket(port)
        self.blockers.append(blocker)
        return blocker

    def test_defaults_are_unchanged_for_normal_launches(self):
        self.assertEqual(self.server.bind_retry_seconds, 0.0)
        self.assertTrue(self.server.remember_port_fallback)

    def test_a_briefly_busy_preferred_port_is_retried_and_obtained(self):
        blocker = self.block(self.port)
        self.server.bind_retry_seconds = 5.0
        threading.Timer(0.6, blocker.close).start()
        started = time.monotonic()
        self.server.start()
        self.assertTrue(self.server.running)
        self.assertEqual(self.server.port, self.port, "tercih edilen port yeniden denemeyle alındı")
        self.assertGreater(time.monotonic() - started, 0.3)
        self.assertEqual(self.config.get("transfer", "port", None), self.port)

    def test_without_retry_a_busy_port_falls_back_immediately_and_is_remembered(self):
        self.block(self.port)
        started = time.monotonic()
        self.server.start()
        self.assertEqual(self.server.port, self.port + 1)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(self.config.get("transfer", "port", None), self.port + 1, "olağan davranış: kayma kaydedilir")
        self.config.config["transfer"]["port"] = self.port

    def test_an_update_restart_never_persists_a_port_drift(self):
        self.block(self.port)
        self.server.bind_retry_seconds = 0.5
        self.server.remember_port_fallback = False
        changed = []
        self.server.on_port_changed = lambda old, new: changed.append((old, new))
        self.server.start()
        self.assertEqual(self.server.port, self.port + 1, "geçici olarak başka porta geçilir")
        self.assertEqual(changed, [(self.port, self.port + 1)], "kullanıcı yine bilgilendirilir")
        self.assertEqual(self.config.get("transfer", "port", None), self.port,
                         "yapılandırma değişmez: sonraki açılış yine tercih edilen portu dener")

    def test_only_the_preferred_port_is_retried(self):
        self.block(self.port)
        self.block(self.port + 1)
        self.server.bind_retry_seconds = 0.6
        started = time.monotonic()
        self.server.start()
        self.assertEqual(self.server.port, self.port + 2)
        self.assertLess(time.monotonic() - started, 2.0, "yedek portlarda bekleme yok")

    def test_application_enables_the_grace_only_for_update_restarts(self):
        import inspect

        source = inspect.getsource(APP.__init__)
        self.assertIn("if self._is_update_restart():", source)
        self.assertIn("self.tcp_server.bind_retry_seconds = UPDATE_RESTART_BIND_GRACE", source)
        self.assertIn("self.tcp_server.remember_port_fallback = False", source)
        self.assertGreaterEqual(app_module.UPDATE_RESTART_BIND_GRACE, 2.0)


if __name__ == "__main__":
    unittest.main()
