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


def install_message_box() -> None:
    """Özel kutuyu TCP paletine/simgesine/diline bağlar (idempotent; ana pencereden ÖNCE çağrılır)."""
    from . import message_box

    message_box.configure(
        palette_provider=tcp_palette,
        app_icon_provider=lambda: QApplication.windowIcon(),
        lang_provider=configured_language,
    )
