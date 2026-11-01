"""Theme detection utilities"""

import os
import sys


def get_system_theme() -> str:
    """
    Detect OS theme (dark/light).

    Returns:
        "dark" or "light"
    """
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value == 1 else "dark"
        except Exception:
            return "dark"
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return "dark" if "Dark" in (out.stdout or "") else "light"
        except Exception:
            return "dark"
    theme = (os.environ.get("GTK_THEME", "") + " " + os.environ.get("QT_STYLE_OVERRIDE", "")).lower()
    return "dark" if "dark" in theme else "light"


def ui_font_families(platform: str | None = None) -> list[str]:
    """Arayüz yazı tipi aileleri, tercih sırasıyla (Qt ilk bulunanı kullanır).

    Windows'ta "Segoe UI" önce gelir (eski sabit değerle aynı); diğer platformlarda sistem yazı tipi.
    """
    plat = platform if platform is not None else sys.platform
    if plat == "win32":
        return ["Segoe UI", "Arial"]
    if plat == "darwin":
        return [".AppleSystemUIFont", "Helvetica Neue", "Arial"]
    return ["Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans", "Arial"]
