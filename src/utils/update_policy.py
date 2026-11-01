"""Güncelleme güvenlik politikası — Qt'siz, saf ve test edilebilir.

* İndirme adresi yalnızca HTTPS ve güvenilen alan adı (macik.com.tr ve alt alanları).
  Geliştirme sırasında (paketlenmemiş çalışmada) localhost'a izin verilir.
* SHA-256 sağlama toplamı 64 haneli onaltılık olmalı; bozuk biçim reddedilir.
* İndirilen paketin türü (exe / zip) adresin uzantısına değil İÇERİĞE bakılarak anlaşılır (`self_update.sniff_package`);
  yerel dosya adı sunucudan gelmez (sabit `<Uygulama>_Update.pkg`).
"""

from __future__ import annotations

import re
import sys
import urllib.parse

TRUSTED_DOMAIN = "macik.com.tr"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_UPDATE_BYTES = 600 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_local_dev_host(host: str | None) -> bool:
    """localhost yalnızca geliştirmede (paketlenmemiş) güvenilir sayılır."""
    return (host or "").lower() in LOCAL_HOSTS and not is_frozen()


def _is_trusted_remote(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host == TRUSTED_DOMAIN or host.endswith("." + TRUSTED_DOMAIN)


def validate_update_url(url: str) -> tuple[bool, str]:
    """(geçerli mi, neden). Gerçek indirme ve yönlendirme sonrası adres için kullanılır."""
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        host = parsed.hostname or ""
        scheme = (parsed.scheme or "").lower()
        port = parsed.port
    except ValueError:
        return False, "Geçersiz güncelleme adresi."
    if not host:
        return False, "Geçersiz güncelleme adresi."
    if parsed.username or parsed.password:
        return False, "Güncelleme adresinde kimlik bilgisi olamaz."
    if is_local_dev_host(host):
        return (scheme in {"http", "https"}, "Geçersiz güncelleme adresi.")
    if scheme != "https":
        return False, "Güncelleme yalnızca HTTPS ile indirilebilir."
    if port not in (None, 443):
        return False, "Güncelleme adresi beklenmeyen bir port kullanıyor."
    if not _is_trusted_remote(host):
        return False, f"Güncelleme adresi güvenilen bir sunucuya ait değil ({host})."
    return True, ""


def normalize_checksum(value) -> str | None:
    """Boş -> None (doğrulama yok). Dolu ama geçersiz biçim -> ValueError (reddet)."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.startswith("sha256:"):
        text = text[len("sha256:"):].strip()
    if not _SHA256_RE.match(text):
        raise ValueError("Sunucunun verdiği sağlama toplamı geçersiz biçimde.")
    return text
