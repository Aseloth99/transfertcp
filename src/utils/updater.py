"""Update checker for TransferTCP"""

import json
import ssl
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread
from .config import get_config
from .logger import get_logger
from .locales import get_active_language, t
from .remote_notice import parse_notice
from .update_policy import is_frozen, is_local_dev_host, validate_update_url
from . import self_update


def as_bool(value) -> bool:
    """Sunucu JSON'unda mantıksal alanlar bazen metin ("false", "0") ya da sayı gelir; `bool("false")` doğru olurdu."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "evet", "on"}
    return False


def as_size(value) -> int:
    """`fileSize` sayı, metin ("15728640"), ondalık ya da boş gelebilir; bilinmiyorsa/bozuksa 0 (bilinmiyor)."""
    if isinstance(value, bool) or value is None:
        return 0
    try:
        if isinstance(value, str):
            number = float(value.strip())
        else:
            number = float(value)
    except (TypeError, ValueError):
        return 0
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        return 0
    return int(number)


def as_text(value) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None or isinstance(value, (dict, list)) else str(value).strip())


class _AutoCheckThread(QThread):
    def __init__(self, checker, parent=None):
        super().__init__(parent)
        self.checker = checker

    def run(self):
        self.checker._check_for_updates_sync(False)


class _ManualCheckThread(QThread):
    def __init__(self, checker, parent=None):
        super().__init__(parent)
        self.checker = checker

    def run(self):
        self.checker._check_for_updates_sync(True)


class UpdateChecker(QObject):
    """Check for application updates"""
    
    # Signals
    # file_size `object`: pyqtSignal(int) 32 bittir, 2 GB üstü boyutta taşardı
    update_available = pyqtSignal(str, str, str, bool, object, str)  # version, download_url, release_notes, is_mandatory, file_size, checksum
    check_complete = pyqtSignal(bool)  # has_update
    check_failed = pyqtSignal()  # denetim yapılamadı (çevrimdışı, sunucu hatası, bozuk yanıt)
    check_message = pyqtSignal(str, str, str)  # level, title, message (main thread)
    manual_check_finished = pyqtSignal()
    notice_received = pyqtSignal(object)  # remote_notice.Notice (duyuru satırı)

    # Update check configuration - Edit these values directly in this file
    CURRENT_VERSION = "1.0.0"  # Update this version number when releasing
    UPDATE_CHECK_URL = "https://macik.com.tr/api/updates/check"  
    APP_NAME = "TransferTCP"
    CHECK_INTERVAL_HOURS = 24  # Check once per day
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_config()
        self.logger = get_logger()
        self.current_version = self.CURRENT_VERSION
        self.last_check_time: Optional[datetime] = None
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_for_updates)
        self._auto_thread: Optional[_AutoCheckThread] = None
        self._manual_thread: Optional[_ManualCheckThread] = None
        
    def start(self):
        """Start automatic update checking"""
        if not self.config.get('advanced', 'auto_update_check', True):
            self.logger.info("Auto update check is disabled")
            return
        
        # Check immediately on start (if not checked recently)
        self._check_if_needed()
        
        # Set up periodic checks (every 24 hours)
        self.check_timer.start(self.CHECK_INTERVAL_HOURS * 3600 * 1000)  # Convert to milliseconds
        self.logger.info("Update checker started")
    
    def stop(self):
        """Stop automatic update checking"""
        self.check_timer.stop()
        if self._auto_thread is not None and self._auto_thread.isRunning():
            self._auto_thread.wait(12000)
        if self._manual_thread is not None and self._manual_thread.isRunning():
            self._manual_thread.wait(12000)
        self.logger.info("Update checker stopped")
    
    def _check_if_needed(self):
        """Check if update check is needed based on last check time"""
        last_check_str = self.config.get('advanced', 'last_update_check', None)
        
        if last_check_str:
            try:
                self.last_check_time = datetime.fromisoformat(last_check_str)
                # Check if 24 hours have passed
                if datetime.now() - self.last_check_time < timedelta(hours=self.CHECK_INTERVAL_HOURS):
                    self.logger.debug("Update check skipped - checked recently")
                    return
            except Exception as e:
                self.logger.warning(f"Failed to parse last check time: {e}")
        
        # Perform check
        self.check_for_updates()
    
    def check_for_updates(self, show_message: bool = False):
        """Güncellemeyi kontrol et; ağ işlemi UI iş parçacığını bloklamaz."""
        if show_message:
            if self._manual_thread is not None and self._manual_thread.isRunning():
                return
            self._manual_thread = _ManualCheckThread(self, self)
            self._manual_thread.finished.connect(self._on_manual_check_finished)
            self._manual_thread.start()
            return
        if self._auto_thread is not None and self._auto_thread.isRunning():
            return
        self._auto_thread = _AutoCheckThread(self, self)
        self._auto_thread.finished.connect(self._on_auto_check_finished)
        self._auto_thread.start()

    def _on_auto_check_finished(self):
        thread = self.sender()
        if thread is self._auto_thread:
            self._auto_thread = None

    def _on_manual_check_finished(self):
        thread = self.sender()
        if thread is self._manual_thread:
            self._manual_thread = None
        self.manual_check_finished.emit()

    def _check_for_updates_sync(self, show_message: bool = False):
        """
        Check for available updates
        
        Args:
            show_message: If True, show message even if no update is available
        """
        if not show_message and not self.config.get('advanced', 'auto_update_check', True):
            return

        self.logger.info("Checking for updates...")
        
        try:
            # Build URL with parameters
            params = {
                'appName': self.APP_NAME,
                'currentVersion': self.current_version
            }
            url = f"{self.UPDATE_CHECK_URL}?{urllib.parse.urlencode(params)}"
            
            # Fetch latest release info from API
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'AppUpp/1.0 TransferTCP-UpdateChecker')
            
            # Create SSL context - skip verification for localhost (development)
            parsed_url = urllib.parse.urlparse(url)
            is_localhost = is_local_dev_host(parsed_url.hostname)
            
            if is_localhost:
                # Geliştirme: yalnızca paketlenmemiş çalışmada localhost için sertifika denetimi atlanır
                ssl_context = ssl._create_unverified_context()
            else:
                # Use default SSL context for production
                ssl_context = None
            
            # Increase timeout and handle errors gracefully
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                data = json.loads(response.read().decode())
                if not isinstance(data, dict):
                    raise ValueError("güncelleme yanıtı bir JSON nesnesi değil")
                
                # API'den gelen JSON formatı:
                # {
                #   "updateAvailable": true,
                #   "version": "1.0.2",
                #   "download_url": "https://macik.com.tr/downloads/TransferTCP_Setup_1.0.2.exe",
                #   "release_notes": "Hata düzeltmeleri...",
                #   "isMandatory": false,
                #   "fileSize": 15728640,
                #   "checksum": "sha256_hash_here"
                # }
                
                notice = parse_notice(data, get_active_language(self.config))
                if notice is not None:
                    self.notice_received.emit(notice)

                update_available = as_bool(data.get('updateAvailable', False))

                if not update_available:
                    self.logger.info("Application is up to date")
                    self.check_complete.emit(False)
                    if show_message:
                        lang = get_active_language(self.config)
                        self.check_message.emit(
                            "info",
                            t("update_check_title", lang),
                            t("update_current", lang).format(version=self.current_version),
                        )
                    self.config.set('advanced', 'last_update_check', datetime.now().isoformat())
                    return

                latest_version = as_text(data.get('version', '')).lstrip('vV')
                download_url = as_text(data.get('download_url', ''))
                release_notes = as_text(data.get('release_notes', ''))
                is_mandatory = as_bool(data.get('isMandatory', False))
                file_size = as_size(data.get('fileSize', 0))
                checksum = as_text(data.get('checksum', ''))

                if not latest_version or not download_url:
                    self.logger.warning("Invalid update response: missing version or download_url")
                    self._report_check_failed(show_message)
                    return

                url_ok, url_reason = validate_update_url(download_url)
                if not url_ok:
                    # Güvenilmeyen/HTTPS olmayan adres: kullanıcıya sunulmaz, hiç indirilmez
                    self.logger.warning(f"Güncelleme adresi reddedildi: {url_reason} ({download_url})")
                    self._report_check_failed(show_message)
                    return

                newer = self._compare_versions(latest_version, self.current_version) > 0
                if newer and self.skipped_version() == latest_version:
                    # Bu sürüm bu bilgisayarda açılışta ölüp geri alındı: bir daha önerilmez ("güncel" sayılır)
                    self.logger.info(f"Sürüm {latest_version} bu bilgisayarda geri alınmıştı: önerilmiyor")
                    newer = False

                if newer:
                    self.logger.info(f"Update available: {latest_version} (mandatory: {is_mandatory})")
                    self.update_available.emit(
                        latest_version,
                        download_url,
                        release_notes,
                        is_mandatory,
                        file_size,
                        checksum
                    )
                    self.check_complete.emit(True)
                    # Damga ATILMAZ: bekleyen güncelleme varken uygulama yeniden açılırsa (ya da indirme yarıda
                    # kalırsa) bir sonraki açılış hemen yeniden denetler; yoksa tepsi/düğme 24 saat kaybolurdu.
                    return

                self.logger.info("Application is up to date")
                self.check_complete.emit(False)
                if show_message:
                    lang = get_active_language(self.config)
                    self.check_message.emit(
                        "info",
                        t("update_check_title", lang),
                        t("update_current", lang).format(version=self.current_version),
                    )
                self.config.set('advanced', 'last_update_check', datetime.now().isoformat())

        except urllib.error.URLError as e:
            # Don't log timeout errors as errors, just debug
            error_msg = str(e).lower()
            if "timed out" in error_msg or "timeout" in error_msg:
                self.logger.debug(f"Update check timed out")
            else:
                self.logger.debug(f"Failed to check for updates: {e}")
            self._report_check_failed(show_message)
        except Exception as e:
            self.logger.debug(f"Unexpected error checking for updates: {e}")
            self._report_check_failed(show_message)

    def _report_check_failed(self, show_message: bool) -> None:
        """Denetim yapılamadı (çevrimdışı, sunucu hatası, bozuk yanıt): elle denetimde "Güncel" DEĞİL,
        "Denetlenemedi" gösterilsin (ayarlar penceresi uyarı düzeyini başarısızlık sayar)."""
        self.check_failed.emit()
        self.check_complete.emit(False)
        if show_message:
            lang = get_active_language(self.config)
            self.check_message.emit(
                "warning",
                t("update_check_title", lang),
                t("update_check_failed_msg", lang),
            )

    @staticmethod
    def skipped_version() -> Optional[str]:
        """Bu bilgisayarda açılışta ölüp geri alınan sürüm (yalnızca paketlenmiş çalışmada; yoksa None)."""
        if not is_frozen():
            return None
        try:
            return self_update.skipped_version(sys.executable)
        except Exception:
            return None

    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two version strings
        
        Returns:
            1 if version1 > version2
            -1 if version1 < version2
            0 if version1 == version2
        """
        try:
            v1_parts = [int(x) for x in version1.split('.')]
            v2_parts = [int(x) for x in version2.split('.')]
            
            # Pad with zeros if needed
            max_len = max(len(v1_parts), len(v2_parts))
            v1_parts += [0] * (max_len - len(v1_parts))
            v2_parts += [0] * (max_len - len(v2_parts))
            
            for v1, v2 in zip(v1_parts, v2_parts):
                if v1 > v2:
                    return 1
                elif v1 < v2:
                    return -1
            
            return 0
        except Exception:
            # If comparison fails, assume versions are equal
            return 0
    
    def get_current_version(self) -> str:
        """Get current application version"""
        return self.current_version

