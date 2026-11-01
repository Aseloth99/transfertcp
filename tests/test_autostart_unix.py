"""autostart_unix.py birim testleri: geçici HOME'da dosya içerikleri, aç/kapat, idempotentlik, güvenlik."""

import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import autostart_unix as au  # noqa: E402


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()

    def files(self) -> list[str]:
        return sorted(str(p.relative_to(self.home)).replace("\\", "/") for p in self.home.rglob("*") if p.is_file())


class PathTests(unittest.TestCase):
    def test_paths(self) -> None:
        home = Path("/h")
        self.assertEqual(au.plist_path("MediaCompressor", home), home / "Library/LaunchAgents/com.macik.mediacompressor.plist")
        self.assertEqual(au.desktop_path("FlexiKey", home), home / ".config/autostart/flexikey.desktop")
        self.assertEqual(au.plist_label("TransferTCP"), "com.macik.transfertcp")

    def test_app_name_cannot_escape_the_directory(self) -> None:
        for evil in ("../../etc/passwd", "..\\x", "a/b", "  .hidden ", "Ünïcode Ad"):
            with self.subTest(evil=evil):
                name = au.desktop_path(evil, Path("/h")).name
                self.assertNotIn("/", name)
                self.assertNotIn("\\", name)
                self.assertFalse(name.startswith("."))
                self.assertEqual(au.desktop_path(evil, Path("/h")).parent, Path("/h/.config/autostart"))
        with self.assertRaises(ValueError):
            au.plist_path("///", Path("/h"))


class RenderTests(unittest.TestCase):
    def test_plist_roundtrip_and_xml_escaping(self) -> None:
        args = ["/Apps/A & B/<run>.app", '--name="x"', "--minimized"]
        text = au.render_plist("com.macik.test", args)
        self.assertIn("<key>RunAtLoad</key>", text)
        self.assertNotIn("<run>", text)
        self.assertIn("&amp;", text)
        data = plistlib.loads(text.encode("utf-8"))
        self.assertEqual(data, {"Label": "com.macik.test", "ProgramArguments": args, "RunAtLoad": True,
                                "ProcessType": "Interactive", "LimitLoadToSessionType": "Aqua"})

    def test_desktop_basic(self) -> None:
        text = au.render_desktop("FlexiKey", "/opt/fk/FlexiKey --minimized", "Klavye kısayolları")
        self.assertTrue(text.startswith("[Desktop Entry]\nType=Application\n"))
        for line in ("Name=FlexiKey", "Comment=Klavye kısayolları", "Exec=/opt/fk/FlexiKey --minimized",
                     "Terminal=false", "X-GNOME-Autostart-enabled=true"):
            self.assertIn(line + "\n", text)
        self.assertNotIn("Comment=\n", au.render_desktop("A", "a"))

    def test_desktop_value_escaping_blocks_line_injection(self) -> None:
        text = au.render_desktop("Ad\nExec=/bin/evil", "/bin/ok", "yorum\r\nHidden=true\t\x07")
        self.assertEqual([ln for ln in text.splitlines() if ln.startswith("Exec=")], ["Exec=/bin/ok"])
        self.assertNotIn("\nHidden=true", text)
        self.assertIn("Name=Ad\\nExec=/bin/evil", text)
        self.assertEqual(au.desktop_escape("C:\\yol"), "C:\\\\yol")

    def test_exec_quoting(self) -> None:
        self.assertEqual(au.quote_exec_arg("/usr/bin/app"), "/usr/bin/app")
        self.assertEqual(au.quote_exec_arg("--minimized"), "--minimized")
        self.assertEqual(au.quote_exec_arg("/opt/My App/app"), '"/opt/My App/app"')
        self.assertEqual(au.quote_exec_arg('a"b'), '"a\\"b"')
        self.assertEqual(au.quote_exec_arg("$HOME`x`"), '"\\$HOME\\`x\\`"')
        self.assertEqual(au.quote_exec_arg("100%"), "100%%")
        self.assertEqual(au.quote_exec_arg(""), '""')
        self.assertEqual(au.build_exec_line("/opt/My App/app", ["--minimized"]), '"/opt/My App/app" --minimized')

    def test_exec_line_double_escaping_in_file(self) -> None:
        # XDG: tırnak içi ters eğik çizgi, ardından değer kaçışı ayrıca uygulanır (\\$ yazılır)
        text = au.render_desktop("A", au.build_exec_line("/opt/a b/app", ["$X"]))
        self.assertIn('Exec="/opt/a b/app" "\\\\$X"\n', text)


class EnableDisableTests(_Home):
    def test_macos_enable_writes_valid_plist(self) -> None:
        self.assertTrue(au.set_enabled("MediaCompressor", "/Applications/MC.app/Contents/MacOS/MC", ["--minimized"],
                                       True, platform="darwin", home=self.home))
        path = au.plist_path("MediaCompressor", self.home)
        data = plistlib.loads(path.read_bytes())
        self.assertEqual(data["Label"], "com.macik.mediacompressor")
        self.assertEqual(data["ProgramArguments"], ["/Applications/MC.app/Contents/MacOS/MC", "--minimized"])
        self.assertIs(data["RunAtLoad"], True)
        self.assertEqual(data["LimitLoadToSessionType"], "Aqua", "grafiksiz (SSH) oturumda pencereli uygulama açılmaz")
        self.assertEqual(data["ProcessType"], "Interactive")
        self.assertTrue(au.is_enabled("MediaCompressor", "darwin", self.home))
        self.assertEqual(self.files(), ["Library/LaunchAgents/com.macik.mediacompressor.plist"])

    def test_linux_enable_writes_desktop_with_minimized(self) -> None:
        self.assertTrue(au.set_enabled("FlexiKey", "/opt/Flexi Key/FlexiKey", ["--minimized"], True,
                                       platform="linux", home=self.home, display_name="FlexiKey",
                                       comment="Kısayol yöneticisi"))
        text = au.desktop_path("FlexiKey", self.home).read_text(encoding="utf-8")
        self.assertIn('Exec="/opt/Flexi Key/FlexiKey" --minimized\n', text)
        self.assertIn("Name=FlexiKey\n", text)
        self.assertTrue(au.is_enabled("FlexiKey", "linux", self.home))
        self.assertNotIn("\r", text)

    def test_linux_platform_variants(self) -> None:
        for platform in ("linux", "linux2"):
            with self.subTest(platform=platform):
                self.assertTrue(au.set_enabled("T", "/t", [], True, platform, self.home))

    def test_disable_removes_and_is_idempotent(self) -> None:
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform):
                self.assertTrue(au.set_enabled("TransferTCP", "/t/tcp", ["--minimized"], True, platform, self.home))
                self.assertTrue(au.is_enabled("TransferTCP", platform, self.home))
                self.assertTrue(au.set_enabled("TransferTCP", "/t/tcp", [], False, platform, self.home))
                self.assertFalse(au.is_enabled("TransferTCP", platform, self.home))
                self.assertTrue(au.set_enabled("TransferTCP", "/t/tcp", [], False, platform, self.home))  # tekrar kapat

    def test_disable_with_no_directories_creates_nothing(self) -> None:
        self.assertTrue(au.set_enabled("X", "/x", [], False, "linux", self.home))
        self.assertTrue(au.set_enabled("X", "/x", [], False, "darwin", self.home))
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse(au.is_enabled("X", "linux", self.home))

    def test_enable_is_idempotent_and_updates_changed_path(self) -> None:
        au.set_enabled("A", "/a/one", ["--minimized"], True, "linux", self.home)
        path = au.desktop_path("A", self.home)
        before = path.stat().st_mtime_ns
        with mock.patch.object(au.os, "replace", side_effect=AssertionError("yeniden yazılmamalı")):
            self.assertTrue(au.set_enabled("A", "/a/one", ["--minimized"], True, "linux", self.home))
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertTrue(au.set_enabled("A", "/a/two", ["--minimized"], True, "linux", self.home))
        self.assertIn("Exec=/a/two --minimized", path.read_text(encoding="utf-8"))
        self.assertEqual(self.files(), [".config/autostart/a.desktop"])  # geçici dosya artığı yok

    def test_windows_does_nothing(self) -> None:
        for call in (lambda: au.set_enabled("A", "C:\\a.exe", ["--minimized"], True, "win32", self.home),
                     lambda: au.set_enabled("A", "C:\\a.exe", [], False, "win32", self.home)):
            self.assertFalse(call())
        self.assertFalse(au.is_enabled("A", "win32", self.home))
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse(au.set_enabled("A", "/a", [], True, "freebsd", self.home))

    def test_disabled_by_desktop_environment_counts_as_off(self) -> None:
        au.set_enabled("A", "/a", [], True, "linux", self.home)
        path = au.desktop_path("A", self.home)
        path.write_text(path.read_text(encoding="utf-8") + "Hidden=true\n", encoding="utf-8")
        self.assertFalse(au.is_enabled("A", "linux", self.home))
        path.write_text("[Desktop Entry]\nExec=/a\nX-GNOME-Autostart-enabled=false\n", encoding="utf-8")
        self.assertFalse(au.is_enabled("A", "linux", self.home))

    def test_broken_or_foreign_files_are_not_enabled(self) -> None:
        path = au.plist_path("A", self.home)
        path.parent.mkdir(parents=True)
        path.write_text("bozuk", encoding="utf-8")
        self.assertFalse(au.is_enabled("A", "darwin", self.home))
        path.write_bytes(plistlib.dumps({"Label": "x", "RunAtLoad": False, "ProgramArguments": ["/a"]}))
        self.assertFalse(au.is_enabled("A", "darwin", self.home))

    def test_legacy_files_are_removed_and_detected(self) -> None:
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "com.mediacompressor.plist").write_bytes(
            plistlib.dumps({"Label": "com.mediacompressor", "ProgramArguments": ["/old"], "RunAtLoad": True}))
        self.assertTrue(au.is_enabled("MediaCompressor", "darwin", self.home, legacy_plist_labels=("com.mediacompressor",)))
        self.assertFalse(au.is_enabled("MediaCompressor", "darwin", self.home))
        self.assertTrue(au.set_enabled("MediaCompressor", "/new", [], True, "darwin", self.home,
                                       legacy_plist_labels=("com.mediacompressor",)))
        self.assertEqual(sorted(p.name for p in agents.iterdir()), ["com.macik.mediacompressor.plist"])
        self.assertTrue(au.set_enabled("MediaCompressor", "/new", [], False, "darwin", self.home,
                                       legacy_plist_labels=("com.mediacompressor",)))
        self.assertEqual(list(agents.iterdir()), [])
        for evil in ("../../escape", "a/b"):  # eski ad olarak yol verilse bile dışarı çıkılmaz
            au.set_enabled("MediaCompressor", "/x", [], True, "darwin", self.home, legacy_plist_labels=(evil,))
        self.assertEqual(sorted(p.name for p in agents.iterdir()), ["com.macik.mediacompressor.plist"])


class SafetyTests(_Home):
    def _symlink(self, link: Path, target: Path) -> bool:
        try:
            os.symlink(target, link, target_is_directory=target.is_dir())
            return True
        except (OSError, NotImplementedError):
            self.skipTest("bu ortamda sembolik bağ oluşturulamıyor")
            return False

    def test_symlinked_target_file_is_refused_and_untouched(self) -> None:
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("dokunma", encoding="utf-8")
        directory = self.home / ".config" / "autostart"
        directory.mkdir(parents=True)
        self._symlink(directory / "a.desktop", outside)
        self.assertFalse(au.set_enabled("A", "/a", [], True, "linux", self.home))
        self.assertFalse(au.set_enabled("A", "/a", [], False, "linux", self.home))
        self.assertEqual(outside.read_text(encoding="utf-8"), "dokunma")
        self.assertTrue((directory / "a.desktop").is_symlink())
        self.assertFalse(au.is_enabled("A", "linux", self.home))

    def test_symlinked_directory_is_refused_even_if_it_points_outside_home(self) -> None:
        outside = Path(self._tmp.name) / "outside_dir"
        outside.mkdir()
        (self.home / ".config").mkdir()
        self._symlink(self.home / ".config" / "autostart", outside)
        self.assertFalse(au.set_enabled("A", "/a", [], True, "linux", self.home))
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_parent_is_refused(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        self._symlink(self.home / "Library", outside)
        self.assertFalse(au.set_enabled("A", "/a", [], True, "darwin", self.home))
        self.assertEqual(list(outside.iterdir()), [])

    def test_directory_in_place_of_file_is_refused(self) -> None:
        (self.home / ".config" / "autostart" / "a.desktop").mkdir(parents=True)
        self.assertFalse(au.set_enabled("A", "/a", [], True, "linux", self.home))
        self.assertFalse(au.set_enabled("A", "/a", [], False, "linux", self.home))

    def test_unwritable_location_returns_false_without_raising(self) -> None:
        with mock.patch.object(au.tempfile, "mkstemp", side_effect=PermissionError("yok")):
            self.assertFalse(au.set_enabled("A", "/a", [], True, "linux", self.home))
        self.assertEqual(self.files(), [])

    def test_invalid_app_name_returns_false(self) -> None:
        self.assertFalse(au.set_enabled("///", "/a", [], True, "linux", self.home))
        self.assertFalse(au.is_enabled("///", "linux", self.home))

    def test_default_home_is_the_real_home_only_when_not_injected(self) -> None:
        with mock.patch.object(au.os.path, "expanduser", return_value=str(self.home)), \
                mock.patch.dict(au.os.environ, {"XDG_CONFIG_HOME": ""}):
            self.assertTrue(au.set_enabled("A", "/a", [], True, "linux"))
        self.assertTrue(au.desktop_path("A", self.home).is_file())


class XdgConfigHomeTests(_Home):
    """Linux: $XDG_CONFIG_HOME (ya da açık `config_home`) ~/.config'in yerini tutar; yalnızca GERÇEK home'da."""

    def setUp(self) -> None:
        super().setUp()
        self.xdg = Path(self._tmp.name) / "xdg-config"
        self.env = {"XDG_CONFIG_HOME": str(self.xdg)}

    def test_explicit_config_home_replaces_dot_config_and_is_created(self) -> None:
        self.assertFalse(self.xdg.exists())
        self.assertTrue(au.set_enabled("A", "/a", ["--minimized"], True, "linux", self.home, config_home=self.xdg))
        target = self.xdg / "autostart" / "a.desktop"
        self.assertEqual(au.desktop_path("A", self.home, config_home=self.xdg), target)
        self.assertIn("Exec=/a --minimized\n", target.read_text(encoding="utf-8"))
        self.assertEqual(self.files(), [], "home altına bir şey yazılmamalı")
        self.assertTrue(au.is_enabled("A", "linux", self.home, config_home=self.xdg))
        self.assertFalse(au.is_enabled("A", "linux", self.home), "varsayılan konumda kayıt yok")
        self.assertTrue(au.set_enabled("A", "/a", [], False, "linux", self.home, config_home=self.xdg))
        self.assertFalse(target.exists())

    def test_environment_variable_applies_only_to_the_real_home(self) -> None:
        with mock.patch.object(au.os.path, "expanduser", return_value=str(self.home)):
            self.assertEqual(au.desktop_path("A", env=self.env), self.xdg / "autostart" / "a.desktop")
            self.assertTrue(au.set_enabled("A", "/a", [], True, "linux", env=self.env))
            self.assertTrue(au.is_enabled("A", "linux", env=self.env))
        self.assertTrue((self.xdg / "autostart" / "a.desktop").is_file())
        self.assertEqual(self.files(), [])

    def test_injected_home_never_escapes_to_the_environment(self) -> None:
        expected = self.home / ".config" / "autostart" / "a.desktop"
        self.assertEqual(au.desktop_path("A", self.home, env=self.env), expected)
        self.assertTrue(au.set_enabled("A", "/a", [], True, "linux", self.home, env=self.env))
        self.assertTrue(expected.is_file())
        self.assertFalse(self.xdg.exists())
        # testlerde `_home` değiştirilerek de aynı güvence: ortamdaki XDG'ye yazılmaz
        with mock.patch.object(au, "_home", lambda home=None: self.home):
            self.assertEqual(au.desktop_path("B", env=self.env), self.home / ".config" / "autostart" / "b.desktop")

    def test_relative_or_empty_xdg_value_is_ignored(self) -> None:
        with mock.patch.object(au.os.path, "expanduser", return_value=str(self.home)):
            for value in ("goreli/yol", "", "   "):
                with self.subTest(value=value):
                    self.assertEqual(au.desktop_path("A", env={"XDG_CONFIG_HOME": value}),
                                     self.home / ".config" / "autostart" / "a.desktop")

    def test_macos_ignores_xdg(self) -> None:
        self.assertTrue(au.set_enabled("A", "/a", [], True, "darwin", self.home, config_home=self.xdg, env=self.env))
        self.assertEqual(self.files(), ["Library/LaunchAgents/com.macik.a.plist"])
        self.assertFalse(self.xdg.exists())

    def test_xdg_root_that_is_a_file_fails_cleanly(self) -> None:
        self.xdg.write_text("dosya", encoding="utf-8")
        self.assertFalse(au.set_enabled("A", "/a", [], True, "linux", self.home, config_home=self.xdg))
        self.assertEqual(self.xdg.read_text(encoding="utf-8"), "dosya")


class IsCurrentTests(_Home):
    """`is_current`: kayıt, `set_enabled`'ın şimdi yazacağı içerikle birebir mi? (taşınma/bayrak/eski ad artığı)"""

    def test_linux_states(self) -> None:
        kw = dict(platform="linux", home=self.home)
        self.assertFalse(au.is_current("A", "/a", ["--minimized"], **kw), "kayıt yok")
        au.set_enabled("A", "/a", ["--minimized"], True, "linux", self.home)
        self.assertTrue(au.is_current("A", "/a", ["--minimized"], **kw))
        self.assertFalse(au.is_current("A", "/b", ["--minimized"], **kw), "program taşındı")
        self.assertFalse(au.is_current("A", "/a", [], **kw), "bayrak değişti")
        self.assertFalse(au.is_current("A", "/a", ["--minimized"], platform="win32", home=self.home))

    def test_hand_edited_or_replaced_file_is_not_current(self) -> None:
        au.set_enabled("A", "/a", [], True, "linux", self.home)
        path = au.desktop_path("A", self.home)
        path.write_text(path.read_text(encoding="utf-8") + "Hidden=true\n", encoding="utf-8")
        self.assertFalse(au.is_current("A", "/a", [], "linux", self.home))
        path.unlink()
        path.mkdir()
        self.assertFalse(au.is_current("A", "/a", [], "linux", self.home))

    def test_macos_legacy_leftover_makes_it_stale(self) -> None:
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        legacy = agents / "tr.com.macik.a.plist"
        legacy.write_bytes(plistlib.dumps({"Label": "tr.com.macik.a", "ProgramArguments": ["/a"], "RunAtLoad": True}))
        kw = dict(platform="darwin", home=self.home, legacy_plist_labels=("tr.com.macik.a",))
        self.assertFalse(au.is_current("A", "/a", [], **kw), "yalnızca eski adlı dosya var")
        self.assertTrue(au.is_enabled("A", "darwin", self.home, legacy_plist_labels=("tr.com.macik.a",)))
        self.assertTrue(au.set_enabled("A", "/a", [], True, "darwin", self.home, legacy_plist_labels=("tr.com.macik.a",)))
        self.assertTrue(au.is_current("A", "/a", [], **kw))
        legacy.write_bytes(b"x")  # eski artık geri gelirse yeniden yenilenmeli
        self.assertFalse(au.is_current("A", "/a", [], **kw))


if __name__ == "__main__":
    unittest.main()
