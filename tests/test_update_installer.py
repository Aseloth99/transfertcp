"""UpdateInstaller: indirme doğrulama matrisi (yerel HTTP sunucusu) ve süreç içi kurulum (gerçek dosya işlemleri).

Hiçbir test kullanıcının gerçek `%TEMP%\\TransferTCP_Update.pkg` dosyasına ya da çalışan exe'ye dokunmaz: paket yolu geçici
bir klasöre, "çalışan exe" geçici bir sahte exe'ye yönlendirilir; yeni süreç başlatma (`self_update.spawn`) sahtedir.
Betik (batch) kalktığı için eski `UpdaterScriptTest` güvenceleri burada `InstallTest` ile aynı davranışlar üzerinden verilir:
zip'ten kurulum, exe'siz zip'te uygulamaya dokunmama, doğrudan exe, Türkçe/boşluklu/özel karakterli klasör.
"""

from __future__ import annotations

import hashlib
import http.server
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (yalıtılmış kullanıcı dizini)
from support import fake_pe, make_zip  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.utils import self_update  # noqa: E402
from src.utils import update_installer as ui  # noqa: E402
from src.utils.update_installer import PACKAGE_NAME, UpdateInstaller  # noqa: E402

REAL_PACKAGE_PATH = ui.package_path  # testler yolu değiştirir; gerçek tanım burada saklı

BODY = b"PK-fake-update-payload" * 500
SHA = hashlib.sha256(BODY).hexdigest()
NEW_EXE = fake_pe(0x8664, b"-new")
ZIP_BODY = make_zip({"TransferTCP/TransferTCP.exe": NEW_EXE, "TransferTCP/readme.txt": b"x"})
STARTED = threading.Event()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # sessiz
        pass

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/ok.zip":
            self._send(BODY)
        elif path == "/Pages/AppDownload":  # uzantısız sunucu adresi (gerçek site böyle)
            self._send(NEW_EXE)
        elif path == "/zip-named.exe":  # uzantı yalan söylüyor: içerik zip
            self._send(ZIP_BODY)
        elif path == "/redirect.zip":
            self.send_response(302)
            self.send_header("Location", "http://evil.example/x.zip")
            self.end_headers()
        elif path == "/short.zip":
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY) + 1000))
            self.end_headers()
            self.wfile.write(BODY)
            self.wfile.flush()
            self.close_connection = True
        elif path == "/slow.zip":  # iptal testi: parça parça, yavaş
            body = BODY * 40
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                for i in range(0, len(body), 8192):
                    self.wfile.write(body[i:i + 8192])
                    self.wfile.flush()
                    STARTED.set()
                    time.sleep(0.01)
            except OSError:
                pass
        else:
            self.send_response(404)
            self.end_headers()


class _TempPackageMixin:
    """`%TEMP%` yerine test klasörü: gerçek kullanıcı dosyasına dokunulmaz."""

    def _patch_package_path(self) -> str:
        tmp = tempfile.TemporaryDirectory(prefix="tt_pkg_")
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, PACKAGE_NAME)
        patcher = mock.patch.object(ui, "package_path", lambda: path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path


class DownloadTest(_TempPackageMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        support.qt_app()
        self.pkg = self._patch_package_path()
        self.inst = UpdateInstaller()
        self.addCleanup(self.inst.cleanup)
        self.failed: list[str] = []
        self.done: list[str] = []
        self.inst.download_failed.connect(self.failed.append)
        self.inst.download_complete.connect(self.done.append)

    def test_valid_checksum_succeeds_and_is_verified(self) -> None:
        self.assertTrue(self.inst.download_update(f"{self.base}/ok.zip", len(BODY), SHA))
        self.assertTrue(self.inst.last_verified)
        path = pathlib.Path(self.done[0])
        self.assertEqual(path.read_bytes(), BODY)
        self.assertEqual(str(path), self.pkg, "indirilen dosya sabit TransferTCP_Update.pkg adına iner")

    def test_package_name_never_comes_from_the_server_url(self) -> None:
        """Eski `safe_update_filename` güvencesi: adresteki dosya adı/yol hilesi yerel adı etkilemez."""
        self.assertTrue(self.inst.download_update(f"{self.base}/Pages/AppDownload?slug=transfertcp&file=..%2F..%2Fevil.exe", None, None))
        self.assertEqual(self.done, [self.pkg])
        self.assertEqual(os.path.basename(self.pkg), "TransferTCP_Update.pkg")
        self.assertTrue(self.inst.download_update(f"{self.base}/ok.zip", None, None))
        self.assertEqual(self.done[-1], self.pkg)

    def test_real_package_name_lives_in_the_user_temp_folder(self) -> None:
        real = REAL_PACKAGE_PATH()
        self.assertEqual(os.path.normcase(os.path.dirname(real)), os.path.normcase(tempfile.gettempdir()))
        self.assertEqual(os.path.basename(real), "TransferTCP_Update.pkg")

    def test_wrong_checksum_fails_and_removes_file(self) -> None:
        self.assertFalse(self.inst.download_update(f"{self.base}/ok.zip", len(BODY), "0" * 64))
        self.assertIn("checksum", self.failed[0])
        self.assertIsNone(self.inst.downloaded_file)
        self.assertFalse(os.path.exists(self.pkg))

    def test_missing_checksum_is_downloaded_but_flagged_unverified(self) -> None:
        self.assertTrue(self.inst.download_update(f"{self.base}/ok.zip", len(BODY), None))
        self.assertFalse(self.inst.last_verified)

    def test_malformed_checksum_rejected_before_download(self) -> None:
        self.assertFalse(self.inst.download_update(f"{self.base}/ok.zip", len(BODY), "xyz"))
        self.assertEqual(self.done, [])
        self.assertIn("geçersiz", self.failed[0])

    def test_size_mismatch_fails(self) -> None:
        self.assertFalse(self.inst.download_update(f"{self.base}/ok.zip", len(BODY) + 5, SHA))
        self.assertIn("boyut", self.failed[0].lower())

    def test_redirect_to_untrusted_host_is_refused(self) -> None:
        self.assertFalse(self.inst.download_update(f"{self.base}/redirect.zip", None, SHA))
        self.assertIn("Yönlendirme reddedildi", self.failed[0])

    def test_incomplete_download_fails(self) -> None:
        self.assertFalse(self.inst.download_update(f"{self.base}/short.zip", None, SHA))
        self.assertEqual(self.done, [])

    def test_insecure_or_untrusted_urls_never_hit_network(self) -> None:
        for url in ("http://macik.com.tr/x.zip", "https://evil.example/x.zip"):
            self.failed.clear()
            self.assertFalse(self.inst.download_update(url, None, SHA), url)
            self.assertEqual(len(self.failed), 1)

    def test_garbage_expected_size_is_tolerated(self) -> None:
        for size in ("abc", object(), -5):
            self.done.clear()
            self.assertTrue(self.inst.download_update(f"{self.base}/ok.zip", size, SHA), size)

    def test_cancel_stops_the_loop_and_removes_the_partial_file(self) -> None:
        STARTED.clear()
        thread = ui.DownloadThread(self.inst, f"{self.base}/slow.zip", None, None)
        thread.start()
        self.assertTrue(STARTED.wait(10), "indirme başlamadı")
        self.inst.cancel_download()
        self.inst.cleanup()  # arayüz iptalde `downloaded_file`ı boşaltsa bile işçi kendi dosyasını silmeli
        self.assertTrue(thread.wait(10000), "iptal edilen indirme bitmedi")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()  # işçi iş parçacığının sinyali kuyruğa düşer
        self.assertEqual(self.failed, ["cancelled"])
        self.assertEqual(self.done, [])
        self.assertFalse(os.path.exists(self.pkg), "yarım paket kalmamalı")

    def test_progress_signal_survives_sizes_above_two_gigabytes(self) -> None:
        """pyqtSignal(int) 32 bittir; 2 GB üstü boyut taşardı."""
        seen = []
        self.inst.download_progress.connect(lambda d, t, s: seen.append((d, t)))
        self.inst.download_progress.emit(3_000_000_000, 5_000_000_000, 1.5)
        self.assertEqual(seen, [(3_000_000_000, 5_000_000_000)])


class InstallTest(_TempPackageMixin, unittest.TestCase):
    """Gerçek `install_update`: sahte "çalışan exe" geçici klasörde; yeni süreç başlatma sahte."""

    def setUp(self) -> None:
        support.qt_app()
        # Türkçe karakterli, boşluklu ve %, !, ', & içeren klasör (eski batch betiği bunlarda bozuluyordu)
        self._tmp = tempfile.TemporaryDirectory(prefix="güncelleme ışık %!'& ")
        self.addCleanup(self._tmp.cleanup)
        self.app_dir = os.path.join(self._tmp.name, "uygulama klasörü")
        os.makedirs(self.app_dir)
        self.exe = os.path.join(self.app_dir, "TransferTCP.exe")
        with open(self.exe, "wb") as handle:
            handle.write(fake_pe(0x8664, b"-old"))
        with open(os.path.join(self.app_dir, "veri.txt"), "w", encoding="utf-8") as handle:
            handle.write("eski veri")
        self.pkg = self._patch_package_path()
        for patcher in (
            mock.patch.object(ui, "current_exe", lambda: self.exe),
            mock.patch.object(self_update, "spawn"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.spawn = self_update.spawn
        self.inst = UpdateInstaller()
        self.results: list[tuple] = []
        self.inst.install_complete.connect(lambda: self.results.append(("ok",)))
        self.inst.install_failed.connect(lambda m: self.results.append(("fail", m)))

    def _install(self, data: bytes, **kwargs) -> bool:
        with open(self.pkg, "wb") as handle:
            handle.write(data)
        self.inst.downloaded_file = self.pkg
        return self.inst.install_update(**kwargs)

    def _read(self, path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()

    def test_zip_update_replaces_only_the_exe_and_relaunches(self) -> None:
        self.assertTrue(self._install(ZIP_BODY, visible=True, old_version="1.0.0"))
        self.assertEqual(self.results, [("ok",)])
        self.assertEqual(self._read(self.exe), NEW_EXE)
        self.assertTrue(os.path.exists(self.exe + ".old"), "eski sürüm, yeni sürüm kendini kanıtlayana dek saklanır")
        with open(os.path.join(self.app_dir, "veri.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "eski veri")
        self.assertEqual(sorted(os.listdir(self.app_dir)), sorted(["TransferTCP.exe", "TransferTCP.exe.old", "veri.txt"]),
                         "zip'ten exe dışında hiçbir dosya yazılmaz (readme.txt yok)")
        self.assertFalse(os.path.exists(self.pkg), "indirilen paket silinir")
        exe, args = self.spawn.call_args[0]
        self.assertEqual(exe, self.exe)
        self.assertEqual(list(args), ["--wait-pid", str(os.getpid()), "--updated", "1.0.0", "--show-window"])

    def test_hidden_window_relaunches_minimized(self) -> None:
        self.assertTrue(self._install(NEW_EXE, visible=False, old_version="1.0.0"))
        self.assertEqual(list(self.spawn.call_args[0][1])[-1], "--minimized")

    def test_direct_exe_package(self) -> None:
        self.assertTrue(self._install(NEW_EXE))
        self.assertEqual(self._read(self.exe), NEW_EXE)

    def test_archive_without_exe_leaves_app_untouched_and_fails(self) -> None:
        before = self._read(self.exe)
        self.assertFalse(self._install(make_zip({"baska_dosya.txt": b"x"})))
        self.assertEqual(self.results[0][0], "fail")
        self.assertEqual(self._read(self.exe), before)
        self.assertEqual(sorted(os.listdir(self.app_dir)), sorted(["TransferTCP.exe", "veri.txt"]),
                         "uygulama klasörüne dokunulmamalı (artık .new/.old yok)")
        self.spawn.assert_not_called()

    def test_wrong_architecture_and_html_are_refused(self) -> None:
        for data in (fake_pe(0x014C), b"<html>404</html>", make_zip({"TransferTCP.exe": b"MZ-sahte"})):
            self.results.clear()
            self.assertFalse(self._install(data))
            self.assertEqual(self._read(self.exe), fake_pe(0x8664, b"-old"))

    def test_renamed_exe_copy_still_finds_the_package_exe(self) -> None:
        """Kullanıcı dosyayı yeniden adlandırmış olabilir ("TransferTCP (1).exe"); zip'teki resmi ad yine bulunur."""
        names = ui.exe_names(os.path.join(self.app_dir, "TransferTCP (1).exe"))
        self.assertEqual(names, ("TransferTCP.exe", "TransferTCP (1).exe"))
        self.assertEqual(ui.exe_names(self.exe), ("TransferTCP.exe",))

    def test_missing_package_reports_failure_without_touching_anything(self) -> None:
        self.inst.downloaded_file = os.path.join(self.app_dir, "yok.pkg")
        self.assertFalse(self.inst.install_update())
        self.assertEqual(self.results, [("fail", "Güncelleme dosyası bulunamadı.")])

    def test_swap_failure_keeps_the_running_exe(self) -> None:
        real = os.replace

        def flaky(src, dst):
            if str(src).endswith(".new"):
                raise PermissionError("kilitli")
            return real(src, dst)

        with mock.patch.object(self_update.os, "replace", flaky):
            self.assertFalse(self._install(NEW_EXE))
        self.assertEqual(self._read(self.exe), fake_pe(0x8664, b"-old"))
        self.assertEqual(self.results[0][0], "fail")

    def test_install_thread_reports_through_signals(self) -> None:
        with open(self.pkg, "wb") as handle:
            handle.write(NEW_EXE)
        self.inst.downloaded_file = self.pkg
        thread = ui.InstallThread(self.inst, False, "1.0.0")
        thread.start()
        self.assertTrue(thread.wait(10000))
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        self.assertEqual(self.results, [("ok",)])

    def test_unsupported_reason(self) -> None:
        with mock.patch.object(ui.os, "name", "posix"):
            self.assertEqual(ui.unsupported_reason(), "os")
        with mock.patch.object(ui.os, "name", "nt"), mock.patch.object(ui, "is_frozen", return_value=False):
            self.assertEqual(ui.unsupported_reason(), "source")
        with mock.patch.object(ui.os, "name", "nt"), mock.patch.object(ui, "is_frozen", return_value=True):
            self.assertIsNone(ui.unsupported_reason())


class TranslatedErrorsTest(unittest.TestCase):
    """Kurulum/paket hata metinleri (self_update'ten gelen Türkçe) İngilizce arayüzde de anlamlı olmalı."""

    def test_package_errors_are_translated(self) -> None:
        from src.utils.error_text import localize_error

        turkish_letters = set("ığüşöçİĞÜŞÖÇ")
        samples = [
            "Paket okunamadı: [Errno 2] No such file",
            "İndirilen dosya bir exe ya da zip değil",
            "Paket izin verilen boyuttan büyük",
            "Pakette uygulamanın exe dosyası yok",
            "Zip dosyası bozuk: File is not a zip file",
            "Yeni sürüm uygulamanın klasörüne yazılamadı: [Errno 28] No space left on device",
            "Paketteki dosya geçerli bir Windows uygulaması değil",
            "Paket başka bir işlemci mimarisi için hazırlanmış (0x014c, bu bilgisayar 0x8664)",
            r"Uygulamanın bulunduğu klasöre yazılamıyor (C:\Program Files (x86)\TransferTCP): [WinError 5] Access is denied",
            "Çalışan uygulama dosyası değiştirilemedi: [WinError 32] in use",
            "Yeni sürüm yerine konamadı: [WinError 5] Access is denied",
            "Yeni sürüm başlatılamadı: [WinError 2] not found",
            "Güncelleme dosyası bulunamadı.",
            "Otomatik kurulum yalnızca Windows'ta var. İndirilen dosyayı uygulama klasörüyle değiştirin.",
        ]
        for text in samples:
            english = localize_error(text, "en")
            self.assertNotEqual(english, text, text)
            self.assertFalse(set(english) & turkish_letters, english)
            self.assertEqual(localize_error(text, "tr"), text)

    def test_every_package_error_literal_in_self_update_has_a_translation(self) -> None:
        """`self_update.py`'ye yeni bir PackageError metni eklenirse error_text.py'ye de karşılığı eklenmeli."""
        import ast
        from src.utils.error_text import localize_error

        source = pathlib.Path(self_update.__file__).read_text(encoding="utf-8")
        found = 0
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PackageError" and node.args):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):  # f"... {x}": değişkenleri örnek metinle doldur
                text = "".join(p.value if isinstance(p, ast.Constant) else "ÖRNEK" for p in arg.values)
            else:
                continue
            found += 1
            if set(text) & set("ığüşöçİĞÜŞÖÇ"):
                self.assertNotEqual(localize_error(text, "en"), text, f"çevirisi yok: {text}")
        self.assertGreaterEqual(found, 10, "PackageError metinleri okunamadı")


if __name__ == "__main__":
    unittest.main()
