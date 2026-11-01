"""Madde 3: kimlik/anahtar dosyalarinin izinleri (POSIX 0700/0600), atomik yazim, donanim kimligi.

Windows'ta (bu makine) izin islemleri no-op olmali ve davranis degismemeli; Linux'ta gercek dosya
sistemiyle (WSL) dogrulanir. macOS yalnizca `platform=` enjekte edilerek sinanir.
Tum veri `support` kum havuzundaki gecici dizine yazilir; gercek kullanici dizinine dokunulmaz.
"""

import hashlib
import os
import stat
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import fresh_dir  # noqa: E402

import src.core.crypto as crypto  # noqa: E402
from src.utils import fileio  # noqa: E402

POSIX = os.name == "posix"
posix_only = unittest.skipUnless(POSIX, "POSIX izin bitleri")


def mode_of(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class IdentityFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("cryptography kurulu degil")
        self.dir = fresh_dir("ident")
        self.cert = os.path.join(self.dir, "identity.crt")
        self.key = os.path.join(self.dir, "identity.key")
        self.old_umask = None

    def tearDown(self) -> None:
        if self.old_umask is not None:
            os.umask(self.old_umask)
        crypto._cached_paths = None

    @posix_only
    def test_private_key_is_0600_and_cert_not_writable_by_others(self) -> None:
        crypto._generate_identity(self.cert, self.key)
        self.assertEqual(mode_of(self.key), 0o600)
        self.assertEqual(mode_of(self.cert) & 0o022, 0)
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    @posix_only
    def test_key_is_0600_even_with_a_permissive_umask(self) -> None:
        self.old_umask = os.umask(0)  # tum izinler acik
        crypto._generate_identity(self.cert, self.key)
        self.assertEqual(mode_of(self.key), 0o600)

    @posix_only
    def test_key_never_exists_with_loose_permissions(self) -> None:
        """Anahtar baştan 0600 ile yaratilir (eskiden 0644 yazilip sonra chmod ediliyordu)."""
        seen = []
        real_replace = os.replace

        def spying_replace(src, dst):
            if dst == self.key:
                seen.append(mode_of(src))
            return real_replace(src, dst)

        self.old_umask = os.umask(0)
        with mock.patch("src.utils.fileio.os.replace", spying_replace):
            crypto._generate_identity(self.cert, self.key)
        self.assertEqual(seen, [0o600])

    @posix_only
    def test_existing_loose_key_and_dir_are_tightened(self) -> None:
        crypto._generate_identity(self.cert, self.key)
        os.chmod(self.key, 0o644)
        with mock.patch.object(crypto, "get_identity_paths", return_value=(self.cert, self.key)):
            crypto._cached_paths = None
            crypto.ensure_identity()
        self.assertEqual(mode_of(self.key), 0o600)

    @posix_only
    def test_cert_dir_is_private_in_the_sandboxed_data_dir(self) -> None:
        path = crypto._cert_dir()
        self.assertTrue(path.startswith(support.SANDBOX_ROOT))
        self.assertEqual(mode_of(path), 0o700)
        os.chmod(path, 0o755)
        crypto._cert_dir()
        self.assertEqual(mode_of(path), 0o700, "gevsek dizin izni sonraki acilista duzeltilmedi")

    @posix_only
    def test_trust_store_is_written_0600_and_data_dir_private(self) -> None:
        crypto.trust_device("ab" * 32, "Perm", "10.0.0.9")
        self.addCleanup(crypto.clear_trusted_devices)
        self.assertEqual(mode_of(crypto._trust_path()), 0o600)
        self.assertEqual(mode_of(os.path.dirname(crypto._trust_path())), 0o700)

    def test_failed_write_keeps_previous_key_and_leaves_no_tmp(self) -> None:
        crypto._generate_identity(self.cert, self.key)
        with open(self.key, "rb") as handle:
            before = handle.read()
        with mock.patch("src.utils.fileio.os.replace", side_effect=OSError("kilitli")):
            with self.assertRaises(OSError):
                crypto._generate_identity(self.cert, self.key)
        with open(self.key, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_generated_identity_is_usable_for_tls_contexts(self) -> None:
        crypto._generate_identity(self.cert, self.key)
        with mock.patch.object(crypto, "get_identity_paths", return_value=(self.cert, self.key)):
            crypto._cached_paths = None
            ctx = crypto._make_context(server_side=True)
        self.assertIsNotNone(ctx)


class PermissionHelpersTest(unittest.TestCase):
    def test_windows_branch_never_calls_chmod(self) -> None:
        path = os.path.join(fresh_dir("perm"), "x")
        with open(path, "w") as handle:
            handle.write("x")
        with mock.patch("src.utils.fileio.os.chmod") as chmod:
            self.assertTrue(fileio.restrict_permissions(path, 0o600, platform="win32"))
            self.assertTrue(fileio.ensure_private_dir(os.path.join(os.path.dirname(path), "d"), platform="win32"))
        chmod.assert_not_called()

    @posix_only
    def test_chmod_failure_is_reported_not_swallowed(self) -> None:
        path = os.path.join(fresh_dir("perm"), "k")
        with open(path, "w") as handle:
            handle.write("x")
        os.chmod(path, 0o644)
        with mock.patch("src.utils.fileio.os.chmod", side_effect=PermissionError("izin yok")):
            with self.assertLogs("TransferTCP", level="WARNING") as captured:
                self.assertFalse(fileio.restrict_permissions(path, 0o600))
        self.assertIn("0o600", "\n".join(captured.output))

    @posix_only
    def test_restrict_leaves_stricter_modes_alone(self) -> None:
        path = os.path.join(fresh_dir("perm"), "k")
        with open(path, "w") as handle:
            handle.write("x")
        os.chmod(path, 0o400)
        self.assertTrue(fileio.restrict_permissions(path, 0o600))
        self.assertEqual(mode_of(path), 0o400)

    def test_atomic_write_with_mode_works_on_every_platform(self) -> None:
        path = os.path.join(fresh_dir("perm"), "sub", "secret.bin")
        fileio.atomic_write_bytes(path, b"gizli", mode=0o600)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"gizli")
        if POSIX:
            self.assertEqual(mode_of(path), 0o600)

    @posix_only
    def test_ensure_private_dir_only_touches_the_leaf(self) -> None:
        base = fresh_dir("perm")
        os.chmod(base, 0o755)
        leaf = os.path.join(base, "TransferTCP")
        self.assertTrue(fileio.ensure_private_dir(leaf))
        self.assertEqual(mode_of(leaf), 0o700)
        self.assertEqual(mode_of(base), 0o755)


class HardwareIdTest(unittest.TestCase):
    def setUp(self) -> None:
        crypto._cached_hardware_id = None
        self.addCleanup(setattr, crypto, "_cached_hardware_id", None)

    @unittest.skipUnless(sys.platform == "win32", "Windows kayit defteri")
    def test_windows_hardware_id_is_unchanged(self) -> None:
        parts = crypto._windows_hardware_parts()
        self.assertTrue(parts)
        expected = hashlib.sha256("|".join(parts).encode("utf-8", "replace")).hexdigest()
        self.assertEqual(crypto.get_hardware_id(), expected)

    def test_linux_uses_machine_id_and_hides_the_raw_value(self) -> None:
        raw = "0123456789abcdef0123456789abcdef"
        with mock.patch.object(crypto, "_linux_hardware_parts", return_value=[f"machine-id:{raw}"]):
            digest = crypto.get_hardware_id("linux")
        self.assertEqual(len(digest), 64)
        self.assertNotIn(raw, digest)
        self.assertEqual(digest, hashlib.sha256(f"machine-id:{raw}|app:TransferTCP".encode()).hexdigest())

        def fake_read(path):
            if path == "/etc/machine-id":
                return raw
            raise FileNotFoundError(path)

        self.assertEqual(crypto._linux_hardware_parts(fake_read), [f"machine-id:{raw}"])

    def test_linux_machine_id_falls_back_to_dbus_path_then_empty(self) -> None:
        def only_dbus(path):
            if path == "/var/lib/dbus/machine-id":
                return "feedfacefeedfacefeedfacefeedface"
            raise FileNotFoundError(path)

        self.assertEqual(crypto._linux_hardware_parts(only_dbus), ["machine-id:feedfacefeedfacefeedfacefeedface"])
        self.assertEqual(crypto._linux_hardware_parts(lambda p: (_ for _ in ()).throw(FileNotFoundError(p))), [])
        self.assertEqual(crypto._linux_hardware_parts(lambda p: ""), [])

    def test_macos_platform_uuid_from_ioreg_then_sysctl(self) -> None:
        ioreg = '''+-o Root  <class IORegistryEntry>
  +-o MacBookPro18,3  <class IOPlatformExpertDevice>
    {
      "IOPlatformUUID" = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    }
'''
        calls = []

        def run_ioreg(argv):
            calls.append(argv[0])
            return ioreg

        self.assertEqual(crypto._macos_hardware_parts(run_ioreg),
                         ["platform-uuid:AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"])
        self.assertEqual(calls, ["/usr/sbin/ioreg"])

        def run_sysctl_only(argv):
            return "11111111-2222-3333-4444-555555555555\n" if "sysctl" in argv[0] else "boş çıktı"

        self.assertEqual(crypto._macos_hardware_parts(run_sysctl_only),
                         ["platform-uuid:11111111-2222-3333-4444-555555555555"])

        def broken(argv):
            raise OSError("ioreg yok")

        self.assertEqual(crypto._macos_hardware_parts(broken), [])

    def test_macos_hardware_id_is_stable_and_differs_from_linux(self) -> None:
        with mock.patch.object(crypto, "_macos_hardware_parts", return_value=["platform-uuid:ABC"]):
            mac1 = crypto.get_hardware_id("darwin")
            crypto._cached_hardware_id = None
            mac2 = crypto.get_hardware_id("darwin")
        crypto._cached_hardware_id = None
        with mock.patch.object(crypto, "_linux_hardware_parts", return_value=["machine-id:ABC"]):
            lin = crypto.get_hardware_id("linux")
        self.assertEqual(mac1, mac2)
        self.assertNotEqual(mac1, lin)

    def test_fallback_uses_a_persisted_random_id_not_a_per_run_mac(self) -> None:
        with mock.patch.object(crypto, "_linux_hardware_parts", return_value=[]):
            first = crypto.get_hardware_id("linux")
            crypto._cached_hardware_id = None
            second = crypto.get_hardware_id("linux")
        self.assertEqual(first, second, "yedek kimlik acilislar arasinda degisti")
        path = os.path.join(os.path.dirname(crypto._trust_path()), "device_id")
        self.assertTrue(os.path.isfile(path))
        if POSIX:
            self.assertEqual(mode_of(path), 0o600)

    @unittest.skipUnless(sys.platform.startswith("linux") and os.path.exists("/etc/machine-id"),
                         "gercek /etc/machine-id gerekli")
    def test_real_linux_machine_id_is_read(self) -> None:
        parts = crypto._linux_hardware_parts()
        self.assertEqual(len(parts), 1)
        self.assertTrue(parts[0].startswith("machine-id:"))


if __name__ == "__main__":
    unittest.main()
