"""Çekirdek hata metinleri arayüz diline çevrilir (sözlük + kalıplar); karşılığı olmayan metin olduğu gibi kalır."""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (yalıtılmış kullanıcı dizini; Qt offscreen)

from src.utils.error_text import localize_error  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"
TURKISH_LETTERS = set("ığüşöçİĞÜŞÖÇ")


def _strings(node: ast.AST) -> list[str]:
    """Doğrudan sabit metinler: `"x"`, `("x", None)`, `(False, "x")`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Tuple):
        return [s for element in node.elts for s in _strings(element)]
    return []


def _user_facing_literals(path: Path, functions: set[str]) -> list[str]:
    """Verilen işlevlerin döndürdüğü / sözlükte tuttuğu / `_fail(...)`e verdiği sabit metinler."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)) or func.name not in functions:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Return) and node.value is not None:
                found += _strings(node.value)
            elif isinstance(node, ast.Dict):
                for value in node.values:
                    found += _strings(value)
            elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_fail" and node.args:
                found += _strings(node.args[0])
    return [s for s in found if s.strip()]


class LocalizeErrorTest(unittest.TestCase):
    def test_turkish_ui_keeps_the_original_text(self):
        text = "Zaman aşımı. Alıcı cihaz çok yavaş yanıt veriyor."
        self.assertEqual(localize_error(text, "tr"), text)

    def test_english_ui_translates_known_messages(self):
        self.assertEqual(
            localize_error("Zaman aşımı. Alıcı cihaz çok yavaş yanıt veriyor.", "en"),
            "Timed out. The receiving device is responding too slowly.",
        )
        self.assertEqual(localize_error("Bilinmeyen hata", "en"), "Unknown error")

    def test_messages_with_variable_parts(self):
        self.assertEqual(
            localize_error("Diskte yeterli boş alan yok (gerekli: 1.5 GB, boş: 200 MB).", "en"),
            "Not enough free disk space (needed: 1.5 GB, free: 200 MB).",
        )
        self.assertEqual(localize_error("Eksik transfer: 100/200 byte alındı", "en"),
                         "Incomplete transfer: 100/200 bytes received")
        self.assertEqual(localize_error("Geçersiz alan: folder_total.", "en"), "Invalid field: folder_total.")
        self.assertEqual(localize_error(r"Dosya bulunamadı: C:\Temp\a.txt", "en"), r"File not found: C:\Temp\a.txt")

    def test_a_message_wrapped_by_the_peer_is_translated_inside_too(self):
        self.assertEqual(
            localize_error("Alıcı cihaz hatası: Diskte yeterli boş alan yok.", "en"),
            "Receiver error: Not enough free disk space.",
        )
        self.assertEqual(
            localize_error("Alıcı cihaz dosyayı kaydedemedi: Erişim engellendi (Yazma yetkisi yok).", "en"),
            "The receiving device could not save the file: Access denied (no write permission).",
        )
        self.assertEqual(
            localize_error("Transfer başarısız: Geçersiz yanıt türü: 7", "en"),
            "Transfer failed: Invalid response type: 7",
        )

    def test_unknown_text_stays_as_it_is(self):
        # Windows'un kendi hata metni gibi sözlükte olmayanlar çevrilmeden gösterilir
        text = "[WinError 10061] Hedef makine etkin olarak reddettiğinden bağlantı kurulamadı"
        self.assertEqual(localize_error(text, "en"), text)
        self.assertEqual(localize_error("Transfer başarısız: weird thing", "en"), "Transfer failed: weird thing")

    def test_empty_and_none(self):
        self.assertEqual(localize_error(None, "en"), "")
        self.assertEqual(localize_error("", "en"), "")

    def test_every_translation_differs_from_its_source(self):
        from src.utils.error_text import _EXACT_EN

        for turkish, english in _EXACT_EN.items():
            self.assertNotEqual(turkish, english)
            self.assertFalse(set(english) & set("ığüşöçİĞÜŞÖÇ"), f"çeviride Türkçe harf kalmış: {english}")

    def test_all_fixed_core_messages_have_an_english_translation(self):
        """Çekirdeğe yeni bir sabit hata metni eklenirse buraya da karşılığı eklenmeli."""
        literals = (
            _user_facing_literals(SRC / "core" / "client.py", {"_user_error"})
            + _user_facing_literals(
                SRC / "core" / "server.py",
                {"_format_receiver_error", "_validate_file_info", "_claim_part"},
            )
            + _user_facing_literals(SRC / "utils" / "update_policy.py", {"validate_update_url", "normalize_checksum"})
            + _user_facing_literals(SRC / "utils" / "update_installer.py", {"download_update"})
        )
        self.assertGreater(len(literals), 25, "metinler okunamadı: işlev adları değişmiş olabilir")
        missing = [
            text for text in literals
            if (set(text) & TURKISH_LETTERS) and localize_error(text, "en") == text
            and "{" not in text
        ]
        self.assertEqual(missing, [], "bu metinlerin error_text.py'de İngilizce karşılığı yok")


if __name__ == "__main__":
    unittest.main()
