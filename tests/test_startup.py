"""Madde 5: otomatik baslatma backend'leri (Windows Run anahtari, macOS LaunchAgent, Linux XDG).

GERCEK kayit defterine ASLA dokunulmaz: Windows backend'i `winreg` benzeri sahte modulle sinanir;
macOS/Linux backend'leri gecici HOME/yapilandirma dizininde gercek dosyalarla calisir.
"""

import configparser
import os
import plistlib
import stat
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import fresh_dir  # noqa: E402

from src.utils import startup  # noqa: E402
from src.utils.paths import BUNDLE_ID  # noqa: E402

POSIX = os.name == "posix"


class FakeWinreg:
    """winreg yerine gecen sahte modul: tek anahtar (Run) icin sozluk."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    KEY_READ = 131097
    REG_SZ = 1

    def __init__(self, preset=None, fail_open=False):
        self.values = dict(preset or {})
        self.opened = []
        self.fail_open = fail_open

    def OpenKey(self, root, sub, reserved, access):
        if self.fail_open:
            raise PermissionError("erisim yok")
        self.opened.append((root, sub, access))
        assert root == "HKCU" and sub == r"Software\Microsoft\Windows\CurrentVersion\Run", (root, sub)
        return object()

    def SetValueEx(self, key, name, reserved, kind, value):
        assert kind == self.REG_SZ
        self.values[name] = value

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]

    def CloseKey(self, key):
        pass


class WindowsBackendTest(unittest.TestCase):
    def backend(self, **kwargs):
        self.reg = FakeWinreg(**kwargs)
        return startup.WindowsRunKeyBackend(self.reg)

    def test_enable_writes_quoted_path_with_minimized_flag(self) -> None:
        backend = self.backend()
        self.assertTrue(backend.enable("TransferTCP", r"C:\Apps\TransferTCP.exe", True))
        self.assertEqual(self.reg.values["TransferTCP"], r'"C:\Apps\TransferTCP.exe" --minimized')
        self.assertTrue(backend.enable("TransferTCP", r"C:\Apps\TransferTCP.exe", False))
        self.assertEqual(self.reg.values["TransferTCP"], r'"C:\Apps\TransferTCP.exe"')

    def test_enabled_disabled_roundtrip_and_idempotent_disable(self) -> None:
        backend = self.backend()
        self.assertFalse(backend.is_enabled("TransferTCP"))
        self.assertTrue(backend.enable("TransferTCP", r"C:\A\T.exe", True))
        self.assertTrue(backend.is_enabled("TransferTCP"))
        self.assertTrue(backend.disable("TransferTCP"))
        self.assertFalse(backend.is_enabled("TransferTCP"))
        self.assertTrue(backend.disable("TransferTCP"), "kayit yokken kaldirma basarili sayilmali")

    def test_registry_errors_return_false_not_raise(self) -> None:
        backend = self.backend(fail_open=True)
        self.assertFalse(backend.enable("TransferTCP", r"C:\A\T.exe", True))
        self.assertFalse(backend.disable("TransferTCP"))
        self.assertFalse(backend.is_enabled("TransferTCP"))
        self.assertFalse(backend.update_if_needed("TransferTCP", True))

    def test_command_builder_is_unchanged(self) -> None:
        self.assertEqual(startup.build_startup_command(True, r"C:\A B\T.exe"), r'"C:\A B\T.exe" --minimized')
        self.assertEqual(startup.build_startup_command(True, r'"C:\A\T.exe"'), r'"C:\A\T.exe" --minimized')
        self.assertEqual(startup._parse_run_value_path(r'"C:\A B\T.exe" --minimized'), r"C:\A B\T.exe")
        self.assertEqual(startup._parse_run_value_path(r"C:\A\T.exe --minimized"), r"C:\A\T.exe")
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", r"C:\Frozen\T.exe"):
            self.assertEqual(startup.build_startup_command(True), r'"C:\Frozen\T.exe" --minimized')

    def test_module_api_with_injected_backend_never_touches_the_real_registry(self) -> None:
        backend = self.backend()
        guard = mock.Mock(side_effect=AssertionError("GERCEK kayit defterine dokunuldu"))
        patchers = []
        if sys.platform == "win32":
            import winreg
            patchers = [mock.patch.object(winreg, "OpenKey", guard), mock.patch.object(winreg, "SetValueEx", guard),
                        mock.patch.object(winreg, "DeleteValue", guard)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertTrue(startup.add_to_startup("TransferTCP", r"C:\A\T.exe", True, backend=backend))
        self.assertTrue(startup.is_in_startup("TransferTCP", backend=backend))
        startup.update_startup_path_if_needed("TransferTCP", True, backend=backend)  # patlamamali
        self.assertTrue(startup.remove_from_startup("TransferTCP", backend=backend))
        guard.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "yol karsilastirmasi Windows yol bicimine (abspath) baglidir")
class WindowsBackendUpdateTest(unittest.TestCase):
    def backend(self, **kwargs):
        self.reg = FakeWinreg(**kwargs)
        return startup.WindowsRunKeyBackend(self.reg)

    def _frozen(self, exe):
        stack = [mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", exe)]
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_update_only_when_enabled(self) -> None:
        self._frozen(r"C:\New\TransferTCP.exe")
        backend = self.backend()
        self.assertFalse(backend.update_if_needed("TransferTCP", True))
        self.assertEqual(self.reg.values, {})

    def test_update_rewrites_a_moved_program_path(self) -> None:
        self._frozen(r"C:\New\TransferTCP.exe")
        backend = self.backend(preset={"TransferTCP": r'"C:\Old\TransferTCP.exe" --minimized'})
        self.assertTrue(backend.update_if_needed("TransferTCP", True))
        self.assertEqual(self.reg.values["TransferTCP"], r'"C:\New\TransferTCP.exe" --minimized')
        self.assertFalse(backend.update_if_needed("TransferTCP", True), "ikinci cagri degisiklik yapmamali")

    def test_update_fixes_minimized_flag_and_console_python(self) -> None:
        self._frozen(r"C:\New\TransferTCP.exe")
        backend = self.backend(preset={"TransferTCP": r'"C:\New\TransferTCP.exe"'})
        self.assertTrue(backend.update_if_needed("TransferTCP", True))
        self.assertTrue(self.reg.values["TransferTCP"].endswith("--minimized"))
        backend = self.backend(preset={"TransferTCP": r'"C:\Py\python.exe" "C:\App\main.py" --minimized'})
        self.assertTrue(backend.update_if_needed("TransferTCP", True))
        self.assertEqual(self.reg.values["TransferTCP"], r'"C:\New\TransferTCP.exe" --minimized')


MAC_EXE = "/Applications/TransferTCP.app/Contents/MacOS/TransferTCP"


def mac_argv(exe=MAC_EXE):
    return lambda minimized, app_path: startup.launch_argv(
        minimized, app_path, frozen=True, executable=exe, env={})


class MacBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = fresh_dir("machome")
        self.backend = startup.MacLaunchAgentBackend(home=self.home, argv_factory=mac_argv())
        self.path = os.path.join(self.home, "Library", "LaunchAgents", "com.macik.transfertcp.plist")

    def _read(self, backend=None) -> dict:
        with open((backend or self.backend).plist_path("TransferTCP"), "rb") as handle:
            return plistlib.load(handle)

    def _legacy_plist(self, label: str) -> str:
        path = os.path.join(self.home, "Library", "LaunchAgents", f"{label}.plist")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(plistlib.dumps({"Label": label, "ProgramArguments": ["/old/TransferTCP"], "RunAtLoad": True}))
        return path

    def test_enable_writes_a_valid_launchagent_plist(self) -> None:
        self.assertTrue(self.backend.enable("TransferTCP", None, True))
        self.assertEqual(self.path, self.backend.plist_path("TransferTCP"))
        data = self._read()
        self.assertEqual(data["Label"], "com.macik.transfertcp")
        self.assertEqual(data["ProgramArguments"], [MAC_EXE, "--minimized"])
        self.assertIs(data["RunAtLoad"], True)
        self.assertEqual(data["ProcessType"], "Interactive")
        self.assertEqual(data["LimitLoadToSessionType"], "Aqua")
        with open(self.path, "rb") as handle:
            self.assertTrue(handle.read().startswith(b"<?xml"))

    def test_minimized_flag_is_optional(self) -> None:
        self.backend.enable("TransferTCP", None, False)
        self.assertEqual(self._read()["ProgramArguments"], [MAC_EXE])

    def test_custom_app_path_is_used(self) -> None:
        self.backend.enable("TransferTCP", "/opt/Custom/TransferTCP", True)
        self.assertEqual(self._read()["ProgramArguments"], ["/opt/Custom/TransferTCP", "--minimized"])

    def test_is_enabled_disable_and_legacy_cleanup(self) -> None:
        self.assertFalse(self.backend.is_enabled("TransferTCP"))
        self.backend.enable("TransferTCP", None, True)
        legacy = [self._legacy_plist("com.transfertcp"), self._legacy_plist(BUNDLE_ID)]
        self.assertTrue(self.backend.is_enabled("TransferTCP"))
        self.assertTrue(self.backend.disable("TransferTCP"))
        self.assertFalse(os.path.exists(self.path))
        for path in legacy:
            self.assertFalse(os.path.exists(path), f"eski etiketli plist temizlenmedi: {path}")
        self.assertFalse(self.backend.is_enabled("TransferTCP"))
        self.assertTrue(self.backend.disable("TransferTCP"))  # idempotent

    def test_upgrade_from_the_old_label_keeps_autostart_and_migrates_it(self) -> None:
        old = self._legacy_plist(BUNDLE_ID)  # eski sürümün yazdığı etiket (tr.com.macik.transfertcp)
        self.assertTrue(self.backend.is_enabled("TransferTCP"), "güncelleme sonrası Açılışta Başlat kapanmamalı")
        self.assertTrue(self.backend.update_if_needed("TransferTCP", True))
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(old), "eski etiketli plist yeni yazılırken silinmeli (çift başlatma olmasın)")
        self.assertEqual(self._read()["ProgramArguments"], [MAC_EXE, "--minimized"])
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True), "ikinci çağrı değişiklik yapmamalı")

    def test_corrupt_plist_is_treated_as_disabled(self) -> None:
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "wb") as handle:
            handle.write(b"bu bir plist degil")
        self.assertFalse(self.backend.is_enabled("TransferTCP"))
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True))

    def test_update_path_when_app_was_moved(self) -> None:
        self.backend.enable("TransferTCP", None, True)
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True), "ayni yol: degisiklik yok")
        moved = startup.MacLaunchAgentBackend(home=self.home, argv_factory=mac_argv("/Users/a/Apps/TransferTCP.app/Contents/MacOS/TransferTCP"))
        self.assertTrue(moved.update_if_needed("TransferTCP", True))
        self.assertEqual(self._read(moved)["ProgramArguments"][0],
                         "/Users/a/Apps/TransferTCP.app/Contents/MacOS/TransferTCP")
        self.assertTrue(moved.update_if_needed("TransferTCP", False), "bayrak degisti")
        self.assertEqual(self._read(moved)["ProgramArguments"], ["/Users/a/Apps/TransferTCP.app/Contents/MacOS/TransferTCP"])

    def test_update_does_nothing_when_not_enabled(self) -> None:
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True))
        self.assertFalse(os.path.exists(self.path))

    @unittest.skipUnless(POSIX, "POSIX izinleri")
    def test_plist_is_not_writable_by_others(self) -> None:
        old = os.umask(0)
        try:
            self.backend.enable("TransferTCP", None, True)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)

    def test_other_app_names_get_their_own_label(self) -> None:
        self.backend.enable("OtherApp", None, True)
        with open(self.backend.plist_path("OtherApp"), "rb") as handle:
            self.assertEqual(plistlib.load(handle)["Label"], "com.macik.otherapp")

    def test_unwritable_target_returns_false(self) -> None:
        blocker = os.path.join(self.home, "Library")
        with open(blocker, "w") as handle:   # "Library" bir DOSYA: LaunchAgents dizini olusturulamaz
            handle.write("x")
        self.assertFalse(self.backend.enable("TransferTCP", None, True))


class LinuxBackendTest(unittest.TestCase):
    EXE = "/opt/Transfer TCP/TransferTCP"

    def setUp(self) -> None:
        self.config_home = fresh_dir("xdgcfg")
        self.backend = startup.LinuxAutostartBackend(
            config_home=self.config_home,
            argv_factory=lambda minimized, app_path: startup.launch_argv(
                minimized, app_path, frozen=True, executable=self.EXE, env={}))
        self.path = os.path.join(self.config_home, "autostart", "transfertcp.desktop")

    def _parse(self):
        parser = configparser.RawConfigParser(strict=True)
        parser.optionxform = str
        parser.read(self.path, encoding="utf-8")
        return parser["Desktop Entry"]

    def test_enable_writes_a_valid_desktop_entry_with_quoted_exec(self) -> None:
        self.assertTrue(self.backend.enable("TransferTCP", None, True))
        entry = self._parse()
        self.assertEqual(entry["Type"], "Application")
        self.assertEqual(entry["Name"], "TransferTCP")
        self.assertEqual(entry["Exec"], '"/opt/Transfer TCP/TransferTCP" --minimized')
        self.assertEqual(entry["Terminal"], "false")
        self.assertEqual(entry["X-GNOME-Autostart-enabled"], "true")
        with open(self.path, encoding="utf-8") as handle:
            self.assertTrue(handle.read().startswith("[Desktop Entry]\n"))

    def test_roundtrip_and_hidden_entries_count_as_disabled(self) -> None:
        self.assertFalse(self.backend.is_enabled("TransferTCP"))
        self.backend.enable("TransferTCP", None, True)
        self.assertTrue(self.backend.is_enabled("TransferTCP"))
        with open(self.path, encoding="utf-8") as handle:
            text = handle.read()
        for hidden in (text + "Hidden=true\n",
                       text.replace("X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-enabled=false")):
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(hidden)
            self.assertFalse(self.backend.is_enabled("TransferTCP"))
        self.assertTrue(self.backend.disable("TransferTCP"))
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(self.backend.disable("TransferTCP"))

    def test_update_only_when_exec_changed(self) -> None:
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True))
        self.backend.enable("TransferTCP", None, True)
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True))
        self.assertTrue(self.backend.update_if_needed("TransferTCP", False))
        self.assertEqual(self._parse()["Exec"], '"/opt/Transfer TCP/TransferTCP"')

    def test_config_home_defaults_follow_xdg_then_home(self) -> None:
        xdg = os.path.join(fresh_dir("xdg2"), "cfg")
        backend = startup.LinuxAutostartBackend(env={"XDG_CONFIG_HOME": xdg})
        self.assertEqual(backend.desktop_path("TransferTCP"), os.path.join(xdg, "autostart", "transfertcp.desktop"))
        backend = startup.LinuxAutostartBackend(env={"XDG_CONFIG_HOME": "goreli/yol"})
        self.assertEqual(backend.desktop_path("TransferTCP"),
                         os.path.join(os.path.expanduser("~"), ".config", "autostart", "transfertcp.desktop"))

    def test_xdg_directory_is_created_on_demand_and_used(self) -> None:
        xdg = os.path.join(fresh_dir("xdg3"), "cfg")  # henüz yok
        backend = startup.LinuxAutostartBackend(
            argv_factory=lambda minimized, app_path: [self.EXE, *(["--minimized"] if minimized else [])],
            env={"XDG_CONFIG_HOME": xdg})
        with mock.patch.object(os.path, "expanduser", return_value=os.path.join(xdg, "..", "home")):
            self.assertTrue(backend.enable("TransferTCP", None, True))
            self.assertTrue(backend.is_enabled("TransferTCP"))
        self.assertTrue(os.path.isfile(os.path.join(xdg, "autostart", "transfertcp.desktop")))

    def test_old_desktop_file_is_rewritten_once_in_the_shared_format(self) -> None:
        self.backend.enable("TransferTCP", None, True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("Icon=transfertcp\n")    # eski sürüm ekstra anahtarlar yazıyordu
        self.assertTrue(self.backend.update_if_needed("TransferTCP", True))
        with open(self.path, encoding="utf-8") as handle:
            self.assertNotIn("Icon=", handle.read())
        self.assertFalse(self.backend.update_if_needed("TransferTCP", True))

    @unittest.skipUnless(POSIX, "POSIX izinleri")
    def test_desktop_file_is_world_readable_not_writable(self) -> None:
        old = os.umask(0)
        try:
            self.backend.enable("TransferTCP", None, True)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)


class SharedModuleTest(unittest.TestCase):
    """Dosya içeriği/tırnaklama/güvenlik ortak `autostart_unix` modülünde (tests/test_autostart_unix.py); burada
    yalnızca TransferTCP'nin ona gerçekten bağlı olduğu ve eski kopyaların kalmadığı doğrulanır."""

    def test_backends_use_the_shared_module_and_the_old_copies_are_gone(self) -> None:
        from src.utils import autostart_unix
        self.assertIs(startup.autostart_unix, autostart_unix)
        for gone in ("desktop_exec_quote", "build_desktop_exec", "_label"):
            self.assertFalse(hasattr(startup, gone), f"{gone}: ortak modüle taşındı")
        self.assertTrue(issubclass(startup.MacLaunchAgentBackend, startup._UnixBackend))
        self.assertTrue(issubclass(startup.LinuxAutostartBackend, startup._UnixBackend))

    def test_exec_with_spaces_and_special_characters_is_quoted_by_the_shared_code(self) -> None:
        home = fresh_dir("shared_q")
        exe = "/opt/My App/100%/T$x"
        backend = startup.LinuxAutostartBackend(
            config_home=home, argv_factory=lambda minimized, app_path: [exe, "--minimized"])
        self.assertTrue(backend.enable("TransferTCP", None, True))
        with open(backend.desktop_path("TransferTCP"), encoding="utf-8") as handle:
            line = next(l for l in handle.read().splitlines() if l.startswith("Exec="))
        self.assertEqual(line, 'Exec="/opt/My App/100%%/T\\\\$x" --minimized')


class LaunchArgvTest(unittest.TestCase):
    def test_frozen_uses_own_executable(self) -> None:
        self.assertEqual(startup.launch_argv(True, frozen=True, executable="/x/T", env={}), ["/x/T", "--minimized"])
        self.assertEqual(startup.launch_argv(False, frozen=True, executable="/x/T", env={}), ["/x/T"])

    def test_appimage_path_wins_when_it_exists(self) -> None:
        image = os.path.join(fresh_dir("appimg"), "TransferTCP.AppImage")
        with open(image, "wb") as handle:
            handle.write(b"x")
        self.assertEqual(startup.launch_argv(True, frozen=True, executable="/tmp/.mount_x/T", env={"APPIMAGE": image}),
                         [image, "--minimized"])
        self.assertEqual(startup.launch_argv(True, frozen=True, executable="/tmp/.mount_x/T",
                                             env={"APPIMAGE": "/yok/yok.AppImage"}), ["/tmp/.mount_x/T", "--minimized"])

    def test_source_run_uses_interpreter_and_main_py(self) -> None:
        self.assertEqual(startup.launch_argv(True, frozen=False, executable="/usr/bin/python3", entry="/src/main.py", env={}),
                         ["/usr/bin/python3", "/src/main.py", "--minimized"])

    def test_app_path_and_no_duplicate_flag(self) -> None:
        self.assertEqual(startup.launch_argv(True, "/opt/T", frozen=True, executable="/x", env={}), ["/opt/T", "--minimized"])
        self.assertEqual(startup.launch_argv(True, "/opt/T", frozen=True, executable="/x", env={}).count("--minimized"), 1)


class ModuleApiTest(unittest.TestCase):
    def test_get_backend_per_platform(self) -> None:
        self.assertIsInstance(startup.get_backend("win32"), startup.WindowsRunKeyBackend)
        self.assertIsInstance(startup.get_backend("darwin"), startup.MacLaunchAgentBackend)
        self.assertIsInstance(startup.get_backend("linux"), startup.LinuxAutostartBackend)
        self.assertIsNone(startup.get_backend("freebsd14"))

    def test_unsupported_platform_api_returns_false(self) -> None:
        with mock.patch.object(startup, "get_backend", return_value=None):
            self.assertFalse(startup.add_to_startup())
            self.assertFalse(startup.remove_from_startup())
            self.assertFalse(startup.is_in_startup())
            self.assertFalse(startup.update_startup_path_if_needed())

    def test_api_delegates_to_the_injected_backend(self) -> None:
        backend = mock.Mock(spec=startup.StartupBackend)
        backend.enable.return_value = True
        backend.disable.return_value = True
        backend.is_enabled.return_value = True
        backend.update_if_needed.return_value = True
        self.assertTrue(startup.add_to_startup("A", "/p", False, backend=backend))
        backend.enable.assert_called_once_with("A", "/p", False)
        self.assertTrue(startup.remove_from_startup("A", backend=backend))
        backend.disable.assert_called_once_with("A")
        self.assertTrue(startup.is_in_startup("A", backend=backend))
        self.assertTrue(startup.update_startup_path_if_needed("A", False, backend=backend))
        backend.update_if_needed.assert_called_once_with("A", False)

    @unittest.skipUnless(sys.platform.startswith("linux"), "gercek Linux dongusu")
    def test_real_linux_roundtrip_in_the_sandboxed_config_dir(self) -> None:
        backend = startup.get_backend()
        self.assertTrue(startup.add_to_startup(minimized=True, backend=backend))
        self.assertTrue(backend.desktop_path("TransferTCP").startswith(support.SANDBOX_ROOT))
        self.assertTrue(startup.is_in_startup(backend=backend))
        self.assertFalse(startup.update_startup_path_if_needed(minimized=True, backend=backend))
        self.assertTrue(startup.remove_from_startup(backend=backend))
        self.assertFalse(startup.is_in_startup(backend=backend))


if __name__ == "__main__":
    unittest.main()
