"""Sistem bildirimleri (Windows, macOS, Linux): ortak `utils/notify.py` (Notifier) üstünde ince sarmalayıcı.

Tek yol Qt'nin çapraz platform `QSystemTrayIcon.showMessage` çağrısıdır (Windows 10/11'de toast); tepsi yoksa macOS'ta
`osascript`, Linux'ta `notify-send`. Windows'ta alt süreç/PowerShell açılmaz; `winotify` kullanılmaz.
Bildirim AYARI (`notifications_enabled`) çağıran yerlerde okunur (davranış aynen korunur); burada ayar kapısı yoktur.
"""

from __future__ import annotations

from ..utils.notify import Notifier

_APP_NAME = "TransferTCP"
_DURATIONS_MS = {"short": 5000, "long": 10000}


class SystemToast:
    """Uygulama genelinde tek bildirim noktası: `SystemToast.show(başlık, ileti)`."""

    _notifier: Notifier | None = None

    @classmethod
    def configure(cls, tray_provider, icon_provider=None, **test_hooks) -> Notifier:
        """Tepsiyi/simgeyi bağlar (uygulama açılışında bir kez). `test_hooks`: Notifier'ın platform/runner/which/supports_messages."""
        cls._notifier = Notifier(
            _APP_NAME,
            tray_provider=tray_provider,
            icon_provider=icon_provider or (lambda: None),
            **test_hooks,
        )
        return cls._notifier

    @classmethod
    def reset(cls) -> None:
        cls._notifier = None

    @classmethod
    def notifier(cls) -> Notifier:
        if cls._notifier is None:
            cls._notifier = Notifier(_APP_NAME)  # tepsisiz: yalnızca macOS/Linux araçları (Windows'ta bir şey olmaz)
        return cls._notifier

    @staticmethod
    def show(title: str, message: str, icon: str = None, duration: str = "short", *, critical: bool = False) -> bool:
        """Bildirimi gösterir; gösterildiyse True. `duration`: "short" (5 sn) | "long" (10 sn). `icon` yoksayılır
        (uygulama simgesi Notifier'a `configure(icon_provider=…)` ile verilir). Hiçbir yol istisna fırlatmaz."""
        timeout = _DURATIONS_MS.get(duration, _DURATIONS_MS["short"])
        return SystemToast.notifier().notify(title, message, critical=critical, timeout_ms=timeout)
