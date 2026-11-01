"""Uzaktan duyuru satiri: dogrulama ve guncelleme isteginin bicimi."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.parse
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (yalitilmis kullanici dizini; Qt offscreen)

from src.utils import remote_notice as rn  # noqa: E402


class NoticeParseTest(unittest.TestCase):
    def _data(self, **over):
        notice = {"id": "2026-10-a", "text": {"tr": "Merhaba", "en": "Hello"}, "url": "https://macik.com.tr/duyuru"}
        notice.update(over)
        return {"updateAvailable": False, "notice": notice}

    def test_language_pick_and_fallback(self):
        self.assertEqual(rn.parse_notice(self._data(), "en").text, "Hello")
        self.assertEqual(rn.parse_notice(self._data(), "tr").text, "Merhaba")
        self.assertEqual(rn.parse_notice(self._data(text={"en": "Only"}), "tr").text, "Only")
        self.assertEqual(rn.parse_notice(self._data(text="Plain"), "tr").text, "Plain")

    def test_nothing_shown_without_a_valid_notice(self):
        for data in (None, {}, {"notice": None}, {"notice": "x"}, self._data(id=""), self._data(text={}), self._data(text="  ")):
            self.assertIsNone(rn.parse_notice(data, "tr"))

    def test_expired_and_bad_dates(self):
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.assertIsNone(rn.parse_notice(self._data(expires="2026-10-13T00:00:00Z"), "tr", now))
        self.assertIsNotNone(rn.parse_notice(self._data(expires="2026-12-31T00:00:00Z"), "tr", now))
        self.assertIsNone(rn.parse_notice(self._data(expires="not a date"), "tr", now))

    def test_untrusted_links_are_dropped_but_the_text_stays(self):
        for bad in ("http://macik.com.tr/a", "https://evil.example/a", "https://macik.com.tr.evil.example/a",
                    "https://user:pw@macik.com.tr/a", "javascript:alert(1)", "file:///c:/x", 5):
            n = rn.parse_notice(self._data(url=bad), "tr")
            self.assertEqual((n.text, n.url), ("Merhaba", ""), bad)
        self.assertEqual(rn.parse_notice(self._data(url="https://www.macik.com.tr/x"), "tr").url, "https://www.macik.com.tr/x")

    def test_text_is_cleaned_and_capped(self):
        n = rn.parse_notice(self._data(text="a\u202eb\x00c\nd" + "x" * 500), "tr")
        self.assertNotIn("\u202e", n.text)
        self.assertNotIn("\x00", n.text)
        self.assertLessEqual(len(n.text), rn.MAX_TEXT)

    def test_level(self):
        self.assertEqual(rn.parse_notice(self._data(level="warn"), "tr").level, "warn")
        self.assertEqual(rn.parse_notice(self._data(level="red"), "tr").level, "info")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UpdaterRequestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _run(self, reply: dict):
        from src.utils.updater import UpdateChecker

        checker = UpdateChecker()
        seen, notices = {}, []
        checker.notice_received.connect(notices.append)

        def fake_open(req, timeout=0, context=None):
            seen["url"] = req.full_url
            return _Resp(json.dumps(reply).encode())

        with mock.patch("urllib.request.urlopen", fake_open):
            checker._check_for_updates_sync(False)
        self.app.processEvents()
        return seen["url"], notices

    def test_request_carries_only_the_app_name_and_version(self):
        from src.utils.updater import UpdateChecker

        url, _ = self._run({"updateAvailable": False})
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query, {"appName": ["TransferTCP"], "currentVersion": [UpdateChecker.CURRENT_VERSION]})

    def test_notice_arrives_even_when_there_is_no_update(self):
        _, notices = self._run({"updateAvailable": False, "notice": {"id": "n1", "text": "Bakım var"}})
        self.assertEqual([n.id for n in notices], ["n1"])
        _, notices = self._run({"updateAvailable": False})
        self.assertEqual(notices, [])


class NoticeBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_until_a_notice_then_dismissable(self):
        from src.gui.notice_bar import NoticeBar

        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        host = QWidget()
        QVBoxLayout(host).addWidget(bar := NoticeBar())
        host.show()
        self.assertFalse(bar.isVisible(), "no notice, no bar")
        bar.show_notice(rn.Notice("n1", "<b>Merhaba</b>", "https://macik.com.tr/x"))
        self.assertTrue(bar.isVisible())
        self.assertEqual(bar.text_label.text(), "<b>Merhaba</b>", "text is shown literally")
        got = []
        bar.dismissed.connect(got.append)
        bar.dismiss()
        self.assertFalse(bar.isVisible())
        self.assertEqual(got, ["n1"])

    def test_link_arrow_only_with_a_trusted_url(self):
        from src.gui.notice_bar import NoticeBar

        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        host = QWidget()
        QVBoxLayout(host).addWidget(bar := NoticeBar())
        host.show()
        bar.show_notice(rn.Notice("n1", "x", ""))
        self.assertFalse(bar.arrow.isVisible())
        bar.show_notice(rn.Notice("n2", "x", "https://macik.com.tr/a"))
        self.assertTrue(bar.arrow.isVisible())


if __name__ == "__main__":
    unittest.main()
