"""Madde 4: kullanici dizinleri, indirme klasoru varsayilani ve alinan dosya adi/yolu temizleme.

* Dizinler `platform=/env=/home=` enjekte edilerek her uc isletim sistemi icin sinanir.
* Dosya adi kurallari saf fonksiyonlarla (Windows/Linux/macOS) ve GERCEK dosya sistemiyle
  (calisilan platform: Windows bu makinede, Linux WSL'de) sinanir.
"""

import json
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import Loopback, RawPeer, fresh_dir, make_bytes, read_file  # noqa: E402

from src.utils import filenames, paths  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
POSIX = os.name == "posix"


class UserDirsTest(unittest.TestCase):
    HOME = os.path.join(os.sep, "home", "ali") if POSIX else "C:\\Users\\ali"

    def test_windows_dirs_use_appdata_and_localappdata(self) -> None:
        env = {"APPDATA": "R:\\Roaming", "LOCALAPPDATA": "R:\\Local"}
        self.assertEqual(paths.get_user_config_dir(platform="win32", env=env), os.path.join("R:\\Roaming", "TransferTCP"))
        self.assertEqual(paths.get_user_data_dir(platform="win32", env=env), os.path.join("R:\\Local", "TransferTCP"))
        self.assertEqual(paths.get_user_log_dir(platform="win32", env=env),
                         os.path.join("R:\\Local", "TransferTCP", "logs"), "Windows log yolu degismemeli")

    def test_windows_falls_back_to_profile_appdata_folders(self) -> None:
        got = paths.get_user_config_dir(platform="win32", env={}, home=self.HOME)
        self.assertEqual(got, os.path.join(self.HOME, "AppData", "Roaming", "TransferTCP"))
        got = paths.get_user_data_dir(platform="win32", env={}, home=self.HOME)
        self.assertEqual(got, os.path.join(self.HOME, "AppData", "Local", "TransferTCP"))

    def test_macos_uses_application_support_and_library_logs(self) -> None:
        for fn in (paths.get_user_config_dir, paths.get_user_data_dir):
            self.assertEqual(fn(platform="darwin", env={}, home=self.HOME),
                             os.path.join(self.HOME, "Library", "Application Support", "TransferTCP"))
        self.assertEqual(paths.get_user_log_dir(platform="darwin", env={}, home=self.HOME),
                         os.path.join(self.HOME, "Library", "Logs", "TransferTCP"))

    def test_linux_honours_absolute_xdg_variables(self) -> None:
        xdg = os.path.join(os.sep, "x") if POSIX else "C:\\x"
        env = {"XDG_CONFIG_HOME": os.path.join(xdg, "c"), "XDG_DATA_HOME": os.path.join(xdg, "d"),
               "XDG_STATE_HOME": os.path.join(xdg, "s")}
        self.assertEqual(paths.get_user_config_dir(platform="linux", env=env, home=self.HOME),
                         os.path.join(xdg, "c", "TransferTCP"))
        self.assertEqual(paths.get_user_data_dir(platform="linux", env=env, home=self.HOME),
                         os.path.join(xdg, "d", "TransferTCP"))
        self.assertEqual(paths.get_user_log_dir(platform="linux", env=env, home=self.HOME),
                         os.path.join(xdg, "s", "TransferTCP", "logs"))

    def test_linux_defaults_when_xdg_unset_empty_or_relative(self) -> None:
        for env in ({}, {"XDG_CONFIG_HOME": "", "XDG_DATA_HOME": " ", "XDG_STATE_HOME": "rel/path"},
                    {"XDG_CONFIG_HOME": "relative", "XDG_DATA_HOME": "relative", "XDG_STATE_HOME": "relative"}):
            with self.subTest(env=env):
                self.assertEqual(paths.get_user_config_dir(platform="linux", env=env, home=self.HOME),
                                 os.path.join(self.HOME, ".config", "TransferTCP"))
                self.assertEqual(paths.get_user_data_dir(platform="linux", env=env, home=self.HOME),
                                 os.path.join(self.HOME, ".local", "share", "TransferTCP"))
                self.assertEqual(paths.get_user_log_dir(platform="linux", env=env, home=self.HOME),
                                 os.path.join(self.HOME, ".local", "state", "TransferTCP", "logs"))

    def test_real_platform_dirs_live_in_the_test_sandbox(self) -> None:
        for fn in (paths.get_user_config_dir, paths.get_user_data_dir, paths.get_user_log_dir):
            self.assertTrue(fn().startswith(support.SANDBOX_ROOT), fn.__name__)

    def test_logger_writes_to_the_platform_log_dir(self) -> None:
        from src.utils.logger import get_logger
        logger = get_logger()
        self.assertEqual(os.path.normcase(logger.log_dir), os.path.normcase(paths.get_user_log_dir()))
        self.assertTrue(os.path.isdir(logger.log_dir))

    def test_config_dir_is_private_on_posix(self) -> None:
        folder = fresh_dir("cfgdir")
        target = os.path.join(folder, "TransferTCP")
        with mock.patch.object(paths, "get_user_config_dir", return_value=target):
            user_path, _seed = paths.resolve_user_config("x.json")
        self.assertEqual(os.path.dirname(user_path), target)
        if POSIX:
            import stat
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o700)


class DownloadFolderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = fresh_dir("home")
        self.env = {}

    def test_qt_download_location_wins_when_it_exists(self) -> None:
        wanted = os.path.join(fresh_dir("dl"), "Indirilenler")
        os.makedirs(wanted)
        got = paths.get_default_download_dir(platform="linux", env=self.env, home=self.home,
                                             qt_lookup=lambda: wanted)
        self.assertEqual(got, wanted)

    def test_qt_location_is_used_when_only_its_parent_exists(self) -> None:
        parent = fresh_dir("dl")
        wanted = os.path.join(parent, "Downloads")
        got = paths.get_default_download_dir(platform="linux", env=self.env, home=self.home,
                                             qt_lookup=lambda: wanted)
        self.assertEqual(got, wanted)

    def test_falls_back_to_home_downloads(self) -> None:
        for lookup in (lambda: None, lambda: "", lambda: "relative/Downloads", mock.Mock(side_effect=RuntimeError)):
            with self.subTest(lookup=lookup):
                got = paths.get_default_download_dir(platform="linux", env=self.env, home=self.home, qt_lookup=lookup)
                self.assertEqual(got, os.path.join(self.home, "Downloads"))

    def test_last_resort_is_data_dir_downloads(self) -> None:
        ghost_home = os.path.join(self.home, "yok", "yok2")
        env = {"XDG_DATA_HOME": os.path.join(self.home, "data")}
        got = paths.get_default_download_dir(platform="linux", env=env, home=ghost_home, qt_lookup=lambda: None)
        self.assertEqual(got, os.path.join(self.home, "data", "TransferTCP", "downloads"))

    def test_real_qt_lookup_returns_an_absolute_path(self) -> None:
        got = paths.get_default_download_dir()
        self.assertTrue(os.path.isabs(got))

    def test_get_download_folder_resolution(self) -> None:
        default = os.path.join(self.home, "Downloads")
        for empty in ("", "   ", None):
            self.assertEqual(paths.get_download_folder(empty, platform="linux", env=self.env, home=self.home,
                                                       qt_lookup=lambda: None), default)
        absolute = os.path.join(fresh_dir("abs"), "Gelenler")
        self.assertEqual(paths.get_download_folder(absolute, home=self.home), absolute)  # mutlak: AYNEN
        self.assertEqual(paths.get_download_folder("sub/dir", home=self.home), os.path.join(self.home, "sub/dir"))
        with mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home}):
            self.assertEqual(os.path.normpath(paths.get_download_folder("~/Gelen")),
                             os.path.normpath(os.path.join(self.home, "Gelen")))

    def test_empty_config_value_receives_into_the_default_folder_not_cwd(self) -> None:
        lb = Loopback().start()
        self.addCleanup(lb.stop)
        wanted = fresh_dir("recv_default")
        lb.config.config["transfer"]["download_folder"] = ""
        with mock.patch("src.core.server.get_download_folder",
                        side_effect=lambda v: wanted if not v else v) as resolver:
            peer = RawPeer(lb.server.port)
            self.addCleanup(peer.close)
            peer.handshake()
            payload = b"x" * 100
            peer.file_info("t-empty-cfg", "f.txt", len(payload))
            peer.chunk("t-empty-cfg", 0, 1, payload)
            peer.complete("t-empty-cfg")
            self.assertTrue(lb.wait_recv("t-empty-cfg"))
            lb.settle()
        resolver.assert_called()
        self.assertTrue(os.path.isfile(os.path.join(wanted, "f.txt")))


class SanitizeComponentTest(unittest.TestCase):
    def test_windows_reserved_device_names_are_prefixed(self) -> None:
        for name in ("CON", "con", "Con.txt", "PRN.tar.gz", "AUX", "NUL", "nul.txt", "COM1", "com9.log",
                     "LPT1", "lpt9.dat", "CONIN$", "CONOUT$", "COM\u00b9", "NUL.", "com1 .txt"):
            with self.subTest(name=name):
                result = filenames.sanitize_component(name, "win32")
                self.assertTrue(result.startswith("_"), f"{name!r} -> {result!r}")

    def test_windows_lookalikes_are_not_reserved(self) -> None:
        for name in ("CONSOLE.txt", "COM10", "com0", "NULL", "LPT0", "acon", "my.con", "aux1", "COM"):
            with self.subTest(name=name):
                self.assertEqual(filenames.sanitize_component(name, "win32"), name)

    def test_windows_invalid_characters_and_trailing_dots_spaces(self) -> None:
        cases = {
            "a:b.txt": "a_b.txt", 'q"x<y>z|w?v*u.txt': "q_x_y_z_w_v_u.txt", "report. ": "report",
            "trailing...": "trailing", "  spaced name  ": "spaced name", "tab\tname.txt": "tab_name.txt",
            "esc\x1b[31m.txt": "esc_[31m.txt", "x\x00y": "x_y", "...": "_", " ": "_", "": "_",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(filenames.sanitize_component(raw, "win32"), expected)

    def test_linux_keeps_names_windows_would_reject_but_removes_nul_and_controls(self) -> None:
        self.assertEqual(filenames.sanitize_component("a:b?c*.txt", "linux"), "a:b?c*.txt")
        self.assertEqual(filenames.sanitize_component("CON", "linux"), "CON")
        self.assertEqual(filenames.sanitize_component(".hidden", "linux"), ".hidden")
        self.assertEqual(filenames.sanitize_component("trail.", "linux"), "trail.")
        self.assertEqual(filenames.sanitize_component("a\x00b", "linux"), "a_b")
        self.assertEqual(filenames.sanitize_component("a\nb", "linux"), "a_b")
        self.assertEqual(filenames.sanitize_component("a/b", "linux"), "a_b")
        self.assertEqual(filenames.sanitize_component("a\\b", "linux"), "a_b")

    def test_macos_replaces_colon(self) -> None:
        self.assertEqual(filenames.sanitize_component("12:30 notlar.txt", "darwin"), "12_30 notlar.txt")
        self.assertEqual(filenames.sanitize_component("CON", "darwin"), "CON")

    def test_dot_names_become_underscore_everywhere(self) -> None:
        for platform in ("win32", "linux", "darwin"):
            for name in (".", "..", "", "   "):
                self.assertEqual(filenames.sanitize_component(name, platform), "_")

    def test_bidi_overrides_and_lone_surrogates_are_neutralised(self) -> None:
        spoof = "evil\u202Efdp.exe"
        for platform in ("win32", "linux", "darwin"):
            result = filenames.sanitize_component(spoof, platform)
            self.assertNotIn("\u202e", result)
            lone = filenames.sanitize_component("a\ud800b", platform)
            lone.encode("utf-8")  # UnicodeEncodeError firlatmamali
            self.assertEqual(lone, "a_b" if platform == "win32" else "a?b")  # '?' Windows'ta gecersiz

    def test_non_string_input_is_safe(self) -> None:
        for value in (None, 12, b"x", ["a"]):
            self.assertEqual(filenames.sanitize_component(value, "linux"), "_")

    def test_long_names_keep_extension_and_stay_under_byte_limit(self) -> None:
        for platform in ("win32", "linux", "darwin"):
            long = filenames.sanitize_component("a" * 400 + ".txt", platform)
            self.assertLessEqual(len(long.encode("utf-8")), filenames.MAX_COMPONENT_BYTES)
            self.assertTrue(long.endswith(".txt"))
            cjk = filenames.sanitize_component("\u6f22" * 200 + ".pdf", platform)   # 3 bayt/karakter
            self.assertLessEqual(len(cjk.encode("utf-8")), filenames.MAX_COMPONENT_BYTES)
            self.assertTrue(cjk.endswith(".pdf"))
            cjk.encode("utf-8").decode("utf-8")  # karakter ortasindan kesilmemis
            giant_ext = filenames.sanitize_component("name." + "b" * 300, platform)
            self.assertLessEqual(len(giant_ext.encode("utf-8")), filenames.MAX_COMPONENT_BYTES)

    def test_part_meta_and_collision_suffixes_still_fit_255_bytes(self) -> None:
        name = filenames.sanitize_component("x" * 1000 + ".bin", "linux")
        self.assertLessEqual(len((name + ".part.meta").encode("utf-8")), 255)
        self.assertLessEqual(len((name[:-4] + " (9999)" + ".bin" + ".part.meta").encode("utf-8")), 255)

    def test_idempotent_and_never_unsafe_for_random_input(self) -> None:
        rng = random.Random(4242)
        alphabet = ["a", "Z", "0", ".", " ", ":", "/", "\\", "\x00", "\x1f", "\u202e", "\u6f22", "\ud800",
                    "*", "?", "<", "|", '"', "\u00e9", "e\u0301"]
        for _ in range(400):
            raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            for platform in ("win32", "linux", "darwin"):
                once = filenames.sanitize_component(raw, platform)
                self.assertEqual(filenames.sanitize_component(once, platform), once, (platform, raw))
                self.assertNotIn(once, ("", ".", ".."))
                self.assertFalse(set(once) & set("/\\\x00"))
                self.assertLessEqual(len(once.encode("utf-8")), filenames.MAX_COMPONENT_BYTES)
                if platform == "win32":
                    self.assertFalse(set(once) & set('<>:"|?*'), (raw, once))
                    self.assertFalse(once.endswith((" ", ".")), (raw, once))


class ResolveTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = os.path.join(fresh_dir("dl"), "Gelen")
        os.makedirs(self.base)

    def _inside(self, target: str) -> bool:
        return os.path.commonpath([os.path.realpath(self.base), os.path.realpath(os.path.dirname(target))]) \
            == os.path.realpath(self.base)

    def test_hostile_paths_never_escape_the_download_folder(self) -> None:
        hostile = [
            ("../../evil.txt", "x.txt"), ("..\\..\\evil.txt", "x.txt"), ("/etc/passwd", "x.txt"),
            ("\\\\server\\share\\evil.txt", "x.txt"), ("C:/Windows/System32/evil.dll", "x.txt"),
            ("C:\\Windows\\evil.dll", "x.txt"), ("a/../../b/evil.txt", "x.txt"), ("a/./b/../c.txt", "x.txt"),
            ("//host/x", "x.txt"), ("a\x00/../../evil", "x.txt"), (None, "../../evil2.txt"),
            (None, "..\\..\\evil3.txt"), (None, "/abs/evil4.txt"), (None, "C:\\evil5.txt"),
            ("~/evil.txt", "x.txt"), ("....//....//evil.txt", "x.txt"), ("a/" + "../" * 20 + "evil.txt", "x.txt"),
        ]
        for platform in ("win32", "linux", "darwin"):
            for relative, name in hostile:
                with self.subTest(platform=platform, relative=relative, name=name):
                    target = filenames.resolve_target(self.base, relative, name, platform)
                    self.assertTrue(self._inside(target), f"{target} disariya cikti")
                    self.assertTrue(os.path.abspath(target).startswith(os.path.abspath(self.base) + os.sep))

    def test_normal_folder_structure_is_preserved(self) -> None:
        target = filenames.resolve_target(self.base, "Tatil/2024/img 01.jpg", "img 01.jpg", "linux")
        self.assertEqual(target, os.path.join(os.path.abspath(self.base), "Tatil", "2024", "img 01.jpg"))
        flat = filenames.resolve_target(self.base, None, "rapor.pdf", "linux")
        self.assertEqual(flat, os.path.join(os.path.abspath(self.base), "rapor.pdf"))
        backslash_sender = filenames.resolve_target(self.base, "Klasor\\alt\\a.txt", "a.txt", "linux")
        self.assertEqual(backslash_sender, os.path.join(os.path.abspath(self.base), "Klasor", "alt", "a.txt"))

    def test_platform_rules_apply_per_path_component(self) -> None:
        win = filenames.resolve_target(self.base, "CON/aux.txt/ok.txt", "ok.txt", "win32")
        self.assertEqual(os.path.relpath(win, self.base).split(os.sep), ["_CON", "_aux.txt", "ok.txt"])
        mac = filenames.resolve_target(self.base, "a:b/c.txt", "c.txt", "darwin")
        self.assertEqual(os.path.relpath(mac, self.base).split(os.sep), ["a_b", "c.txt"])
        if POSIX:  # Windows ana makinede "a:b" surucu belirtimi sayilir; Linux kurali yalnizca POSIX'te anlamli
            linux = filenames.resolve_target(self.base, "a:b/c.txt", "c.txt", "linux")
            self.assertEqual(os.path.relpath(linux, self.base).split(os.sep), ["a:b", "c.txt"])

    def test_empty_or_garbage_filename_gets_a_default_name(self) -> None:
        for name in ("", "   ", None, "/", "\\"):
            target = filenames.resolve_target(self.base, None, name, "linux")
            self.assertEqual(os.path.dirname(target), os.path.abspath(self.base))
            self.assertEqual(os.path.basename(target), filenames.DEFAULT_FILENAME)

    def test_filename_with_directories_keeps_only_the_base_name(self) -> None:
        target = filenames.resolve_target(self.base, None, "..\\..\\evil1.txt", "linux")
        self.assertEqual(os.path.basename(target), "evil1.txt")
        self.assertEqual(os.path.dirname(target), os.path.abspath(self.base))

    @unittest.skipUnless(POSIX, "sembolik bag olusturma POSIX'te serbest")
    def test_symlink_escape_falls_back_to_the_safe_path_and_reports(self) -> None:
        outside = fresh_dir("outside")
        os.symlink(outside, os.path.join(self.base, "link"))
        reasons = []
        target = filenames.resolve_target(self.base, "link/evil.txt", "evil.txt", "linux", reasons.append)
        self.assertEqual(target, os.path.join(os.path.abspath(self.base), "evil.txt"))
        self.assertEqual(len(reasons), 1)
        self.assertIn("sembolik", reasons[0])

    @unittest.skipUnless(POSIX, "sembolik bag olusturma POSIX'te serbest")
    def test_download_folder_itself_may_be_a_symlink(self) -> None:
        real = fresh_dir("realdl")
        link = os.path.join(fresh_dir("linkdl"), "Downloads")
        os.symlink(real, link)
        target = filenames.resolve_target(link, "Alt/a.txt", "a.txt", "linux")
        self.assertEqual(target, os.path.join(os.path.abspath(link), "Alt", "a.txt"))

    def test_fallback_callback_for_dotdot_free_paths_is_not_called(self) -> None:
        reasons = []
        filenames.resolve_target(self.base, "a/b/c.txt", "c.txt", "linux", reasons.append)
        self.assertEqual(reasons, [])


class FsKeyTest(unittest.TestCase):
    def test_windows_keys_ignore_case_and_slashes(self) -> None:
        self.assertEqual(filenames.fs_key("C:\\Dl\\File.TXT.part", "win32"), filenames.fs_key("c:/dl/file.txt.part", "win32"))

    def test_macos_keys_ignore_case_and_unicode_normalisation(self) -> None:
        nfc = "/Users/a/Dl/\u00c9t\u00e9.txt.part"
        nfd = "/Users/a/Dl/E\u0301te\u0301.TXT.PART"
        self.assertEqual(filenames.fs_key(nfc, "darwin"), filenames.fs_key(nfd, "darwin"))

    def test_linux_keys_are_case_sensitive(self) -> None:
        self.assertNotEqual(filenames.fs_key("/dl/A.part", "linux"), filenames.fs_key("/dl/a.part", "linux"))

    def test_real_platform_key_is_used_by_the_server_claims(self) -> None:
        from src.core.server import TCPServer
        from src.core.transfer import TransferManager
        server = TCPServer(TransferManager())
        sock = mock.Mock()
        error, entry = server._claim_part("/tmp/x/File.part" if POSIX else "C:\\x\\File.part", sock, "s", "t")
        self.assertIsNone(error)
        self.assertIn(filenames.fs_key("/tmp/x/File.part" if POSIX else "C:\\x\\File.part"), server._receivers)


class ReceiveRealFilesystemTest(unittest.TestCase):
    """GERCEK dosya sistemi (Windows: bu makine, Linux: WSL ext4): sanitize edilmis adlar diske yazilabilmeli."""

    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=16384).start()
        self.addCleanup(self.lb.stop)
        self._n = 0

    def _receive(self, filename, relative_path=None, payload=None):
        self._n += 1
        tid = f"t-fs-{self._n}"
        payload = payload if payload is not None else make_bytes(3000, seed=self._n)
        peer = RawPeer(self.lb.server.port)
        self.addCleanup(peer.close)
        peer.handshake()
        msg_type, ack = peer.file_info(tid, filename, len(payload), relative_path=relative_path)
        self.assertEqual(msg_type, peer.MessageType.FILE_INFO_ACK, ack)
        peer.chunk(tid, 0, 1, payload)
        peer.complete(tid)
        self.assertTrue(self.lb.wait_recv(tid))
        self.lb.settle()
        transfer = self.lb.recv_transfer(tid)
        self.assertEqual(transfer.status.value, "completed", transfer.error_message)
        self.assertEqual(read_file(transfer.filepath), payload)
        return transfer.filepath

    def test_windows_reserved_name_is_stored_under_a_safe_name_on_windows_only(self) -> None:
        stored = self._receive("con.txt")
        expected = "_con.txt" if IS_WINDOWS else "con.txt"
        self.assertEqual(os.path.basename(stored), expected)

    def test_colon_name_from_a_linux_sender(self) -> None:
        stored = self._receive("rapor 12:30.txt")
        expected = "rapor 12_30.txt" if IS_WINDOWS else "rapor 12:30.txt"
        self.assertEqual(os.path.basename(stored), expected)

    def test_nul_and_control_characters_are_replaced(self) -> None:
        stored = self._receive("a\x00b\x1fc.txt")
        self.assertEqual(os.path.basename(stored), "a_b_c.txt")

    def test_overlong_name_is_shortened_and_written(self) -> None:
        stored = self._receive("u" * 700 + ".dat")
        self.assertLessEqual(len(os.path.basename(stored).encode("utf-8")), filenames.MAX_COMPONENT_BYTES)
        self.assertTrue(stored.endswith(".dat"))

    def test_folder_transfer_creates_nested_directories_inside_downloads(self) -> None:
        stored = self._receive("deep.txt", relative_path="Proje/src/alt/deep.txt")
        expected = os.path.join(os.path.abspath(self.lb.download_dir), "Proje", "src", "alt", "deep.txt")
        self.assertEqual(os.path.abspath(stored), expected)

    def test_case_colliding_names_never_overwrite_each_other(self) -> None:
        self.lb.server.config.set('transfer', 'overwrite_existing', False)
        self.addCleanup(self.lb.server.config.set, 'transfer', 'overwrite_existing', True)
        first = self._receive("Case.txt", payload=b"BIRINCI" * 50)
        second = self._receive("case.txt", payload=b"IKINCI" * 50)
        self.assertEqual(read_file(first), b"BIRINCI" * 50)
        self.assertEqual(read_file(second), b"IKINCI" * 50)
        self.assertNotEqual(os.path.normcase(first) if IS_WINDOWS else first,
                            os.path.normcase(second) if IS_WINDOWS else second)
        if IS_WINDOWS:   # buyuk/kucuk harf duyarsiz disk: ikinci ad "(1)" ile benzersizlesir
            self.assertEqual(os.path.basename(second), "case (1).txt")
        else:
            self.assertEqual(os.path.basename(second), "case.txt")

    def test_hostile_relative_path_stays_inside_on_the_real_filesystem(self) -> None:
        stored = self._receive("x.txt", relative_path="../../../escape/evil.txt")
        root = os.path.realpath(self.lb.download_dir)
        self.assertTrue(os.path.realpath(stored).startswith(root + os.sep), stored)
        outside = os.path.join(os.path.dirname(root), "escape")
        self.assertFalse(os.path.exists(outside))

    def test_unicode_names_roundtrip(self) -> None:
        stored = self._receive("T\u00fcrk\u00e7e \u00e7\u0131\u011f\u0131\u015f \U0001F600 \u6f22\u5b57.txt")
        self.assertEqual(os.path.basename(stored), "T\u00fcrk\u00e7e \u00e7\u0131\u011f\u0131\u015f \U0001F600 \u6f22\u5b57.txt")

    def test_scan_folder_wire_paths_use_forward_slashes(self) -> None:
        from src.utils.helpers import scan_folder
        root = fresh_dir("scan")
        os.makedirs(os.path.join(root, "a", "b"))
        for rel in ("a/b/c.txt", "top.txt"):
            with open(os.path.join(root, *rel.split("/")), "wb") as handle:
                handle.write(b"1")
        rels = sorted(rel for _full, rel in scan_folder(root))
        self.assertEqual(rels, ["a/b/c.txt", "top.txt"])

    def test_scan_folder_skips_os_metadata_files(self) -> None:
        from src.utils.helpers import scan_folder, get_folder_size
        root = fresh_dir("scanmeta")
        for name, data in (("desktop.ini", b"[x]"), ("Thumbs.db", b"x"), (".DS_Store", b"x"), ("gercek.txt", b"12")):
            with open(os.path.join(root, name), "wb") as handle:
                handle.write(data)
        self.assertEqual([rel for _full, rel in scan_folder(root)], ["gercek.txt"])
        self.assertEqual(get_folder_size(root), 2)

    @unittest.skipUnless(POSIX, "'\\' yalnizca POSIX'te gecerli dosya adi karakteri")
    def test_backslash_in_a_posix_file_name_is_not_turned_into_a_directory(self) -> None:
        from src.utils.helpers import scan_folder
        root = fresh_dir("scanbs")
        with open(os.path.join(root, "a\\b.txt"), "wb") as handle:
            handle.write(b"1")
        self.assertEqual([rel for _full, rel in scan_folder(root)], ["a\\b.txt"])


if __name__ == "__main__":
    unittest.main()
