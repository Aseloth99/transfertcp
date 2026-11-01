"""Güncelleme indirme, SHA-256 doğrulama ve süreç içi kurulum.

İndirme kuralları `src.utils.update_policy` içindedir: yalnızca HTTPS ve güvenilen alan adı (yönlendirmeler dahil),
boyut sınırı/uyuşması, geçerli SHA-256. İndirilen dosya `%TEMP%\\TransferTCP_Update.pkg` olur; paketin türü (exe ya da
içinde exe olan zip) adrese değil İÇERİĞE bakılarak anlaşılır.

Kurulumda betik, taskkill ve PowerShell YOKTUR: `self_update.install_and_relaunch` çalışan exe'yi yeniden adlandırır
(Windows'ta çalışan exe silinemez ama adlandırılabilir), yeni exe'yi yerine koyar ve `--wait-pid` ile başlatır. Uygulama
bundan sonra TEMİZ çıkmalıdır (`QApplication.quit()`); yeni süreç bizim çıkışımızı bekler.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from . import self_update
from .logger import get_logger
from .update_policy import (
    MAX_UPDATE_BYTES,
    is_frozen,
    is_local_dev_host,
    normalize_checksum,
    validate_update_url,
)

APP_NAME = "TransferTCP"
APP_EXE_NAME = "TransferTCP.exe"
PACKAGE_NAME = f"{APP_NAME}_Update.pkg"


def package_path() -> str:
    """İndirilen paketin yeri: `%TEMP%\\TransferTCP_Update.pkg` (Windows'ta %TEMP% kullanıcıya özeldir)."""
    return os.path.join(tempfile.gettempdir(), PACKAGE_NAME)


def current_exe() -> str:
    return os.path.abspath(sys.executable)


def exe_names(exe: Optional[str] = None) -> tuple[str, ...]:
    """Paketteki exe'nin aranacağı adlar: resmi ad + çalışan kopyanın adı (kullanıcı dosyayı yeniden adlandırmış olabilir)."""
    names = [APP_EXE_NAME]
    own = os.path.basename(exe or current_exe())
    if own and own.lower() not in {n.lower() for n in names}:
        names.append(own)
    return tuple(names)


def unsupported_reason() -> Optional[str]:
    """Bu çalışma biçiminde otomatik kurulum yapılabilir mi? None: evet. "os": Windows değil. "source": kaynaktan
    çalışıyor (değiştirilecek bir exe yok; eski betik yanlış klasöre yazıyordu)."""
    if os.name != "nt":
        return "os"
    if not is_frozen():
        return "source"
    return None


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Yönlendirmeyi izlemeden ÖNCE hedef adresi doğrula (güvenilmeyen sunucuya gitme)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        ok, reason = validate_update_url(newurl)
        if not ok:
            raise urllib.error.URLError(f"Yönlendirme reddedildi: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UpdateInstaller(QObject):
    # Boyutlar `object`: pyqtSignal(int) 32 bit'tir, 2 GB üstü değerde taşar.
    download_progress = pyqtSignal(object, object, float)  # indirilen, toplam, hız (MB/sn)
    download_complete = pyqtSignal(str)
    download_failed = pyqtSignal(str)
    install_started = pyqtSignal()
    install_complete = pyqtSignal()
    install_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self.downloaded_file: Optional[str] = None
        self._target: Optional[str] = None  # yazılmakta olan paket (iptal arayüzden `downloaded_file`ı boşaltsa da silinebilsin)
        # True: sunucunun verdiği SHA-256 ile doğrulandı. False: sunucu sağlama toplamı vermedi.
        self.last_verified = False
        self._cancel = False
        self.speed_samples: deque = deque()
        self.smoothed_speed = 0.0
        self._last_progress_emit = 0.0

    # ----------------------------------------------------------- yardımcılar
    def cancel_download(self) -> None:
        self._cancel = True

    def cleanup(self) -> None:
        """İndirilmiş/yarım paketi siler (açık tutulan dosya silinemezse indirme döngüsü kendi temizler)."""
        path = self._target or self.downloaded_file
        self.downloaded_file = None
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    def _emit_progress(self, downloaded: int, total: int, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_progress_emit) < 0.1:
            return
        self._last_progress_emit = now
        self.download_progress.emit(downloaded, total, self._smooth_speed(self._calculate_speed()))

    def _add_speed_sample(self, bytes_downloaded: int) -> None:
        now = time.time()
        self.speed_samples.append((now, bytes_downloaded))
        cutoff = now - 1.5
        while self.speed_samples and self.speed_samples[0][0] < cutoff:
            self.speed_samples.popleft()

    def _calculate_speed(self) -> float:
        if len(self.speed_samples) < 2:
            return 0.0
        first_time, first_bytes = self.speed_samples[0]
        last_time, last_bytes = self.speed_samples[-1]
        span = last_time - first_time
        if span <= 0:
            return 0.0
        return ((last_bytes - first_bytes) / span) / (1024 * 1024)

    def _smooth_speed(self, new_speed: float) -> float:
        if self.smoothed_speed == 0.0:
            self.smoothed_speed = new_speed
        else:
            self.smoothed_speed = 0.3 * new_speed + 0.7 * self.smoothed_speed
        return self.smoothed_speed

    def _sha256_file(self, path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _fail(self, message: str) -> bool:
        self.logger.error(f"Güncelleme indirilemedi: {message}")
        self.cleanup()
        self.download_failed.emit(message)
        return False

    # --------------------------------------------------------------- indirme
    def download_update(
        self,
        download_url: str,
        expected_size: Optional[int] = None,
        expected_checksum: Optional[str] = None,
    ) -> bool:
        self._cancel = False
        self.last_verified = False
        self.speed_samples.clear()
        self.smoothed_speed = 0.0
        self._last_progress_emit = 0.0

        ok, reason = validate_update_url(download_url)
        if not ok:
            return self._fail(reason)
        try:
            checksum = normalize_checksum(expected_checksum)
        except ValueError as exc:
            return self._fail(str(exc))
        try:
            expected_size = int(expected_size) if expected_size else 0
        except (TypeError, ValueError):
            expected_size = 0
        expected_size = max(expected_size, 0)  # eksi/bozuk boyut = bilinmiyor
        if expected_size > MAX_UPDATE_BYTES:
            return self._fail("Güncelleme boyutu izin verilen sınırı aşıyor.")

        try:
            self.cleanup()
            self._target = self.downloaded_file = package_path()

            parsed = urllib.parse.urlparse(download_url)
            ssl_context = ssl._create_unverified_context() if is_local_dev_host(parsed.hostname) else None
            opener = urllib.request.build_opener(
                _SafeRedirectHandler, urllib.request.HTTPSHandler(context=ssl_context)
            )
            cache_buster = int(time.time() * 1000)
            sep = "&" if parsed.query else "?"
            req = urllib.request.Request(f"{download_url}{sep}_t={cache_buster}")
            req.add_header("User-Agent", "AppUpp/1.0 TransferTCP-Updater")
            req.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
            req.add_header("Pragma", "no-cache")
            req.add_header("Expires", "0")

            with opener.open(req, timeout=30) as response:
                header_length = int(response.headers.get("Content-Length", 0) or 0)
                total_size = header_length or expected_size
                if total_size > MAX_UPDATE_BYTES:
                    return self._fail("Güncelleme boyutu izin verilen sınırı aşıyor.")
                downloaded = 0
                if total_size > 0:
                    self._emit_progress(0, total_size, force=True)
                with open(self.downloaded_file, "wb") as handle:
                    while True:
                        if self._cancel:
                            handle.close()
                            self.cleanup()
                            self.download_failed.emit("cancelled")
                            return False
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > MAX_UPDATE_BYTES:
                            handle.close()
                            return self._fail("Güncelleme boyutu izin verilen sınırı aşıyor.")
                        self._add_speed_sample(downloaded)
                        self._emit_progress(downloaded, total_size)
            self._emit_progress(downloaded, total_size, force=True)

            # Boyut: hem sunucu başlığı hem API'nin bildirdiği boyutla uyuşmalı.
            if header_length and downloaded != header_length:
                return self._fail("İndirme eksik kaldı (boyut uyuşmuyor).")
            if expected_size and downloaded != expected_size:
                return self._fail("İndirilen dosyanın boyutu beklenenle uyuşmuyor.")
            if downloaded <= 0:
                return self._fail("İndirilen dosya boş.")

            if checksum is not None:
                if self._sha256_file(self.downloaded_file) != checksum:
                    return self._fail("Dosya bütünlüğü doğrulanamadı (checksum).")
                self.last_verified = True

            if self._cancel:  # sağlama toplamı hesaplanırken iptal edildi
                self.cleanup()
                self.download_failed.emit("cancelled")
                return False

            self.download_complete.emit(self.downloaded_file)
            return True
        except Exception as exc:
            return self._fail(str(exc))

    # ---------------------------------------------------------------- kurulum
    def install_update(self, visible: bool = False, old_version: str = "") -> bool:
        """İndirilen paketi kurar ve yeni sürümü başlatır (BLOKLAYICI; arayüz iş parçacığından çağrılmamalı).

        Başarıda `install_complete` yayılır ve çağıran uygulama TEMİZ çıkmalıdır (yeni süreç bizi bekliyor).
        Hatada `install_failed` yayılır; çalışan uygulamaya dokunulmamıştır.
        """
        try:
            update_file = self.downloaded_file
            if not update_file or not os.path.exists(update_file):
                self.install_failed.emit("Güncelleme dosyası bulunamadı.")
                return False
            if unsupported_reason() == "os":
                self.install_failed.emit(
                    "Otomatik kurulum yalnızca Windows'ta var. İndirilen dosyayı uygulama klasörüyle değiştirin."
                )
                return False
            exe = current_exe()
            self.install_started.emit()
            self_update.install_and_relaunch(
                update_file, exe, exe_names(exe), visible=visible, old_version=old_version, max_bytes=MAX_UPDATE_BYTES
            )
        except self_update.PackageError as exc:
            self.install_failed.emit(str(exc))
            return False
        except Exception as exc:
            self.install_failed.emit(str(exc))
            return False
        self.downloaded_file = None  # paket kurulum sırasında silindi
        self.install_complete.emit()
        return True


class DownloadThread(QThread):
    """İndirmeyi arayüzü dondurmadan yürütür; sonuç `UpdateInstaller` sinyalleriyle gelir."""

    def __init__(self, installer: UpdateInstaller, download_url: str, file_size: Optional[int],
                 checksum: Optional[str], parent=None):
        super().__init__(parent)
        self.installer = installer
        self.download_url = download_url
        self.file_size = file_size if file_size and file_size > 0 else None
        self.checksum = checksum if checksum else None

    def run(self):
        try:
            self.installer.download_update(self.download_url, self.file_size, self.checksum)
        except Exception as exc:  # güvence: arayüz "indiriliyor"da takılı kalmasın
            self.installer.download_failed.emit(str(exc))


class InstallThread(QThread):
    """Kurulumu (paketi açma, exe değiştirme, yeni sürümü başlatma) arayüzü dondurmadan yürütür."""

    def __init__(self, installer: UpdateInstaller, visible: bool, old_version: str, parent=None):
        super().__init__(parent)
        self.installer = installer
        self.visible = bool(visible)
        self.old_version = old_version or ""

    def run(self):
        try:
            self.installer.install_update(visible=self.visible, old_version=self.old_version)
        except Exception as exc:
            self.installer.install_failed.emit(str(exc))
