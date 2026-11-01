"""Güncelleme politikası (saf mantık): URL ve checksum. (Dosya adı/batch yolu denetimleri kalktı: paket sabit
`TransferTCP_Update.pkg` (%TEMP%) adına iner, türü içeriğe bakılarak anlaşılır; bkz. test_update_installer.)"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (yalıtılmış kullanıcı dizini)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.utils import update_policy as pol  # noqa: E402


class ValidateUrlTest(unittest.TestCase):
    def test_trusted_https_accepted(self) -> None:
        for url in (
            "https://macik.com.tr/downloads/TransferTCP.zip",
            "https://cdn.macik.com.tr/TransferTCP.zip",
            "https://MACIK.COM.TR/x.zip",
        ):
            self.assertTrue(pol.validate_update_url(url)[0], url)

    def test_untrusted_or_insecure_rejected(self) -> None:
        for url in (
            "http://macik.com.tr/TransferTCP.zip",            # HTTPS değil
            "https://evil.example/TransferTCP.zip",            # güvenilmeyen alan adı
            "https://macik.com.tr.evil.example/x.zip",    # benzetme
            "https://evilmacik.com.tr/x.zip",             # son ek hilesi
            "https://user:pw@macik.com.tr/x.zip",         # kimlik bilgisi
            "https://macik.com.tr:8443/x.zip",            # beklenmeyen port
            "ftp://macik.com.tr/x.zip",
            "file:///C:/x.zip",
            "",
            "not a url",
        ):
            self.assertFalse(pol.validate_update_url(url)[0], url)

    def test_localhost_only_when_not_frozen(self) -> None:
        self.assertTrue(pol.validate_update_url("http://127.0.0.1:8000/x.zip")[0])
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertFalse(pol.validate_update_url("http://127.0.0.1:8000/x.zip")[0])
            self.assertFalse(pol.validate_update_url("http://localhost/x.zip")[0])


class ChecksumTest(unittest.TestCase):
    def test_checksum_normalization(self) -> None:
        good = "A" * 64
        self.assertEqual(pol.normalize_checksum("sha256:" + good), "a" * 64)
        self.assertEqual(pol.normalize_checksum("  " + good + " "), "a" * 64)
        self.assertIsNone(pol.normalize_checksum(""))
        self.assertIsNone(pol.normalize_checksum(None))
        for bad in ("xyz", "a" * 63, "g" * 64, "sha1:" + "a" * 40):
            with self.assertRaises(ValueError):
                pol.normalize_checksum(bad)

    def test_extensionless_server_urls_are_valid(self) -> None:
        """Sunucu adresi uzantısız olabilir (AppDownload?slug=...&file=...): paket türü içerikten anlaşılır."""
        self.assertTrue(pol.validate_update_url("https://macik.com.tr/Pages/AppDownload?slug=transfertcp&file=TransferTCP.exe")[0])
        self.assertTrue(pol.validate_update_url("https://macik.com.tr/Pages/AppDownload?slug=transfertcp")[0])

    def test_batch_era_helpers_are_gone(self) -> None:
        for name in ("check_batch_path", "ps_escape", "safe_update_filename", "ALLOWED_EXTENSIONS"):
            self.assertFalse(hasattr(pol, name), f"{name}: betik/uzantı mantığı kaldırıldı")


if __name__ == "__main__":
    unittest.main()
