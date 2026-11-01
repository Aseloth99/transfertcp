"""Platform tespiti — tek noktadan ve test için enjekte edilebilir.

Windows'a özgü hiçbir modül (winreg, winotify, msvcrt, ctypes.windll ...) bu modülde veya
başka bir modülde içe aktarma anında çalışmaz/yüklenmez; platforma özgü kod her zaman
işlevin içinde, burada tanımlı denetimlerin arkasında tembel (lazy) içe aktarılır.

Fonksiyonlar `platform` parametresi alır (varsayılan `sys.platform`); böylece macOS davranışı
Windows/Linux üzerinde, gerçek soket/kayıt defteri/dosya sistemi dokunulmadan test edilebilir.
"""

from __future__ import annotations

import sys
from typing import Optional

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"
OTHER = "other"


def current_platform(platform: Optional[str] = None) -> str:
    """`sys.platform` (veya verilen dize) → "windows" | "macos" | "linux" | "other"."""
    raw = sys.platform if platform is None else platform
    if raw in ("win32", "windows"):
        return WINDOWS
    if raw in ("darwin", "macos"):
        return MACOS
    if raw.startswith("linux"):
        return LINUX
    return OTHER


def is_windows(platform: Optional[str] = None) -> bool:
    return current_platform(platform) == WINDOWS


def is_macos(platform: Optional[str] = None) -> bool:
    return current_platform(platform) == MACOS


def is_linux(platform: Optional[str] = None) -> bool:
    return current_platform(platform) == LINUX


def is_posix(platform: Optional[str] = None) -> bool:
    """Windows dışındaki her platform (macOS, Linux, BSD ...)."""
    return current_platform(platform) != WINDOWS
