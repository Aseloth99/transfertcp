"""Uygulama yasam dongusu: normal cikista stop() (GOODBYE, TCP, DB) calismali, idempotent olmali.

Madde 4. Pencere/QApplication acilmaz; Application.stop() sahte `self` ile, aboutToQuit baglantisi
ise gercek (offscreen) QApplication uzerinden denenir.
"""

import inspect
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401

import main  # noqa: E402
from src.app import Application  # noqa: E402


class _Log:
    def __init__(self):
        self.errors = []

    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, message, *a, **k): self.errors.append(message)


class _Component:
    def __init__(self, calls, name, fail=False):
        self.calls, self.name, self.fail = calls, name, fail

    def _record(self):
        self.calls.append(self.name)
        if self.fail:
            raise RuntimeError(f"{self.name} patladi")

    stop = _record
    close = _record


def make_fake_app(fail=()):
    calls = []
    fake = types.SimpleNamespace(
        logger=_Log(),
        discovery=_Component(calls, "discovery", "discovery" in fail),
        tcp_server=_Component(calls, "tcp_server", "tcp_server" in fail),
        transfer_manager=_Component(calls, "transfer_manager"),
        update_checker=_Component(calls, "update_checker"),
        database=_Component(calls, "database"),
        _stopped=False,
    )
    return fake, calls


class StopTest(unittest.TestCase):
    def test_stop_stops_everything_in_order(self) -> None:
        fake, calls = make_fake_app()
        Application.stop(fake)
        self.assertEqual(calls, ["discovery", "tcp_server", "transfer_manager", "update_checker", "database"])

    def test_stop_is_idempotent(self) -> None:
        fake, calls = make_fake_app()
        Application.stop(fake)
        Application.stop(fake)
        Application.stop(fake)
        self.assertEqual(len(calls), 5, "kapanis adimlari birden fazla kez calisti")

    def test_one_failing_step_does_not_block_goodbye_or_db_close(self) -> None:
        fake, calls = make_fake_app(fail=("discovery", "tcp_server"))
        Application.stop(fake)
        self.assertIn("database", calls)
        self.assertIn("transfer_manager", calls)
        self.assertEqual(len(fake.logger.errors), 2)


class ShutdownHookTest(unittest.TestCase):
    def test_about_to_quit_triggers_stop_exactly_once(self) -> None:
        qt_app = support.qt_app()  # tek QApplication (diger Qt testleriyle paylasilir)
        fake, calls = make_fake_app()
        holder = types.SimpleNamespace(stop=lambda: Application.stop(fake))
        main._install_shutdown_hook(qt_app, holder)
        qt_app.aboutToQuit.emit()  # QApplication.quit() -> aboutToQuit
        qt_app.aboutToQuit.emit()  # ikinci kez (ornegin restart yolu) zararsiz olmali
        self.assertEqual(calls.count("discovery"), 1)
        self.assertEqual(calls.count("database"), 1)

    def test_main_installs_the_hook_and_stops_after_exec(self) -> None:
        source = inspect.getsource(main.main)
        self.assertIn("_install_shutdown_hook(app, transfer_app)", source)
        self.assertIn("transfer_app.stop()", source)
        self.assertLess(source.index("_install_shutdown_hook("), source.index("app.exec()"))

    def test_main_tears_the_gui_down_after_exec_on_every_exit(self) -> None:
        """Gerçek exe ara sıra Python sonlandırmasında çöküyordu: GUI nesneleri `exec()` ve `stop()` sonrası sabit sırayla yok edilir."""
        source = inspect.getsource(main.main)
        self.assertIn("transfer_app.teardown_qt_objects()", source)
        self.assertLess(source.index("transfer_app.stop()"), source.index("transfer_app.teardown_qt_objects()"))
        self.assertLess(source.index("app.exec()"), source.index("transfer_app.teardown_qt_objects()"))


if __name__ == "__main__":
    unittest.main()
