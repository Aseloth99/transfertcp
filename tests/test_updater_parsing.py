"""UpdateChecker: sunucu JSON alan tipleri, geri alınan sürümün (skip) önerilmemesi, check_failed, damga davranışı.

Ağ yok: `urllib.request.urlopen` sahtedir.
"""

import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils import updater as updater_module  # noqa: E402
from src.utils.updater import UpdateChecker, as_bool, as_size, as_text  # noqa: E402

URL = "https://macik.com.tr/Pages/AppDownload?slug=transfertcp&file=TransferTCP.exe"


def reply(payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = body
    return mock.Mock(return_value=response)


class ParsersTest(unittest.TestCase):
    def test_as_bool(self):
        for value, expected in ((True, True), (False, False), ("true", True), ("True", True), (" TRUE ", True), ("1", True),
                                ("false", False), ("False", False), ("0", False), ("", False), (None, False),
                                (1, True), (0, False), (0.0, False), ("hayır", False), ([], False)):
            self.assertIs(as_bool(value), expected, repr(value))

    def test_as_size(self):
        for value, expected in ((15728640, 15728640), ("15728640", 15728640), (" 42 ", 42), (1.5e9, 1_500_000_000),
                                ("2147483648", 2147483648), (10**12, 10**12), (None, 0), ("", 0), ("abc", 0), (-5, 0),
                                (float("nan"), 0), (float("inf"), 0), (True, 0), ([], 0), ("1,5", 0)):
            self.assertEqual(as_size(value), expected, repr(value))

    def test_as_text(self):
        self.assertEqual(as_text("  v1.2 "), "v1.2")
        self.assertEqual(as_text(1.2), "1.2")
        self.assertEqual(as_text(None), "")
        self.assertEqual(as_text({"a": 1}), "")


class CheckCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.qt_app()

    def setUp(self):
        self.checker = UpdateChecker()
        self.offered = []
        self.complete = []
        self.failed = []
        self.messages = []
        self.checker.update_available.connect(lambda *a: self.offered.append(a))
        self.checker.check_complete.connect(self.complete.append)
        self.checker.check_failed.connect(lambda: self.failed.append(True))
        self.checker.check_message.connect(lambda *a: self.messages.append(a))
        self.checker.config.set("advanced", "last_update_check", None)

    def run_check(self, payload, manual=False, **patches):
        with mock.patch("src.utils.updater.urllib.request.urlopen", payload if callable(payload) else reply(payload)), \
                mock.patch("src.utils.updater.get_active_language", return_value="tr"):
            self.checker._check_for_updates_sync(manual)


class FieldTypeTest(CheckCase):
    def payload(self, **over):
        data = {"updateAvailable": True, "version": "9.9.9", "download_url": URL, "release_notes": "<p>n</p>",
                "isMandatory": False, "fileSize": 1234, "checksum": "a" * 64}
        data.update(over)
        return data

    def test_string_false_is_not_mandatory(self):
        self.run_check(self.payload(isMandatory="false"))
        self.assertIs(self.offered[0][3], False, 'bool("false") doğru olurdu: güncelleme zorunlu sayılıyordu')
        self.offered.clear()
        self.run_check(self.payload(isMandatory="true"))
        self.assertIs(self.offered[0][3], True)

    def test_string_update_available_false_means_up_to_date(self):
        self.run_check(self.payload(updateAvailable="false"))
        self.assertEqual(self.offered, [])
        self.assertEqual(self.complete, [False])

    def test_file_size_may_be_a_string_a_float_null_or_huge(self):
        for raw, expected in (("15728640", 15728640), (1.5e6, 1_500_000), (None, 0), ("yok", 0), (5_000_000_000, 5_000_000_000)):
            self.offered.clear()
            self.run_check(self.payload(fileSize=raw))
            self.assertEqual(self.offered[0][4], expected, repr(raw))

    def test_missing_optional_fields_are_fine(self):
        data = {"updateAvailable": True, "version": "9.9.9", "download_url": URL}
        self.run_check(data)
        version, url, notes, mandatory, size, checksum = self.offered[0]
        self.assertEqual((version, url, notes, mandatory, size, checksum), ("9.9.9", URL, "", False, 0, ""))

    def test_numeric_version_and_leading_v(self):
        self.run_check(self.payload(version="v9.9.9"))
        self.assertEqual(self.offered[0][0], "9.9.9")
        self.offered.clear()
        self.run_check(self.payload(version=9.9))
        self.assertEqual(self.offered[0][0], "9.9")

    def test_checksum_with_prefix_is_passed_through_for_the_installer_to_normalize(self):
        self.run_check(self.payload(checksum="sha256:" + "A" * 64))
        self.assertEqual(self.offered[0][5], "sha256:" + "A" * 64)

    def test_untrusted_download_url_is_never_offered(self):
        self.run_check(self.payload(download_url="http://evil.example/x.exe"))
        self.assertEqual(self.offered, [])
        self.assertEqual(self.failed, [True])


class FailureSignalTest(CheckCase):
    def test_check_failed_is_emitted_when_the_check_cannot_be_done(self):
        for payload in (mock.Mock(side_effect=urllib.error.URLError("getaddrinfo failed")),
                        mock.Mock(side_effect=TimeoutError("timed out")),
                        b"<html>not json", {"updateAvailable": True}, [1, 2]):
            self.failed.clear()
            self.run_check(payload)
            self.assertEqual(self.failed, [True], payload)
            self.assertEqual(self.complete[-1], False)

    def test_a_good_reply_does_not_emit_check_failed(self):
        self.run_check({"updateAvailable": False})
        self.assertEqual(self.failed, [])


class StampTest(CheckCase):
    def test_up_to_date_stamps_the_last_check(self):
        self.run_check({"updateAvailable": False})
        self.assertTrue(self.checker.config.get("advanced", "last_update_check", None))

    def test_a_pending_update_is_not_stamped_so_the_next_launch_offers_it_again(self):
        """Eski hata: damga atılınca uygulama yeniden açıldığında 24 saat denetim yapılmaz, tepsi/düğme kaybolurdu."""
        self.run_check({"updateAvailable": True, "version": "9.9.9", "download_url": URL})
        self.assertEqual(len(self.offered), 1)
        self.assertFalse(self.checker.config.get("advanced", "last_update_check", None))

    def test_a_failed_check_is_not_stamped(self):
        self.run_check(mock.Mock(side_effect=urllib.error.URLError("offline")))
        self.assertFalse(self.checker.config.get("advanced", "last_update_check", None))


class SkippedVersionTest(CheckCase):
    PAYLOAD = {"updateAvailable": True, "version": "9.9.9", "download_url": URL}

    def test_a_rolled_back_version_is_not_offered_again(self):
        with mock.patch.object(updater_module, "is_frozen", return_value=True), \
                mock.patch.object(updater_module.self_update, "skipped_version", return_value="9.9.9"):
            self.run_check(self.PAYLOAD, manual=True)
        self.assertEqual(self.offered, [], "geri alınan sürüm bir daha önerilmez")
        self.assertEqual(self.complete, [False], "'güncel' sayılır")
        self.assertEqual([m[0] for m in self.messages], ["info"])
        self.assertTrue(self.checker.config.get("advanced", "last_update_check", None))

    def test_a_different_newer_version_is_offered(self):
        with mock.patch.object(updater_module, "is_frozen", return_value=True), \
                mock.patch.object(updater_module.self_update, "skipped_version", return_value="9.9.8"):
            self.run_check(self.PAYLOAD)
        self.assertEqual(len(self.offered), 1)

    def test_a_mandatory_rolled_back_version_is_also_not_offered(self):
        with mock.patch.object(updater_module, "is_frozen", return_value=True), \
                mock.patch.object(updater_module.self_update, "skipped_version", return_value="9.9.9"):
            self.run_check(dict(self.PAYLOAD, isMandatory=True))
        self.assertEqual(self.offered, [])

    def test_the_skip_file_is_only_consulted_when_running_as_an_exe(self):
        with mock.patch.object(updater_module.self_update, "skipped_version", return_value="9.9.9") as skipped:
            self.run_check(self.PAYLOAD)  # paketlenmemiş test çalışması
        skipped.assert_not_called()
        self.assertEqual(len(self.offered), 1)

    def test_skipped_version_reads_the_marker_next_to_the_running_exe(self):
        import tempfile
        from src.utils import self_update

        with tempfile.TemporaryDirectory() as folder:
            exe = os.path.join(folder, "TransferTCP.exe")
            with open(exe + ".skip", "w", encoding="utf-8") as handle:
                handle.write("9.9.9")
            with mock.patch.object(updater_module, "is_frozen", return_value=True), \
                    mock.patch.object(updater_module.sys, "executable", exe):
                self.assertEqual(UpdateChecker.skipped_version(), "9.9.9")
            self.assertEqual(self_update.skipped_version(exe), "9.9.9")


if __name__ == "__main__":
    unittest.main()
