"""Bekleyen transferlerin durum metni seçimi — Qt'siz, saf ve test edilebilir.

Eskiden gönderici yuvası (aynı anda en fazla N gönderim) dolu olduğu için sırada bekleyen
transferler 0 B'de "Bekliyor..." gösteriyordu; kullanıcı bunu takılma sanıyordu. Burada
durumlar ayrılır:

* ``queued``    — sırada: başka gönderimler bitince başlayacak (üst sınır belirtilir)
* ``retrying``  — bağlantı koptu, yeniden deneniyor (deneme no ile)
* ``connecting``— bağlantı kuruluyor / alıcı onayı bekleniyor
* ``pending``   — oluşturuldu, henüz iş parçacığı yuvayı sormadı (çok kısa)
* ``other``     — aktarım/duraklatma/bitiş: bu modülün işi değil
"""

from __future__ import annotations

from typing import Optional, Tuple

from ..models.transfer import TransferStatus
from .locales import t

QUEUED = "queued"
RETRYING = "retrying"
CONNECTING = "connecting"
PENDING = "pending"
OTHER = "other"


def wait_state(transfer) -> str:
    """Transferin bekleme türünü döndürür (bkz. modül açıklaması)."""
    status = getattr(transfer, "status", None)
    if status == TransferStatus.CONNECTING:
        if int(getattr(transfer, "retry_attempt", 0) or 0) > 0:
            return RETRYING
        return CONNECTING
    if status == TransferStatus.PENDING:
        if getattr(transfer, "queued_for_slot", False):
            return QUEUED
        return PENDING
    return OTHER


def queued_text(limit: int, lang: Optional[str] = None) -> str:
    """"Sırada (aynı anda en fazla N)" metni."""
    return t("transfer_queued", lang).format(n=max(1, int(limit or 1)))


def retry_text(attempt: int, lang: Optional[str] = None) -> str:
    """"Yeniden deneniyor (n)..." metni."""
    return t("transfer_retrying", lang).format(n=int(attempt))


def wait_labels(transfer, lang: Optional[str] = None) -> Optional[Tuple[Optional[str], str, str]]:
    """Bekleyen transfer için ``(bilgi_metni | None, hız_alanı_metni, renk_anahtarı)`` döndürür.

    ``bilgi_metni`` None ise çağıran normal "boyut - cihaz" satırını bırakır. Bekleme
    durumunda değilse None döner (çağıran kendi mantığını sürdürür). Renk anahtarı:
    ``"warn"`` (turuncu), ``"muted"`` (gri).
    """
    state = wait_state(transfer)
    if state == QUEUED:
        return None, queued_text(getattr(transfer, "queue_limit", 0), lang), "muted"
    if state == RETRYING:
        return retry_text(transfer.retry_attempt, lang), t("status_retrying", lang), "warn"
    if state == CONNECTING:
        return None, t("status_waiting_approval", lang), "muted"
    if state == PENDING:
        return None, t("status_pending_short", lang), "muted"
    return None
