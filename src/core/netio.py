"""Güvenilir TCP / TLS soket I/O — STARTTLS sonrası kopmaları azaltır.

Platform farkları (hepsi `platform=` ile enjekte edilebilir, varsayılan `sys.platform`):

* TCP keepalive: Windows `SIO_KEEPALIVE_VALS`; Linux `TCP_KEEPIDLE/INTVL/CNT`; macOS
  `TCP_KEEPALIVE` (boşta süre) + `TCP_KEEPINTVL/CNT`. Var olan seçenek uygulanır, yoksa atlanır.
* Dinleme soketi: Windows `SO_EXCLUSIVEADDRUSE`; Linux/macOS `SO_REUSEADDR` (hızlı yeniden başlatmada
  TIME_WAIT'e takılmamak için). `SO_REUSEPORT` TCP'de KULLANILMAZ: iki örnek aynı porta bağlanıp gelen
  bağlantıları sessizce bölüştürürdü.
* Keşif (UDP) soketi: üç platformda da özel kullanım (Linux/macOS'ta REUSEADDR/REUSEPORT yok):
  ikinci yerel örnek EADDRINUSE alır ve keşif yedek portlarına (38522/38523) geçer; aksi halde
  iki süreç aynı UDP portunu paylaşır, yanıtlar (unicast) birine gider ve diğeri cihazları göremezdi.
  UDP'de TIME_WAIT yoktur, yani REUSEADDR'in kazandıracağı bir şey de yok.
"""

from __future__ import annotations

import socket
import ssl
import time
from typing import List, Optional

from ..utils.platform_utils import current_platform, is_windows


CONNECT_TIMEOUT = 6.0  # Hızlı LAN bağlantısı: Windows'un 21 saniyelik SYN takılmalarını önler
TRANSFER_TIMEOUT = 180
HANDSHAKE_TIMEOUT = 120
TLS_CHUNK = 256 * 1024  # 256 KB chunk: modem/switch tamponunu taşırmaz, internet ve RDP kopmasını önler
# Yerel ağda (özel/link-local adres) parça başına onay beklemek hızı belirler: 256 KB'lık parçalarla tek akış
# 2-60 MB/s arasında dalgalandı (bir denemede 63 sn takıldı); 4 MB'lık parçalarda üç denemede de ~19-22 MB/s
# ile düzenli kaldı. İnternet/VPN adreslerinde eski küçük parça korunur.
TLS_CHUNK_LAN = 4 * 1024 * 1024


def tls_chunk_for(address: str) -> int:
    """Hedef adrese göre TLS parça boyutu: yerel ağda büyük, diğer her yerde küçük."""
    try:
        import ipaddress
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return TLS_CHUNK
    return TLS_CHUNK_LAN if (ip.is_private or ip.is_link_local) else TLS_CHUNK

# Keepalive: 30 sn boşta, sonra 5 sn arayla yoklama (Windows'taki değerlerle aynı), ~1 dk'da kopuk tespit
KEEPALIVE_IDLE = 30
KEEPALIVE_INTERVAL = 5
KEEPALIVE_COUNT = 6

_SIO_KEEPALIVE_VALS = 0x98000004  # _WSAIOW(IOC_VENDOR, 4); socket.SIO_KEEPALIVE_VALS yalnızca Windows'ta var
# macOS sabitleri (Python bazı sürümlerde socket modülünde sunmaz)
_DARWIN_TCP_KEEPALIVE = 0x10
_DARWIN_TCP_KEEPINTVL = 0x101
_DARWIN_TCP_KEEPCNT = 0x102


def apply_tcp_keepalive(sock: socket.socket, platform: Optional[str] = None) -> List[str]:
    """Platformun desteklediği TCP keepalive ayarlarını uygular; uygulananların adlarını döndürür."""
    kind = current_platform(platform)
    applied: List[str] = []

    def setopt(level: int, option: int, value: int, name: str) -> None:
        try:
            sock.setsockopt(level, option, value)
            applied.append(name)
        except (OSError, AttributeError):
            pass

    if kind == "windows":
        try:
            sock.ioctl(getattr(socket, "SIO_KEEPALIVE_VALS", _SIO_KEEPALIVE_VALS), (1, 30000, 5000))
            applied.append("SIO_KEEPALIVE_VALS")
        except (OSError, AttributeError):
            pass
    elif kind == "linux":
        setopt(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPIDLE", 4), KEEPALIVE_IDLE, "TCP_KEEPIDLE")
        setopt(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPINTVL", 5), KEEPALIVE_INTERVAL, "TCP_KEEPINTVL")
        setopt(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPCNT", 6), KEEPALIVE_COUNT, "TCP_KEEPCNT")
    elif kind == "macos":
        setopt(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPALIVE", _DARWIN_TCP_KEEPALIVE),
               KEEPALIVE_IDLE, "TCP_KEEPALIVE")
        setopt(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPINTVL", _DARWIN_TCP_KEEPINTVL),
               KEEPALIVE_INTERVAL, "TCP_KEEPINTVL")
        setopt(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPCNT", _DARWIN_TCP_KEEPCNT),
               KEEPALIVE_COUNT, "TCP_KEEPCNT")
    return applied


def configure_socket(sock: socket.socket, timeout: float = TRANSFER_TIMEOUT,
                     platform: Optional[str] = None) -> None:
    sock.settimeout(timeout)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    # Windows'ta SO_RCVBUF manuel ayarlandığında Windows TCP Window Auto-Tuning
    # devre dışı kalır ve tampon dolduğunda TCP ZeroWindow kilitlenmelerine yol açar.
    # Windows'un dinamik auto-tuning özelliğinin (16MB+'a kadar otomatik pencere ölçekleme)
    # devrede kalması için Windows'ta SO_RCVBUF işletim sistemine bırakılır.
    if not is_windows(platform):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * 1024 * 1024)
        except OSError:
            pass

    apply_tcp_keepalive(sock, platform)


def make_listen_socket(port: int, host: str = "", backlog: int = 128,
                       platform: Optional[str] = None) -> socket.socket:
    """Dinleyen TCP soketi: Windows'ta özel kullanım, Linux/macOS'ta SO_REUSEADDR (REUSEPORT yok).

    Hata olursa soket kapatılıp istisna yeniden fırlatılır (çağıran sonraki porta geçebilir).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if is_windows(platform) and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(backlog)
        return sock
    except BaseException:
        try:
            sock.close()
        except OSError:
            pass
        raise


def open_discovery_socket(port: int, host: str = "", platform: Optional[str] = None) -> socket.socket:
    """UDP keşif soketi: yayın izinli, ÖZEL kullanım (üç platformda da; bkz. modül açıklaması)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if is_windows(platform):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                # Windows'ta UDP'de SO_REUSEADDR, başka bir sürecin aynı porta bağlanıp
                # datagramları çalmasına izin verir; özel kullanım istenir (TCP sunucusu da böyle).
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Linux/macOS: REUSEADDR/REUSEPORT bilerek YOK (özel bağlama); bkz. modül açıklaması
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        except Exception:
            pass
        # Kapanan eşten dönen ICMP "port unreachable" WinError 10054 spam'i üretmesin
        disable_udp_connreset(sock, platform)
        sock.bind((host, port))
        sock.settimeout(1.0)
        return sock
    except BaseException:
        try:
            sock.close()
        except Exception:
            pass
        raise


_SIO_UDP_CONNRESET = 0x9800000C  # _WSAIOW(IOC_VENDOR, 12)


def disable_udp_connreset(sock: socket.socket, platform: Optional[str] = None) -> bool:
    """Windows'ta UDP soketinde ICMP "port unreachable"ın recvfrom'da WinError 10054 üretmesini kapatır.

    Yayın/yanıt gönderilen bir eş kapandığında (ICMP dönüşü) bu hata dinleme döngüsünü bozar ve
    günlüğü doldurur. Python'un socket.ioctl'u bu komutu desteklemediğinden WSAIoctl çağrılır.
    Windows dışında veya başarısızlıkta False döner (zararsız).
    """
    if not is_windows(platform):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        ws2_32 = ctypes.WinDLL("ws2_32", use_last_error=True)
        ws2_32.WSAIoctl.argtypes = [
            ctypes.c_size_t, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p, ctypes.c_void_p,
        ]
        ws2_32.WSAIoctl.restype = ctypes.c_int
        enable = wintypes.DWORD(0)  # FALSE: bu davranışı kapat
        returned = wintypes.DWORD(0)
        result = ws2_32.WSAIoctl(
            sock.fileno(), _SIO_UDP_CONNRESET, ctypes.byref(enable), ctypes.sizeof(enable),
            None, 0, ctypes.byref(returned), None, None,
        )
        return result == 0
    except Exception:
        return False


def send_all(sock: socket.socket, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            sent = sock.send(view)
        except ssl.SSLWantWriteError:
            time.sleep(0.005)
            continue
        except ssl.SSLWantReadError:
            time.sleep(0.005)
            continue
        except ssl.SSLZeroReturnError as exc:
            raise ConnectionError("TLS oturumu kapandı") from exc
        if sent == 0:
            raise ConnectionError("Bağlantı kapandı")
        view = view[sent:]


def recv_exact(sock: socket.socket, size: int) -> Optional[bytes]:
    if size <= 0:
        return b""
    buf = bytearray(size)
    view = memoryview(buf)
    got = 0
    while got < size:
        try:
            n = sock.recv_into(view[got:], min(size - got, 262144))
        except ssl.SSLWantReadError:
            time.sleep(0.005)
            continue
        except ssl.SSLWantWriteError:
            time.sleep(0.005)
            continue
        except ssl.SSLZeroReturnError:
            return None
        except socket.timeout:
            raise
        if n == 0:
            return None
        got += n
    return bytes(buf)


def socket_has_data(sock: socket.socket, timeout: float = 0.2) -> bool:
    """Check if socket has data to read without blocking for full transfer timeout."""
    import select
    try:
        if hasattr(sock, "pending") and sock.pending() > 0:
            return True
        r, _, _ = select.select([sock], [], [], timeout)
        return bool(r)
    except Exception:
        return False

