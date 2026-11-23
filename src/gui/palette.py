"""Vurgu renkleri ve ortak palet.

Tek kaynak: ana pencere (QSS'e vurgu işleme), özel kutular/çerçeveli pencereler (`message_box.configure`),
menü/tepsi simgeleri (seçilen vurguya göre boyanır) ve ayarlardaki vurgu seçici buradan okur.
Onaltılık değerler MediaCompressor/FlexiKey ile aynı Material ailesidir (aynı "Turkuaz" her uygulamada aynı).
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from ..utils.config import get_config
from ..utils.locales import configured_language, t

DEFAULT_ACCENT = "cyan"

ACCENTS = {
    "cyan": {"label_key": "accent_cyan", "accent": "#00ACC1", "accent2": "#00838F", "hi_dark": "#4DD0E1", "hi_light": "#80DEEA"},
    "blue": {"label_key": "accent_blue", "accent": "#2196F3", "accent2": "#1976D2", "hi_dark": "#42A5F5", "hi_light": "#90CAF9"},
    "teal": {"label_key": "accent_teal", "accent": "#00897B", "accent2": "#00695C", "hi_dark": "#4DB6AC", "hi_light": "#80CBC4"},
    "indigo": {"label_key": "accent_indigo", "accent": "#3F51B5", "accent2": "#303F9F", "hi_dark": "#7986CB", "hi_light": "#9FA8DA"},
    "violet": {"label_key": "accent_violet", "accent": "#7C4DFF", "accent2": "#651FFF", "hi_dark": "#B388FF", "hi_light": "#D1C4E9"},
    "rose": {"label_key": "accent_rose", "accent": "#E91E63", "accent2": "#C2185B", "hi_dark": "#F06292", "hi_light": "#F8BBD0"},
    "orange": {"label_key": "accent_orange", "accent": "#FB8C00", "accent2": "#EF6C00", "hi_dark": "#FFB74D", "hi_light": "#FFE0B2"},
    "red": {"label_key": "accent_red", "accent": "#E53935", "accent2": "#C62828", "hi_dark": "#EF5350", "hi_light": "#FFCDD2"},
    "green": {"label_key": "accent_green", "accent": "#43A047", "accent2": "#2E7D32", "hi_dark": "#66BB6A", "hi_light": "#C8E6C9"},
    "yellow": {"label_key": "accent_yellow", "accent": "#F9A825", "accent2": "#F57F17", "hi_dark": "#FDD835", "hi_light": "#FFF59D"},
}

# Nötr gri aileler (SPEC §1.4): koyu = MediaCompressor DARK, açık = MediaCompressor LIGHT
_DARK = {"base": "#1a1a1a", "raised": "#2a2a2a", "surface": "#252525", "border": "#1a1a1a", "hi": "#3a3a3a",
         "text": "#e8e8e8", "text_muted": "#9e9e9e", "danger": "#d32f2f", "warn": "#FFC107"}
_LIGHT = {"base": "#e0e0e0", "raised": "#f5f5f5", "surface": "#ececec", "border": "#c5c5c5", "hi": "#ffffff",
          "text": "#1a1a1a", "text_muted": "#616161", "danger": "#e53935", "warn": "#8A5300"}


def accent_label(key: str, lang: str | None = None) -> str:
    spec = ACCENTS.get(key) or ACCENTS[DEFAULT_ACCENT]
    return t(spec["label_key"], lang)


_override: str | None = None  # ayarlardaki canlı önizleme: kaydedilmeden denenen vurgu


def set_accent_override(key: str | None) -> None:
    """Kaydedilmemiş (önizleme) vurguyu uygula; None kayıtlı vurguya döner."""
    global _override
    _override = key if key in ACCENTS else None


def accent_key() -> str:
    """Geçerli vurgu anahtarı: önizleme varsa o, yoksa ayarlardaki kayıtlı değer (geçersizse varsayılan)."""
    if _override is not None:
        return _override
    try:
        key = get_config().get("ui", "accent", DEFAULT_ACCENT)
    except Exception:
        key = DEFAULT_ACCENT
    return key if key in ACCENTS else DEFAULT_ACCENT


def accent_spec(key: str | None = None) -> dict:
    return ACCENTS.get(key or accent_key()) or ACCENTS[DEFAULT_ACCENT]


def is_dark() -> bool:
    """Uygulanan temanın koyu olup olmadığı (`MainWindow.apply_theme` QApplication'a `tt_dark` yazar; yoksa koyu)."""
    app = QApplication.instance()
    value = app.property("tt_dark") if app is not None else None
    return True if value is None else bool(value)


def accent_color() -> str:
    """Menü/tepsi simgeleri için seçili vurgu rengi ("#RRGGBB"); başlıktaki "Renk" örneği ve üst çizgiyle aynı ton."""
    return accent_spec()["accent"]


def tcp_palette() -> dict:
    """Özel kutu ve çerçeveli pencereler için palet (`message_box.configure(palette_provider=…)`)."""
    spec = accent_spec()
    base = dict(_DARK if is_dark() else _LIGHT)
    base["accent"] = spec["accent"]
    base["accent2"] = spec["accent2"]
    return base


def _rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: str, b: str, amount: float) -> str:
    """`a`'dan `b`'ye `amount` oranında opak karışım (#rrggbb)."""
    (ra, ga, ba), (rb, gb, bb) = _rgb(a), _rgb(b)
    return "#" + "".join(f"{max(0, min(255, round(x + (y - x) * amount))):02x}"
                         for x, y in ((ra, rb), (ga, gb), (ba, bb)))


def _luminance(color: str) -> float:
    def lin(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable(color: str, background: str, target: float = 4.5) -> str:
    """`color`'ı, `background` üzerinde `target` kontrastına ulaşana dek (koyu zeminde beyaza, açıkta siyaha) çeker."""
    if _contrast(color, background) >= target:
        return color
    toward = "#ffffff" if _luminance(background) < 0.4 else "#000000"
    for step in range(1, 21):
        candidate = _mix(color, toward, step / 20.0)
        if _contrast(candidate, background) >= target:
            return candidate
    return toward


# Ayarlar kenar çubuğunun zemini (dark.qss / light.qss `QFrame#sidebar`): Lumina'daki `surface` ile aynı
SIDEBAR_BG = {"dark": "#252525", "light": "#ececec"}


def nav_colors(theme: str, key: str | None = None) -> tuple[str, str]:
    """Ayarlar kenar çubuğunda seçili sekme (Lumina ile aynı kural): zemine %16 (koyu) / %13 (açık) vurgu karışmış
    hafif zemin ve onun üstünde en az 4,5:1 okunan vurgu yazısı. (`__NAV_TINT__`, `__NAV_INK__`)"""
    dark = theme == "dark"
    spec = accent_spec(key)
    tint = _mix(SIDEBAR_BG["dark" if dark else "light"], spec["accent"], 0.16 if dark else 0.13)
    return tint, readable(spec["hi_dark"] if dark else spec["accent2"], tint, 4.5)


def install_message_box() -> None:
    """Özel kutuyu TCP paletine/simgesine/diline bağlar (idempotent; ana pencereden ÖNCE çağrılır)."""
    from . import message_box

    message_box.configure(
        palette_provider=tcp_palette,
        app_icon_provider=lambda: QApplication.windowIcon(),
        lang_provider=configured_language,
    )
