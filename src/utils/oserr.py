"""OSError / errno / winerror tabanlı hata sınıflandırma.

Hata MESAJI içinde "5", "32", "112" gibi rakam aramak yanlış pozitif verir (yol, dosya adı,
bayt sayısı vb. içindeki rakamlar). Burada gerçek `errno` / `winerror` / istisna türü kullanılır.
"""

from __future__ import annotations

import errno
import socket
from typing import Iterator, Optional

# Windows hata kodları (winerror)
_WIN_DISK_FULL = {39, 112}                 # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
_WIN_LOCKED = {32, 33}                     # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
_WIN_ACCESS = {5}                          # ERROR_ACCESS_DENIED
_WIN_INVALID_NAME = {123, 161, 206}        # ERROR_INVALID_NAME, ERROR_BAD_PATHNAME, ERROR_FILENAME_EXCED_RANGE
_WIN_NOT_FOUND = {2, 3}                    # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND
_WIN_CONN_RESET = {10053, 10054, 10058}    # WSAECONNABORTED, WSAECONNRESET, WSAESHUTDOWN
_WIN_TIMEOUT = {10060}                     # WSAETIMEDOUT
_WIN_REFUSED = {10061}                     # WSAECONNREFUSED
_WIN_UNREACHABLE = {10050, 10051, 10064, 10065}  # ağ/host ulaşılamıyor

DISK_FULL = "disk_full"
LOCKED = "locked"
ACCESS_DENIED = "access_denied"
INVALID_NAME = "invalid_name"
NOT_FOUND = "not_found"
CONN_RESET = "conn_reset"
TIMEOUT = "timeout"
REFUSED = "refused"
UNREACHABLE = "unreachable"


def iter_exception_chain(error: BaseException, limit: int = 8) -> Iterator[BaseException]:
    """Hata + sarmalanmış özgün hata (`original`) + __cause__ / __context__ zinciri."""
    seen = set()
    stack = [error]
    while stack and len(seen) < limit:
        current = stack.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for attr in ("original", "__cause__", "__context__"):
            nxt = getattr(current, attr, None)
            if isinstance(nxt, BaseException):
                stack.append(nxt)


def find_os_error(error: BaseException) -> Optional[OSError]:
    for item in iter_exception_chain(error):
        if isinstance(item, OSError):
            return item
    return None


def classify_os_error(error: BaseException) -> Optional[str]:
    """Hata zincirindeki OSError'u kategoriye çevirir; tanınmazsa None."""
    for item in iter_exception_chain(error):
        if not isinstance(item, OSError):
            continue
        winerror = getattr(item, "winerror", None)
        number = item.errno

        if winerror in _WIN_DISK_FULL or number in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
            return DISK_FULL
        if winerror in _WIN_LOCKED:
            return LOCKED
        if winerror in _WIN_ACCESS or number in (errno.EACCES, errno.EPERM) or isinstance(item, PermissionError):
            return ACCESS_DENIED
        if winerror in _WIN_INVALID_NAME or number in (errno.EINVAL, getattr(errno, "ENAMETOOLONG", -1)):
            return INVALID_NAME
        if isinstance(item, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)) \
                or winerror in _WIN_CONN_RESET or number in (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE):
            return CONN_RESET
        if isinstance(item, (socket.timeout, TimeoutError)) or winerror in _WIN_TIMEOUT or number == errno.ETIMEDOUT:
            return TIMEOUT
        if isinstance(item, ConnectionRefusedError) or winerror in _WIN_REFUSED or number == errno.ECONNREFUSED:
            return REFUSED
        if winerror in _WIN_UNREACHABLE or number in (errno.ENETUNREACH, errno.EHOSTUNREACH,
                                                      getattr(errno, "ENETDOWN", -1)):
            return UNREACHABLE
        if winerror in _WIN_NOT_FOUND or number == errno.ENOENT or isinstance(item, FileNotFoundError):
            return NOT_FOUND
    return None
