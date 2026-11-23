"""Güncelleme denetim takvimi: uzun süre açılmayan uygulama açılışta hemen denetler; açıkken birkaç saatte bir
denetler; zamanlayıcı sık "tıklar" (duvar saatine bakar), böylece uyku/hazırda bekleme sonrası kaçan denetim de yakalanır.

Kullanıcı: "arka planda güncelleme kontrolü yapmıyor ... uzun süre açmayıp sonra açanlarda direk kontrol yapılabilir."
Eskiden açılışta ancak 24 saat geçtiyse denetleniyor, zamanlayıcı da ancak 24 saat kesintisiz açık kalınca tetikleniyordu."""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (yalıtılmış kullanıcı dizini)
from support import FakeConfig  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.utils.updater import UpdateChecker  # noqa: E402


def make_checker(last, auto):
    checker = UpdateChecker()
    values = {"auto_update_check": auto}
    if last is not None:
        values["last_update_check"] = last
    checker.config = FakeConfig(**values)
    return checker


def _ago(**kw) -> str:
    return (datetime.now() - timedelta(**kw)).isoformat()


class UpdateScheduleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def run_start(self, last, auto=True):
        checker = make_checker(last, auto)
        self.addCleanup(checker.stop)
        with mock.patch.object(checker, "check_for_updates") as check:
            checker.start()
        return checker, check

    def test_policy_constants(self) -> None:
        self.assertEqual(UpdateChecker.STARTUP_STALE_HOURS, 1)
        self.assertEqual(UpdateChecker.CHECK_INTERVAL_HOURS, 4)
        self.assertEqual(UpdateChecker.TICK_MINUTES, 30)

    def test_start_checks_when_last_check_is_older_than_an_hour(self) -> None:
        checker, check = self.run_start(_ago(hours=2))
        check.assert_called_once_with(show_message=False)
        self.assertTrue(checker.check_timer.isActive())
        self.assertEqual(checker.check_timer.interval(), 30 * 60 * 1000)

    def test_start_checks_after_days_away_and_on_first_run(self) -> None:
        for last in (_ago(days=9), None, "bozuk tarih"):
            with self.subTest(last=last):
                _, check = self.run_start(last)
                check.assert_called_once_with(show_message=False)

    def test_start_skips_a_fresh_check(self) -> None:
        checker, check = self.run_start(_ago(minutes=10))
        check.assert_not_called()
        self.assertTrue(checker.check_timer.isActive(), "denetim atlansa da zamanlayıcı kurulmalı")

    def test_tick_checks_only_every_few_hours(self) -> None:
        for last, expected in ((_ago(hours=3), False), (_ago(hours=5), True), (_ago(days=2), True)):
            with self.subTest(last=last):
                checker = make_checker(last, True)
                with mock.patch.object(checker, "check_for_updates") as check:
                    checker._auto_check()
                self.assertEqual(check.called, expected)

    def test_disabled_auto_check_does_nothing(self) -> None:
        checker, check = self.run_start(_ago(days=9), auto=False)
        check.assert_not_called()
        self.assertFalse(checker.check_timer.isActive())


class UpdateCheckRetryTest(unittest.TestCase):
    """DNS ya da bağlantı birkaç saniyeliğine takılınca denetim hemen "denetlenemedi" demez: 3 ve 8 sn sonra yeniden
    dener; kalıcı hatada beklemez, uygulama kapanırken bekleme hemen biter."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from src.utils import updater as upd

        self.upd = upd
        self.slept: list = []
        pause = mock.patch.object(upd, "_pause", side_effect=lambda seconds, stop: self.slept.append(seconds) or True)
        pause.start()
        self.addCleanup(pause.stop)
        self.pause_patch = pause

    @staticmethod
    def dns_error():
        import socket
        import urllib.error

        return urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))

    @staticmethod
    def http_error(code: int):
        import urllib.error

        return urllib.error.HTTPError("https://macik.com.tr/api/updates/check", code, "x", None, None)

    def open_with(self, *outcomes):
        with mock.patch.object(self.upd.urllib.request, "urlopen", side_effect=list(outcomes)) as urlopen:
            try:
                return self.upd.urlopen_with_retry("req", 10), urlopen.call_count
            except Exception as exc:  # noqa: BLE001
                return exc, urlopen.call_count

    def test_policy(self) -> None:
        self.assertEqual(tuple(self.upd.RETRY_DELAYS), (3.0, 8.0))

    def test_a_dns_hiccup_is_asked_again(self) -> None:
        result, calls = self.open_with(self.dns_error(), self.dns_error(), "yanıt")
        self.assertEqual((result, calls), ("yanıt", 3))
        self.assertEqual(self.slept, [3.0, 8.0])

    def test_a_busy_server_is_asked_again_then_the_error_stands(self) -> None:
        result, calls = self.open_with(*(self.http_error(503) for _ in range(3)))
        self.assertEqual((getattr(result, "code", None), calls), (503, 3))

    def test_lasting_errors_are_not_retried(self) -> None:
        import ssl
        import urllib.error

        for error in (self.http_error(404), urllib.error.URLError("unknown url type: x"),
                      urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")), ValueError("bozuk")):
            with self.subTest(error=repr(error)):
                self.slept.clear()
                result, calls = self.open_with(error, "yanıt")
                self.assertIs(result, error)
                self.assertEqual((calls, self.slept), (1, []))

    def test_transient_kinds(self) -> None:
        for code, expected in ((408, True), (429, True), (500, True), (522, True), (400, False), (403, False)):
            self.assertIs(self.upd.is_transient_error(self.http_error(code)), expected, code)
        self.assertTrue(self.upd.is_transient_error(TimeoutError()))
        self.assertTrue(self.upd.is_transient_error(ConnectionResetError()))

    def test_a_stop_request_ends_the_wait_at_once(self) -> None:
        import time

        self.pause_patch.stop()  # gerçek bekleme
        started = time.monotonic()
        result, calls = self.open_with_real_pause(stop=lambda: True)
        self.assertEqual(calls, 1)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIsInstance(result, OSError)

    def open_with_real_pause(self, stop):
        with mock.patch.object(self.upd.urllib.request, "urlopen", side_effect=[self.dns_error(), "yanıt"]) as urlopen:
            try:
                return self.upd.urlopen_with_retry("req", 10, stop=stop), urlopen.call_count
            except Exception as exc:  # noqa: BLE001
                return exc, urlopen.call_count

    def test_stop_interrupts_a_check_that_waits_to_retry(self) -> None:
        """Kapanışta süren denetim beklenir: yeniden deneme beklemesi kesilmezse çıkış 30 sn takılırdı."""
        import time

        self.pause_patch.stop()
        checker = make_checker(None, True)
        with mock.patch.object(self.upd, "RETRY_DELAYS", (30.0,)), \
             mock.patch.object(self.upd.urllib.request, "urlopen", side_effect=self.dns_error()):
            thread = checker._manual_thread = self.upd._ManualCheckThread(checker)
            thread.start()
            time.sleep(0.3)
            started = time.monotonic()
            checker.stop()
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertFalse(thread.isRunning())


if __name__ == "__main__":
    unittest.main()
