"""exe'nin sürüm kaynağı (file_version_info.txt) uygulamanın sürümüyle aynı kalsın; spec dosyası onu kullansın."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PackagingVersionTest(unittest.TestCase):
    def test_version_resource_matches_the_app_version(self):
        from src.utils.updater import UpdateChecker
        text = (ROOT / "file_version_info.txt").read_text(encoding="utf-8")
        version = UpdateChecker.CURRENT_VERSION
        four = ".".join((version.split(".") + ["0"] * 4)[:4])
        self.assertIn(f"StringStruct('FileVersion', '{four}')", text)
        self.assertIn(f"StringStruct('ProductVersion', '{four}')", text)
        nums = ", ".join((version.split(".") + ["0"] * 4)[:4])
        self.assertIn(f"filevers=({nums})", text)
        self.assertIn(f"prodvers=({nums})", text)
        self.assertIn("StringStruct('OriginalFilename', 'TransferTCP.exe')", text)

    def test_spec_embeds_the_version_resource(self):
        spec = (ROOT / "TransferTCP.spec").read_text(encoding="utf-8")
        self.assertTrue(re.search(r"version\s*=\s*'file_version_info\.txt'", spec))

    def test_pyinstaller_can_parse_the_resource(self):
        try:
            from PyInstaller.utils.win32 import versioninfo
        except ImportError:
            self.skipTest("PyInstaller yok")
        info = versioninfo.load_version_info_from_text_file(str(ROOT / "file_version_info.txt"))
        self.assertEqual((info.ffi.fileVersionMS, info.ffi.fileVersionLS), (1 << 16, 0))   # 1.0.0.0
        strings = {s.name: s.val for s in info.kids[0].kids[0].kids}
        self.assertEqual(strings["FileVersion"], "1.0.0.0")


if __name__ == "__main__":
    unittest.main()
