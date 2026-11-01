"""Configuration management — kullanıcı dizinine yazar."""

import threading
from copy import deepcopy
from json import load
from os.path import isfile
from typing import Any, Dict, Optional

from .fileio import atomic_write_json, backup_corrupt_file
from .logger import get_logger
from .paths import APP_ID, get_application_path, get_default_download_dir, resolve_user_config
from .ports import DEFAULT_TRANSFER_PORT

# Eski sürümlerin varsayılan portları: yeni varsayılana taşınır
_LEGACY_DEFAULT_PORTS = (5000, 52980, 59144)


class ConfigManager:
    """Manage application configuration"""

    def __init__(self, config_file: str = "config.json"):
        user_path, seed_path = resolve_user_config(
            config_file, APP_ID, get_application_path()
        )
        self.config_file = user_path
        self._seed_file = seed_path
        self.config: Dict[str, Any] = {}
        self.logger = get_logger()
        # set()/save() birden çok thread'den (arayüz, sunucu) çağrılır
        self._lock = threading.RLock()
        self._default_config = {
            "general": {
                "device_name": "",
                "auto_start": False,
                "start_minimized": True,
                "notifications_enabled": True,
                "play_sounds": True,
                "first_run": True,
            },
            "transfer": {
                "download_folder": "",
                "port": DEFAULT_TRANSFER_PORT,
                "chunk_size": 1048576,
                "speed_limit": 0,
                "max_concurrent_transfers": 2,
                "auto_open_file": False,
                "overwrite_existing": True,
            },
            "ui": {
                "theme": "system",
                "language": "auto",
                "accent": "cyan",
            },
            "advanced": {
                "enable_logging": True,
                "log_level": "WARNING",
                "auto_update_check": True,
                "auto_update_install": True,
                "encryption_enabled": True,
                "accept_from_anyone": False,
                "last_update_check": None,
                "declined_update_version": None,
                "update_type": "auto",
                "dismissed_notice": "",
            },
        }
        self.load()

    def _merge(self, loaded: Any) -> Dict[str, Any]:
        result = deepcopy(self._default_config)
        if not isinstance(loaded, dict):
            return result
        for section, values in loaded.items():
            if isinstance(values, dict) and isinstance(result.get(section), dict):
                merged = dict(result[section])
                merged.update(values)
                result[section] = merged
            else:
                result[section] = values
        return result

    def _migrate_legacy_port(self):
        """Eski varsayılan portları (5000, 52980, 59144) yeni varsayılana taşı; geçersiz değeri düzelt.

        Eskiden `port >= 49152` olan HER port sıfırlanıyordu. Ayarlar arayüzü 1024–65535 arasını
        seçtirdiği için kullanıcının bilinçli seçimi (ör. 50000) her açılışta sessizce
        38520'ye dönüyordu. 49152+ IANA dinamik/geçici aralığıdır ve Windows'ta bazı bloklar
        (Hyper-V/WinNAT) rezerve olabilir; ama bunun gerçek çözümü yapılandırmayı değiştirmek
        değil, TCPServer.start()'ın bind sırasında yaptığı denemedir (kullanılamayan portta bir
        sonrakine kayıp yapılandırmayı günceller). Bu yüzden yalnızca bilinen eski varsayılanlar
        ve geçersiz değerler burada düzeltilir.
        """
        transfer = self.config.setdefault("transfer", {})
        port = transfer.get("port")
        modified = False
        invalid = isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535)
        if port in _LEGACY_DEFAULT_PORTS or invalid:
            transfer["port"] = DEFAULT_TRANSFER_PORT
            self.logger.info(
                f"Transfer portu güncellendi: {port} → {DEFAULT_TRANSFER_PORT}"
            )
            modified = True

        # Geçici veya geçersiz indirme klasörünü kullanıcı İndirilenler klasörüne yönlendir
        download_folder = transfer.get("download_folder", "")
        if download_folder and ("\\Temp\\" in download_folder or "/temp/" in download_folder.lower()):
            default_dl = get_default_download_dir()
            transfer["download_folder"] = default_dl
            self.logger.info(f"Geçici indirme klasörü düzeltildi: {download_folder} → {default_dl}")
            modified = True

        if modified:
            self.save()

    def load(self):
        """Kullanıcı config'ini yükle; tohum yalnızca kullanıcı dosyası yokken.

        Bozuk (geçersiz JSON / sözlük olmayan) kullanıcı dosyası `.corrupt-<zaman>` olarak
        yedeklenir ve varsayılana dönülür; böylece sonraki save() bozuk ama kurtarılabilir
        veriyi sessizce ezmez.
        """
        with self._lock:
            try:
                if isfile(self.config_file):
                    try:
                        with open(self.config_file, "r", encoding="utf-8") as f:
                            loaded = load(f)
                        if not isinstance(loaded, dict):
                            raise ValueError("config kök öğesi bir JSON nesnesi değil")
                    except ValueError as corrupt:  # JSONDecodeError ve UnicodeDecodeError dahil
                        self._recover_from_corrupt(corrupt)
                        return
                    self.config = self._merge(loaded)
                    self._migrate_legacy_port()
                    self.logger.info("Configuration loaded successfully")
                    return
                if self._seed_file and isfile(self._seed_file):
                    with open(self._seed_file, "r", encoding="utf-8") as f:
                        self.config = self._merge(load(f))
                    self._migrate_legacy_port()
                    self.save()
                    self.logger.info("Seed configuration copied to user config directory")
                    return
                self.config = deepcopy(self._default_config)
                self.save()
                self.logger.info("Created default configuration")
            except Exception as e:
                self.logger.error(f"Failed to load config: {e}")
                self.config = deepcopy(self._default_config)

    def _recover_from_corrupt(self, reason: Exception) -> None:
        backup = backup_corrupt_file(self.config_file)
        self.logger.error(
            f"Config bozuk ({reason}); {'yedeklendi: ' + backup if backup else 'yedeklenemedi'}, "
            "varsayılan ayarlar kullanılıyor"
        )
        self.config = deepcopy(self._default_config)
        if backup:
            # Bozuk dosya güvenle kenara alındı; yeni dosya varsayılanlarla yazılabilir
            self.save()

    def save(self):
        """Save configuration to the user config directory (atomik: tmp + fsync + os.replace)."""
        with self._lock:
            try:
                atomic_write_json(self.config_file, self.config)
                self.logger.info("Configuration saved successfully")
            except Exception as e:
                self.logger.error(f"Failed to save config: {e}")

    def get(self, section: str, key: str, default: Any = None) -> Any:
        try:
            return self.config.get(section, {}).get(key, default)
        except Exception:
            return default

    def set(self, section: str, key: str, value: Any):
        with self._lock:
            if section not in self.config:
                self.config[section] = {}
            self.config[section][key] = value
            self.save()

    def get_section(self, section: str) -> Dict[str, Any]:
        return self.config.get(section, {})

    def set_section(self, section: str, values: Dict[str, Any]):
        with self._lock:
            self.config[section] = values
            self.save()

    def reset_to_default(self):
        with self._lock:
            self.config = deepcopy(self._default_config)
            self.save()
        self.logger.info("Configuration reset to defaults")


_config_instance: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager()
    return _config_instance
