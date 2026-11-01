"""IPv4 ağ arayüzü sayımı: yerel IP kümesi ve yayın (broadcast) hedefleri.

Eskiden her yerel IP için `a.b.c.255` varsayılıyordu (/24 tahmini) ve Linux'ta `gethostname()`
çoğu zaman yalnızca 127.0.1.1 döndürdüğü için gerçek arayüzler hiç bulunamıyordu. Burada
arayüzler, alt ağ maskesi ve yayın adresleriyle (Qt'nin `QNetworkInterface`i üzerinden, her üç
platformda aynı) sayılır:

* Çoklu NIC: her etkin, yayın destekleyen arayüzün gerçek yönlendirilmiş yayın adresi (maske
  doğru: /16, /22 ... da çalışır) + genel yayın (`<broadcast>` = 255.255.255.255). Linux/macOS'ta
  genel yayın yalnızca varsayılan rotanın arayüzünden çıkar; diğer NIC'ler yönlendirilmiş
  adresle kapsanır.
* VPN: noktadan noktaya (tun/wg/ppp) arayüzlerin yayın alanı yoktur, atlanır.
* Docker/konteyner köprüleri (Linux/macOS'ta docker0, br-*, veth*, cni*, ...) kullanıcı
  cihazlarını barındırmaz, atlanır. Windows'ta eski davranış korunur (ad süzgeci yok).
* Yerel (self) IP kümesi tüm arayüz adreslerini içerir.

Sağlayıcı (`provider`) enjekte edilebilir; Qt yoksa/hata verirse eski sezgisel yönteme düşülür.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

from .platform_utils import is_windows

GENERIC_BROADCAST = "<broadcast>"  # sendto(): 255.255.255.255

# Konteyner/orkestrasyon köprüleri: yayın yapmanın anlamı yok (Linux/macOS'ta süzülür)
_CONTAINER_PREFIXES = ("docker", "veth", "br-", "cni", "flannel", "cali", "kube", "podman", "lxcbr")


@dataclass(frozen=True)
class Iface:
    name: str
    ip: str
    netmask: str = ""
    broadcast: str = ""
    loopback: bool = False
    point_to_point: bool = False
    can_broadcast: bool = True


Provider = Callable[[], List[Iface]]


def qt_interfaces() -> List[Iface]:
    """QNetworkInterface ile etkin (up+running) IPv4 arayüz adresleri."""
    from PyQt6.QtNetwork import QAbstractSocket, QNetworkInterface

    flag = QNetworkInterface.InterfaceFlag
    result: List[Iface] = []
    for qi in QNetworkInterface.allInterfaces():
        flags = qi.flags()
        if not (flags & flag.IsUp) or not (flags & flag.IsRunning):
            continue
        for entry in qi.addressEntries():
            address = entry.ip()
            if address.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            ip = address.toString()
            if not ip:
                continue
            result.append(Iface(
                name=qi.name() or qi.humanReadableName() or "",
                ip=ip,
                netmask=entry.netmask().toString() if not entry.netmask().isNull() else "",
                broadcast=entry.broadcast().toString() if not entry.broadcast().isNull() else "",
                loopback=bool(flags & flag.IsLoopBack),
                point_to_point=bool(flags & flag.IsPointToPoint),
                can_broadcast=bool(flags & flag.CanBroadcast),
            ))
    return result


def hostname_interfaces() -> List[Iface]:
    """Qt yokken/başarısızken eski yöntem: ana makine adından çözülen adresler (maske bilinmez)."""
    ips: List[str] = []
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if family == socket.AF_INET and sockaddr:
                ips.append(sockaddr[0])
    except Exception:
        pass
    try:
        ips.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    seen: List[str] = []
    for ip in ips:
        if ip and ip not in seen:
            seen.append(ip)
    return [Iface(name="", ip=ip, loopback=ip.startswith("127.")) for ip in seen]


def list_ipv4_interfaces(provider: Optional[Provider] = None) -> List[Iface]:
    """Sağlayıcıdan (varsayılan Qt) arayüzleri al; hata/boş sonuçta eski yönteme düş."""
    if provider is not None:
        try:
            return list(provider())
        except Exception:
            return []
    try:
        found = qt_interfaces()
        if found:
            return found
    except Exception:
        pass
    return hostname_interfaces()


def _is_link_local(ip: str) -> bool:
    return ip.startswith("169.254.")


def _is_container_bridge(name: str) -> bool:
    lowered = (name or "").lower()
    return lowered.startswith(_CONTAINER_PREFIXES)


def directed_broadcast(iface: Iface) -> str:
    """Arayüzün yönlendirilmiş yayın adresi; hesaplanamıyorsa (örn. /31, /32) boş dize."""
    if iface.broadcast:
        return iface.broadcast
    if not iface.netmask:
        return ""
    try:
        network = ipaddress.IPv4Network(f"{iface.ip}/{iface.netmask}", strict=False)
    except ValueError:
        return ""
    if network.prefixlen >= 31:
        return ""  # /31, /32: yayın adresi yok
    return str(network.broadcast_address)


def usable_for_broadcast(iface: Iface, platform: Optional[str] = None) -> bool:
    if iface.loopback or iface.ip.startswith("127.") or _is_link_local(iface.ip):
        return False
    if iface.point_to_point or not iface.can_broadcast:
        return False
    if not is_windows(platform) and _is_container_bridge(iface.name):
        return False
    return True


def broadcast_targets(
    ifaces: Sequence[Iface],
    fallback_ips: Iterable[str] = (),
    platform: Optional[str] = None,
) -> List[str]:
    """Genel yayın + her uygun arayüzün yönlendirilmiş yayın adresi (tekrarsız, sıralı).

    Arayüz sayımı hiçbir şey vermediyse (`ifaces` boş) eski /24 tahminine (`fallback_ips`) düşülür.
    """
    targets: List[str] = [GENERIC_BROADCAST]
    if ifaces:
        for iface in ifaces:
            if not usable_for_broadcast(iface, platform):
                continue
            target = directed_broadcast(iface)
            if target and target != iface.ip and target != "255.255.255.255" and target not in targets:
                targets.append(target)
        return targets
    for ip in fallback_ips:
        parts = ip.split(".")
        if len(parts) == 4 and not ip.startswith("127.") and not _is_link_local(ip):
            directed = ".".join(parts[:3]) + ".255"
            if directed != ip and directed not in targets:
                targets.append(directed)
    return targets


def local_ipv4_addresses(ifaces: Sequence[Iface]) -> set:
    """Arayüzlerin tüm IPv4 adresleri (self-algılama için; loopback dahil)."""
    return {iface.ip for iface in ifaces if iface.ip}


def first_private_ipv4(ifaces: Sequence[Iface], platform: Optional[str] = None) -> Optional[str]:
    """Varsayılan rota yokken yerel IP tahmini için ilk uygun (loopback/link-local olmayan) adres."""
    for iface in ifaces:
        if usable_for_broadcast(iface, platform):
            return iface.ip
    return None
