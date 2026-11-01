"""Alınan dosya adı/yolunun temizlenmesi — Windows, Linux ve macOS için güvenli yol üretimi.

Gönderen başka bir işletim sisteminden olabilir ve (kötü niyetli ise) rastgele bayt dizisi
gönderebilir. Hedef yol her zaman indirme klasörünün İÇİNDE kalır:

* `..`, `.`, mutlak yol, sürücü harfi, NUL ve ters eğik çizgi ayırıcıları atılır/çevrilir.
* Windows: ayrılmış aygıt adları (CON, PRN, AUX, NUL, COM1-9, LPT1-9, uzantılı olanlar dahil),
  `<>:"/\\|?*` ve kontrol karakterleri, sondaki boşluk/nokta. (Gönderen Linux'ta olup `a:b.txt`
  gibi Windows'ta geçersiz adlar gönderebilir; eskiden dosya açılamayıp transfer hata veriyordu.)
* Linux/macOS: NUL, kontrol karakterleri, `/`; macOS'ta ayrıca `:` (Finder'da `/` görünür).
  Her platformda: çift yönlü (bidi) denetim karakterleri (uzantı sahteciliği), eşleşmeyen
  vekil (surrogate) karakterler, aşırı uzun ad (uzantı korunarak bayt sınırına kısaltılır;
  `.part.meta` ve ` (n)` ekleri için pay bırakılır).
* Sembolik bağ kaçışı: hedefin üst dizini `realpath` ile indirme klasörünün içinde kalmalı.
* Büyük/küçük harf duyarsız disklerde (Windows, macOS varsayılanı) farklı harflerle gelen adlar
  `O_EXCL` ile rezerve edilir (bkz. server._claim_final_path); eşzamanlı `.part` yarışları için
  `fs_key` platforma uygun anahtar üretir.
"""

from __future__ import annotations

import ntpath
import os
import unicodedata
from typing import List, Optional

from .platform_utils import MACOS, WINDOWS, current_platform

# `.part.meta` (10 bayt) ve " (9999)" (7 bayt) ekleri 255 baytlık dosya adı sınırını aşmasın
MAX_COMPONENT_BYTES = 230
_MAX_EXT_BYTES = 32

_WINDOWS_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
    + ["COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"]
)
_WINDOWS_BAD_CHARS = frozenset('<>:"/\\|?*')
_BIDI_CONTROLS = frozenset(
    chr(c) for c in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)) + [0x200E, 0x200F, 0x061C]
)
DEFAULT_FILENAME = "received_file"


def _is_control(char: str) -> bool:
    code = ord(char)
    return code < 32 or code == 0x7F or 0x80 <= code <= 0x9F


def _truncate_bytes(text: str, limit: int) -> str:
    """UTF-8'de `limit` bayta kısaltır (karakteri ortadan bölmeden)."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", "ignore")


def sanitize_component(name: object, platform: Optional[str] = None,
                       max_bytes: int = MAX_COMPONENT_BYTES) -> str:
    """Tek bir dosya/klasör adı bileşenini hedef platform için güvenli hale getirir (asla boş/'.'/'..' dönmez)."""
    kind = current_platform(platform)
    text = name if isinstance(name, str) else ""
    # eşleşmeyen vekil karakterler UTF-8'e çevrilemez (open() UnicodeEncodeError): '?' olur
    text = text.encode("utf-8", "replace").decode("utf-8", "replace")

    cleaned = []
    for char in text:
        if _is_control(char) or char in _BIDI_CONTROLS:
            cleaned.append("_")
        elif char in "/\\":
            cleaned.append("_")
        elif kind == WINDOWS and char in _WINDOWS_BAD_CHARS:
            cleaned.append("_")
        elif kind == MACOS and char == ":":
            cleaned.append("_")
        else:
            cleaned.append(char)
    result = "".join(cleaned).strip()

    if kind == WINDOWS:
        result = result.rstrip(" .")  # Windows sondaki nokta/boşluğu sessizce atar (ad değişir/çakışır)
        stem = result.split(".", 1)[0].rstrip(" ")
        if stem.upper() in _WINDOWS_RESERVED:
            result = "_" + result

    if result in ("", ".", ".."):
        result = "_"

    if len(result.encode("utf-8")) > max_bytes:
        root, ext = os.path.splitext(result)
        if not root or len(ext.encode("utf-8")) > _MAX_EXT_BYTES:
            root, ext = result, ""
        root = _truncate_bytes(root, max_bytes - len(ext.encode("utf-8")))
        result = (root.rstrip(" .") if kind == WINDOWS else root) + ext
        if kind == WINDOWS and result.split(".", 1)[0].rstrip(" ").upper() in _WINDOWS_RESERVED:
            result = "_" + result
        if not result or result in (".", ".."):
            result = "_"
    return result


def split_relative(relative_path: Optional[str]) -> List[str]:
    """Göndericinin `relative_path`ini bileşenlere böler: her iki ayırıcı, boş/`.`/`..` bileşenler atılır."""
    if not isinstance(relative_path, str) or not relative_path:
        return []
    parts = relative_path.replace("\\", "/").split("/")
    return [part for part in parts if part.strip() not in ("", ".", "..")]


def _inside(base: str, target: str) -> bool:
    try:
        common = os.path.commonpath([os.path.normcase(base), os.path.normcase(target)])
    except ValueError:  # farklı sürücüler
        return False
    return common == os.path.normcase(base)


def resolve_target(base_folder: str, relative_path: Optional[str], filename: str,
                   platform: Optional[str] = None, on_fallback=None) -> str:
    """Alınan dosyanın hedef yolu (her zaman `base_folder` içinde).

    `relative_path` varsa (klasör transferi) bileşenleri hedefi belirler; yoksa `filename`.
    Güvenli yola düşülürse (`..`, sembolik bağ kaçışı...) `on_fallback(neden)` çağrılır (günlük için).
    """
    base_abs = os.path.abspath(base_folder)
    name_source = filename.replace("\\", "/") if isinstance(filename, str) else ""
    base_name = os.path.basename(name_source).strip()
    clean_name = sanitize_component(base_name, platform) if base_name else DEFAULT_FILENAME

    parts = [sanitize_component(part, platform) for part in split_relative(relative_path)]
    safe_default = os.path.join(base_abs, clean_name)
    target = os.path.abspath(os.path.join(base_abs, *parts)) if parts else safe_default

    if not _inside(base_abs, target):
        if on_fallback:
            on_fallback("indirme klasörü dışına çıkıyor")
        return safe_default

    # Sembolik bağ/junction ile kaçış: üst dizinin gerçek yolu indirme klasörünün gerçek yolunda kalmalı
    try:
        real_base = os.path.realpath(base_abs)
        real_parent = os.path.realpath(os.path.dirname(target))
    except (OSError, ValueError):
        real_base = real_parent = base_abs
    if not _inside(real_base, real_parent):
        if on_fallback:
            on_fallback("sembolik bağ indirme klasörü dışına çıkıyor")
        return safe_default
    return target


def fs_key(path: str, platform: Optional[str] = None) -> str:
    """Aynı dosyayı gösteren yolların aynı anahtarı üretmesi için (yarış/kilit tablosu anahtarı).

    Windows: normcase (büyük/küçük harf + eğik çizgi). macOS: varsayılan APFS/HFS+ büyük/küçük harf ve
    Unicode normalizasyonuna duyarsızdır → NFC + casefold. Linux: olduğu gibi (duyarlı).
    """
    absolute = os.path.abspath(path)
    kind = current_platform(platform)
    if kind == WINDOWS:
        return ntpath.normcase(absolute)
    if kind == MACOS:
        return unicodedata.normalize("NFC", absolute).casefold()
    return absolute
