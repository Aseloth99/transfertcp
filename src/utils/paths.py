"""Kullanıcı dizinleri — Windows AppData, macOS Application Support, Linux XDG."""

from __future__ import annotations

import os
import sys
from typing import Optional, Tuple

from .fileio import ensure_private_dir
from .platform_utils import MACOS, WINDOWS, current_platform

APP_ID = "TransferTCP"
# macOS paket kimliği (Info.plist CFBundleIdentifier, LaunchAgent etiketi); macik.com.tr ters alan adı
BUNDLE_ID = "tr.com.macik.transfertcp"


def get_application_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_bundle_dir() -> str:
    """Return PyInstaller temporary bundle directory if frozen, else project root."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", get_application_path())
    return get_application_path()


def get_asset_path(*subpaths: str) -> str:
    """Return absolute path to an asset, checking PyInstaller bundle (_MEIPASS) first."""
    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", get_application_path())
        bundled = os.path.join(mei, "assets", *subpaths)
        if os.path.exists(bundled):
            return bundled
    base = get_application_path()
    return os.path.join(base, "assets", *subpaths)


def _env_dir(env, name: str) -> Optional[str]:
    """XDG değişkeni yalnızca MUTLAK yol ise geçerlidir (XDG Base Directory belirtimi)."""
    value = (env.get(name) or "").strip()
    return value if value and os.path.isabs(value) else None


def _home(home: Optional[str]) -> str:
    return home if home is not None else os.path.expanduser("~")


def get_user_config_dir(app_id: str = APP_ID, *, platform: Optional[str] = None,
                        env=None, home: Optional[str] = None) -> str:
    """Ayar dosyaları: Windows %APPDATA%, macOS ~/Library/Application Support, Linux $XDG_CONFIG_HOME."""
    env = os.environ if env is None else env
    kind = current_platform(platform)
    if kind == WINDOWS:
        base = env.get("APPDATA") or os.path.join(_home(home), "AppData", "Roaming")
        return os.path.join(base, app_id)
    if kind == MACOS:
        return os.path.join(_home(home), "Library", "Application Support", app_id)
    xdg = _env_dir(env, "XDG_CONFIG_HOME") or os.path.join(_home(home), ".config")
    return os.path.join(xdg, app_id)


def get_user_data_dir(app_id: str = APP_ID, *, platform: Optional[str] = None,
                      env=None, home: Optional[str] = None) -> str:
    """Veri (veritabanı, kimlik, güvenilen cihazlar): Windows %LOCALAPPDATA%, macOS Application Support,
    Linux $XDG_DATA_HOME (~/.local/share)."""
    env = os.environ if env is None else env
    kind = current_platform(platform)
    if kind == WINDOWS:
        base = env.get("LOCALAPPDATA") or os.path.join(_home(home), "AppData", "Local")
        return os.path.join(base, app_id)
    if kind == MACOS:
        return os.path.join(_home(home), "Library", "Application Support", app_id)
    xdg = _env_dir(env, "XDG_DATA_HOME") or os.path.join(_home(home), ".local", "share")
    return os.path.join(xdg, app_id)


def get_user_log_dir(app_id: str = APP_ID, *, platform: Optional[str] = None,
                     env=None, home: Optional[str] = None) -> str:
    """Günlükler: Windows <LOCALAPPDATA>/TransferTCP/logs (DEĞİŞMEDİ), macOS ~/Library/Logs/TransferTCP,
    Linux $XDG_STATE_HOME/TransferTCP/logs (varsayılan ~/.local/state)."""
    env = os.environ if env is None else env
    kind = current_platform(platform)
    if kind == MACOS:
        return os.path.join(_home(home), "Library", "Logs", app_id)
    if kind == WINDOWS:
        return os.path.join(get_user_data_dir(app_id, platform=platform, env=env, home=home), "logs")
    state = _env_dir(env, "XDG_STATE_HOME") or os.path.join(_home(home), ".local", "state")
    return os.path.join(state, app_id, "logs")


def _qt_download_location() -> Optional[str]:
    """Qt'nin bildirdiği İndirilenler klasörü (Windows bilinen klasör, macOS, XDG user-dirs); yoksa None."""
    try:
        from PyQt6.QtCore import QStandardPaths
        path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        return path or None
    except Exception:
        return None


def get_default_download_dir(*, platform: Optional[str] = None, env=None, home: Optional[str] = None,
                             qt_lookup=_qt_download_location) -> str:
    """Varsayılan indirme klasörü: QStandardPaths.DownloadLocation → ~/Downloads → <veri>/downloads.

    Önceki sürümlerde indirme klasörü boşsa dosyalar çalışma dizinine (uygulama klasörüne; macOS'ta .app
    paketinin içine) yazılırdı. Dizin burada OLUŞTURULMAZ (alıcı gerektiğinde oluşturur); aday ya
    vardır ya da üst dizini (ev) vardır, aksi halde veri dizinindeki "downloads" kullanılır.
    """
    candidates = []
    try:
        found = qt_lookup() if qt_lookup is not None else None
    except Exception:
        found = None
    if found and os.path.isabs(found):
        candidates.append(found)
    candidates.append(os.path.join(_home(home), "Downloads"))
    for candidate in candidates:
        if os.path.isdir(candidate) or os.path.isdir(os.path.dirname(candidate)):
            return candidate
    return os.path.join(get_user_data_dir(platform=platform, env=env, home=home), "downloads")


def get_download_folder(configured: Optional[str] = None, **kwargs) -> str:
    """Ayarlardaki indirme klasörünü çözer: boş → varsayılan; `~` açılır; göreli yol ev dizinine bağlanır
    (cwd'ye değil: kurulu uygulamada cwd yazılamayan bir yer olabilir). Mutlak yollar AYNEN döner."""
    value = (configured or "").strip()
    if not value:
        return get_default_download_dir(**kwargs)
    value = os.path.expanduser(value)
    if not os.path.isabs(value):
        value = os.path.join(_home(kwargs.get("home")), value)
    return value


def resolve_user_config(filename: str = "config.json", app_id: str = APP_ID,
                        app_dir: Optional[str] = None) -> Tuple[str, Optional[str]]:
    user_dir = get_user_config_dir(app_id)
    ensure_private_dir(user_dir)  # POSIX: 0700 (kişisel ayarlar); Windows: yalnızca makedirs
    user_path = os.path.join(user_dir, filename)
    if os.path.isfile(user_path):
        return user_path, None
    app_dir = app_dir or get_application_path()
    seen = set()
    for candidate in (os.path.join(app_dir, filename), os.path.join(os.getcwd(), filename)):
        norm = os.path.normcase(os.path.abspath(candidate))
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isfile(candidate):
            return user_path, candidate
    return user_path, None
