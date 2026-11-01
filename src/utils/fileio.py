"""Güvenli dosya yazımı: atomik JSON/metin yazımı, bozuk dosya yedekleme, POSIX izinleri."""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
import time
from typing import Any, Optional

from .platform_utils import is_windows

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def _log() -> logging.Logger:
    # Uygulama günlükçüsüyle aynı ad (işleyiciler Logger() yaratılınca eklenir); döngüsel içe aktarma yok
    return logging.getLogger("TransferTCP")


def ensure_private_dir(path: str, mode: int = PRIVATE_DIR_MODE, platform: Optional[str] = None) -> bool:
    """Dizini oluşturur; POSIX'te yalnızca sahibine açık (0700) olmasını sağlar. Windows'ta yalnızca makedirs.

    `os.chmod` sonucu doğrulanır: grup/diğer bitleri hâlâ açıksa uyarı günlüğe yazılır ve False döner.
    """
    if is_windows(platform):
        os.makedirs(path, exist_ok=True)
        return True
    os.makedirs(path, mode=mode, exist_ok=True)  # yalnızca yaprak dizine uygulanır (üst dizinlere dokunmaz)
    return restrict_permissions(path, mode)


def restrict_permissions(path: str, mode: int, platform: Optional[str] = None) -> bool:
    """Dosya/dizin izinlerini en fazla `mode` yapar (POSIX). Windows'ta hiçbir şey yapmaz (True).

    Mevcut izinlerde `mode` dışındaki grup/diğer bitleri açıksa `os.chmod` çağrılır ve sonuç yeniden
    okunarak doğrulanır; başarısızlık bir uyarıyla bildirilir (sessizce yutulmaz).
    """
    if is_windows(platform):
        return True
    try:
        current = stat.S_IMODE(os.stat(path).st_mode)
    except OSError as exc:
        _log().warning(f"İzinler okunamadı ({path}): {exc}")
        return False
    if not (current & ~mode & 0o777):
        return True  # zaten en fazla `mode` kadar açık
    try:
        os.chmod(path, mode)
        after = stat.S_IMODE(os.stat(path).st_mode)
    except OSError as exc:
        _log().warning(f"İzinler {oct(mode)} yapılamadı ({path}): {exc}")
        return False
    if after & ~mode & 0o777:
        _log().warning(f"İzinler hâlâ gevşek ({path}): {oct(after)} (istenen {oct(mode)})")
        return False
    return True


def atomic_write_bytes(path: str, payload: bytes, *, mode: Optional[int] = None) -> None:
    """tmp dosyaya yaz + flush + fsync + os.replace (yarım yazılmış hedef bırakmaz).

    `mode` verilirse (POSIX) tmp dosya baştan o izinlerle yaratılır (ör. özel anahtar için 0600):
    içerik, herkese açık izinlerle yazılıp sonradan chmod edilmez. Windows'ta `mode` yok sayılır.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    # Thread başına benzersiz ad: aynı dosyaya eşzamanlı yazanlar birbirinin tmp'sini ezmesin
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        if mode is not None and not is_windows():
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            handle = os.fdopen(fd, "wb")
        else:
            handle = open(tmp_path, "wb")
        with handle:
            if mode is not None and not is_windows():
                try:
                    os.fchmod(handle.fileno(), mode)  # umask'tan bağımsız kesin izin
                except (AttributeError, OSError):
                    pass
            handle.write(payload)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path: str, text: str, encoding: str = "utf-8", *, mode: Optional[int] = None) -> None:
    atomic_write_bytes(path, text.encode(encoding), mode=mode)


def atomic_write_json(path: str, data: Any, *, indent: Optional[int] = 2, mode: Optional[int] = None) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False), mode=mode)


def hash_file_prefix(hasher: Any, path: str, nbytes: int, *, block: int = 1024 * 1024,
                     should_stop: Optional[Any] = None) -> int:
    """Dosyanın ilk `nbytes` baytını `hasher`a besler (devam edilen önek için).

    Dosya beklenenden kısaysa ValueError fırlatır. `should_stop()` True dönerse erken çıkar.
    Okunan bayt sayısını döndürür.
    """
    remaining = nbytes
    with open(path, "rb") as handle:
        while remaining > 0:
            if should_stop is not None and should_stop():
                break
            data = handle.read(min(block, remaining))
            if not data:
                raise ValueError(f"Dosya beklenenden kısa: {path} ({nbytes - remaining}/{nbytes} bayt)")
            hasher.update(data)
            remaining -= len(data)
    return nbytes - remaining


def backup_corrupt_file(path: str) -> Optional[str]:
    """Bozuk dosyayı `<ad>.corrupt-YYYYmmdd-HHMMSS` olarak yan tarafa taşır; yeni yolu döndürür.

    Böylece varsayılana dönüp sonradan üzerine yazarken kullanıcının bozuk ama
    kurtarılabilir verisi sessizce kaybolmaz.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = f"{path}.corrupt-{stamp}"
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = f"{path}.corrupt-{stamp}-{counter}"
    try:
        os.replace(path, target)
        return target
    except OSError:
        return None
