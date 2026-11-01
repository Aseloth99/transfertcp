"""Madde 2: platforma gore soket davranisi (netio/discovery/server) ve arayuz sayimi.

* Windows/Linux GERCEK soketlerle (yalniz 127.0.0.1) dogrulanir; macOS yalnizca `platform="darwin"`
  parametresiyle (sahte soket / Linux soketi uzerinde) sinanir.
* LAN'a hicbir paket gonderilmez: yayin hedefleri sahte arayuz saglayicisindan hesaplanir.
"""

import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import Loopback, free_port, wait_until  # noqa: E402

from src.core import netio  # noqa: E402
from src.core.discovery import NetworkDiscovery  # noqa: E402
from src.utils import netif  # noqa: E402
from src.utils.netif import Iface  # noqa: E402
from src.utils.ports import DEFAULT_DISCOVERY_PORT  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


class FakeSock:
    """setsockopt/ioctl/settimeout cagrilarini kaydeden sahte TCP soketi."""

    def __init__(self, fail_options=False):
        self.opts = []
        self.ioctls = []
        self.timeout = None
        self.fail_options = fail_options

    def settimeout(self, value):
        self.timeout = value

    def setsockopt(self, level, option, value):
        if self.fail_options:
            raise OSError("desteklenmiyor")
        self.opts.append((level, option, value))

    def ioctl(self, code, value):
        if self.fail_options:
            raise OSError("desteklenmiyor")
        self.ioctls.append((code, value))

    def has(self, level, option, value=None):
        return any(l == level and o == option and (value is None or v == value) for l, o, v in self.opts)


class KeepaliveTest(unittest.TestCase):
    def test_windows_uses_sio_keepalive_vals_and_leaves_rcvbuf_to_autotuning(self) -> None:
        sock = FakeSock()
        netio.configure_socket(sock, 30, platform="win32")
        code = getattr(socket, "SIO_KEEPALIVE_VALS", netio._SIO_KEEPALIVE_VALS)
        self.assertEqual(sock.ioctls, [(code, (1, 30000, 5000))])
        self.assertTrue(sock.has(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1))
        self.assertTrue(sock.has(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1))
        self.assertFalse(sock.has(socket.SOL_SOCKET, socket.SO_RCVBUF), "Windows'ta SO_RCVBUF auto-tuning'i bozar")
        self.assertEqual(sock.timeout, 30)

    def test_linux_uses_tcp_keepidle_intvl_cnt(self) -> None:
        sock = FakeSock()
        applied = netio.apply_tcp_keepalive(sock, "linux")
        self.assertEqual(applied, ["TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT"])
        self.assertTrue(sock.has(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPIDLE", 4), netio.KEEPALIVE_IDLE))
        self.assertTrue(sock.has(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPINTVL", 5), netio.KEEPALIVE_INTERVAL))
        self.assertTrue(sock.has(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPCNT", 6), netio.KEEPALIVE_COUNT))
        self.assertEqual(sock.ioctls, [])

    def test_macos_uses_tcp_keepalive_option(self) -> None:
        sock = FakeSock()
        applied = netio.apply_tcp_keepalive(sock, "darwin")
        self.assertEqual(applied, ["TCP_KEEPALIVE", "TCP_KEEPINTVL", "TCP_KEEPCNT"])
        self.assertTrue(sock.has(socket.IPPROTO_TCP, getattr(socket, "TCP_KEEPALIVE", 0x10), netio.KEEPALIVE_IDLE))
        self.assertEqual(sock.ioctls, [])

    def test_posix_sets_big_buffers_and_unknown_platform_only_basics(self) -> None:
        for platform in ("linux", "darwin"):
            sock = FakeSock()
            netio.configure_socket(sock, platform=platform)
            self.assertTrue(sock.has(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024), platform)
        other = FakeSock()
        self.assertEqual(netio.apply_tcp_keepalive(other, "freebsd14"), [])

    def test_unsupported_options_are_skipped_without_raising(self) -> None:
        for platform in ("win32", "linux", "darwin"):
            sock = FakeSock(fail_options=True)
            netio.configure_socket(sock, platform=platform)  # istisna firlatmamali
            self.assertEqual(netio.apply_tcp_keepalive(sock, platform), [])

    def test_real_socket_accepts_keepalive_for_current_platform(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            netio.configure_socket(sock)
            self.assertTrue(sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE))
            if IS_LINUX:
                self.assertEqual(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE), netio.KEEPALIVE_IDLE)
                self.assertEqual(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL), netio.KEEPALIVE_INTERVAL)
                self.assertEqual(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT), netio.KEEPALIVE_COUNT)


class ListenSocketTest(unittest.TestCase):
    def test_second_listener_on_same_port_is_refused(self) -> None:
        port = free_port()
        first = netio.make_listen_socket(port, "127.0.0.1")
        self.addCleanup(first.close)
        with self.assertRaises(OSError):
            netio.make_listen_socket(port, "127.0.0.1")

    @unittest.skipUnless(IS_LINUX, "gercek Linux soket seceneklerini okur")
    def test_linux_listener_uses_reuseaddr_but_never_reuseport(self) -> None:
        for platform in ("linux", "darwin"):  # macOS yolu da ayni POSIX dali
            sock = netio.make_listen_socket(free_port(), "127.0.0.1", platform=platform)
            self.addCleanup(sock.close)
            self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 1, platform)
            self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT), 0,
                             "SO_REUSEPORT iki ornegin baglantilari sessizce bolmesine yol acar")

    @unittest.skipUnless(IS_LINUX, "TIME_WAIT/REUSEADDR Linux'ta gercek soketle sinanir")
    def test_linux_listener_can_rebind_right_after_a_connection_closed(self) -> None:
        port = free_port()
        listener = netio.make_listen_socket(port, "127.0.0.1")
        client = socket.create_connection(("127.0.0.1", port), timeout=3)
        conn, _ = listener.accept()
        conn.close()   # sunucu tarafi once kapatir -> TIME_WAIT
        time.sleep(0.1)
        client.close()
        listener.close()
        again = netio.make_listen_socket(port, "127.0.0.1")  # hizli yeniden baslatma (peer restart senaryosu)
        again.close()

    @unittest.skipUnless(IS_WINDOWS, "SO_EXCLUSIVEADDRUSE yalnizca Windows'ta")
    def test_windows_listener_cannot_be_hijacked_by_reuseaddr(self) -> None:
        port = free_port()
        listener = netio.make_listen_socket(port, "127.0.0.1")
        self.addCleanup(listener.close)
        hijacker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(hijacker.close)
        hijacker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError):
            hijacker.bind(("127.0.0.1", port))


class DiscoverySocketTest(unittest.TestCase):
    def test_second_discovery_socket_on_same_port_is_refused_on_every_platform(self) -> None:
        """Iki yerel ornek ayni UDP portunu paylasmamali (yanitlar sessizce bolunurdu)."""
        port = free_port_udp()
        first = netio.open_discovery_socket(port, "127.0.0.1")
        self.addCleanup(first.close)
        with self.assertRaises(OSError):
            netio.open_discovery_socket(port, "127.0.0.1")

    @unittest.skipUnless(IS_LINUX, "gercek Linux soket seceneklerini okur")
    def test_linux_discovery_socket_is_exclusive_and_broadcast_capable(self) -> None:
        port = free_port_udp()
        sock = netio.open_discovery_socket(port, "127.0.0.1", platform="darwin")  # macOS dali = POSIX dali
        self.addCleanup(sock.close)
        self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST), 1)
        self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 0)
        self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT), 0)
        for option in (socket.SO_REUSEADDR, socket.SO_REUSEPORT):
            hijacker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addCleanup(hijacker.close)
            hijacker.setsockopt(socket.SOL_SOCKET, option, 1)
            with self.assertRaises(OSError, msg=f"{option} ile UDP portu calindi"):
                hijacker.bind(("127.0.0.1", port))

    def test_discovery_open_socket_delegates_to_netio(self) -> None:
        disc = make_discovery()
        port = free_port_udp()
        sock = disc._open_socket(port, "127.0.0.1")
        self.addCleanup(sock.close)
        self.assertEqual(sock.getsockname()[1], port)
        self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST) != 0, True)

    def test_failed_bind_does_not_leak_the_socket(self) -> None:
        port = free_port_udp()
        holder = netio.open_discovery_socket(port, "127.0.0.1")
        self.addCleanup(holder.close)
        created = []
        real_socket = socket.socket

        def tracking_socket(*args, **kwargs):
            sock = real_socket(*args, **kwargs)
            created.append(sock)
            return sock

        with mock.patch.object(netio.socket, "socket", tracking_socket):
            with self.assertRaises(OSError):
                netio.open_discovery_socket(port, "127.0.0.1")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].fileno(), -1, "basarisiz bind soketi kapatmadi")

    @unittest.skipUnless(IS_LINUX, "127.255.255.255 yayini Linux loopback'inde yerel dagitilir")
    def test_socket_bound_to_any_receives_broadcast_on_linux(self) -> None:
        """Linux'ta `''` ile baglanan soket yayin paketlerini alir (yalnizca loopback yayin adresi)."""
        port = free_port_udp()
        receiver = netio.open_discovery_socket(port, "")
        self.addCleanup(receiver.close)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sender.sendto(b"hello-broadcast", ("127.255.255.255", port))
        receiver.settimeout(3)
        data, _addr = receiver.recvfrom(100)
        self.assertEqual(data, b"hello-broadcast")


def free_port_udp() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_discovery():
    with mock.patch.object(NetworkDiscovery, "_collect_local_ips", return_value={"127.0.0.1"}):
        disc = NetworkDiscovery()
    disc.found = []
    disc.on_device_found = lambda device: disc.found.append(device)
    return disc


class InterfaceTargetsTest(unittest.TestCase):
    ETH = Iface("eth0", "192.168.1.20", "255.255.255.0", "192.168.1.255")
    WIFI16 = Iface("wlan0", "10.20.30.40", "255.255.0.0")           # yayin adresi maskeden hesaplanir
    LOOP = Iface("lo", "127.0.0.1", "255.0.0.0", "", loopback=True, can_broadcast=False)
    VPN = Iface("wg0", "10.8.0.2", "255.255.255.255", "", point_to_point=True, can_broadcast=False)
    DOCKER = Iface("docker0", "172.17.0.1", "255.255.0.0", "172.17.255.255")
    BRIDGE = Iface("br-1a2b3c", "172.18.0.1", "255.255.0.0")
    LINKLOCAL = Iface("eth1", "169.254.3.4", "255.255.0.0")
    SLASH31 = Iface("eth2", "10.0.0.1", "255.255.255.254")

    def test_multi_nic_gets_each_directed_broadcast_plus_generic(self) -> None:
        targets = netif.broadcast_targets([self.ETH, self.WIFI16, self.LOOP], platform="linux")
        self.assertEqual(targets, ["<broadcast>", "192.168.1.255", "10.20.255.255"])

    def test_vpn_loopback_linklocal_and_slash31_are_skipped(self) -> None:
        targets = netif.broadcast_targets(
            [self.LOOP, self.VPN, self.LINKLOCAL, self.SLASH31, self.ETH], platform="linux")
        self.assertEqual(targets, ["<broadcast>", "192.168.1.255"])

    def test_container_bridges_are_skipped_on_posix_but_not_on_windows(self) -> None:
        ifaces = [self.ETH, self.DOCKER, self.BRIDGE]
        self.assertEqual(netif.broadcast_targets(ifaces, platform="linux"), ["<broadcast>", "192.168.1.255"])
        self.assertEqual(netif.broadcast_targets(ifaces, platform="darwin"), ["<broadcast>", "192.168.1.255"])
        # Windows'ta eski davranis: ad suzgeci yok
        self.assertEqual(netif.broadcast_targets(ifaces, platform="win32"),
                         ["<broadcast>", "192.168.1.255", "172.17.255.255", "172.18.255.255"])

    def test_duplicates_collapse(self) -> None:
        twin = Iface("eth0:1", "192.168.1.21", "255.255.255.0", "192.168.1.255")
        self.assertEqual(netif.broadcast_targets([self.ETH, twin]), ["<broadcast>", "192.168.1.255"])

    def test_empty_enumeration_falls_back_to_slash24_guess(self) -> None:
        targets = netif.broadcast_targets([], fallback_ips={"192.168.5.7", "127.0.0.1", "169.254.1.1"})
        self.assertEqual(targets, ["<broadcast>", "192.168.5.255"])

    def test_local_addresses_and_first_private(self) -> None:
        ifaces = [self.LOOP, self.VPN, self.ETH]
        self.assertEqual(netif.local_ipv4_addresses(ifaces), {"127.0.0.1", "10.8.0.2", "192.168.1.20"})
        self.assertEqual(netif.first_private_ipv4(ifaces), "192.168.1.20")
        self.assertIsNone(netif.first_private_ipv4([self.LOOP]))

    def test_provider_error_yields_empty_list_not_exception(self) -> None:
        def broken():
            raise RuntimeError("Qt yok")
        self.assertEqual(netif.list_ipv4_interfaces(broken), [])

    def test_real_enumeration_returns_valid_ipv4_entries(self) -> None:
        ifaces = netif.list_ipv4_interfaces()
        import ipaddress
        for iface in ifaces:
            ipaddress.IPv4Address(iface.ip)  # gecerli IPv4 olmali
        if IS_LINUX:
            self.assertTrue(any(i.loopback and i.ip == "127.0.0.1" for i in ifaces) or ifaces == [],
                            "Linux'ta loopback arayuzu sayilmali")


class DiscoveryBroadcastPlanTest(unittest.TestCase):
    def test_targets_come_from_interfaces_not_a_slash24_guess(self) -> None:
        disc = make_discovery()
        fake = [Iface("eth0", "10.1.2.3", "255.255.252.0", "10.1.3.255")]
        with mock.patch.object(netif, "list_ipv4_interfaces", return_value=fake):
            self.assertEqual(disc._broadcast_targets(), ["<broadcast>", "10.1.3.255"])

    def test_fallback_port_also_broadcasts_to_default_port(self) -> None:
        disc = make_discovery()
        disc.BROADCAST_PORT = DEFAULT_DISCOVERY_PORT
        self.assertEqual(disc._broadcast_ports(), [DEFAULT_DISCOVERY_PORT])
        disc.BROADCAST_PORT = 38522
        self.assertEqual(disc._broadcast_ports(), [38522, DEFAULT_DISCOVERY_PORT])

    def test_presence_packet_goes_to_every_target_and_port(self) -> None:
        disc = make_discovery()
        sent = []
        disc.sock = types_namespace(sendto=lambda data, addr: sent.append(addr))
        disc.running = True
        disc.BROADCAST_PORT = 38522
        fake = [Iface("eth0", "10.1.2.3", "255.255.255.0", "10.1.2.255")]
        with mock.patch.object(netif, "list_ipv4_interfaces", return_value=fake), \
                mock.patch.object(NetworkDiscovery, "_collect_local_ips", return_value={"10.1.2.3"}):
            disc._send_presence_packet()
        self.assertEqual(sorted(sent), sorted([
            ("<broadcast>", 38522), ("<broadcast>", DEFAULT_DISCOVERY_PORT),
            ("10.1.2.255", 38522), ("10.1.2.255", DEFAULT_DISCOVERY_PORT),
        ]))

    def test_local_ips_include_all_interface_addresses(self) -> None:
        fake = [Iface("eth0", "10.1.2.3", "255.255.255.0"), Iface("wg0", "10.8.0.2", point_to_point=True)]
        with mock.patch.object(netif, "list_ipv4_interfaces", return_value=fake):
            ips = NetworkDiscovery()._collect_local_ips()
        self.assertTrue({"10.1.2.3", "10.8.0.2"} <= ips)


def types_namespace(**kwargs):
    import types
    return types.SimpleNamespace(**kwargs)


class LoopbackDiscoveryTest(unittest.TestCase):
    """Gercek UDP (yalniz 127.0.0.1): iki NetworkDiscovery ornegi birbirini bulur."""

    def _node(self, name, port):
        disc = make_discovery()
        disc._local_ips = set()
        disc._collect_local_ips = lambda: set()   # 127.0.0.1 "kendimiz" sayilmasin
        disc._local_fingerprint = None
        disc.BROADCAST_PORT = port
        disc._broadcast_targets = lambda: ["127.0.0.1"]   # LAN'a yayin YOK
        # ayni makinedeki iki ornek: kimligi yalnizca instance_id ile ayir
        disc._is_self = lambda data, ip, me=disc: data.get("instance_id") == me._instance_id
        disc.config = types_namespace(get=lambda section, key, default=None, n=name: n if key == "device_name" else (
            free_tcp_port_for(n) if key == "port" else default))
        return disc

    def test_two_instances_discover_each_other_over_real_udp(self) -> None:
        port_a, port_b = free_port_udp(), free_port_udp()
        a, b = self._node("Alpha", port_a), self._node("Beta", port_b)
        # her biri digerinin portuna da gonderir (yedek-port senaryosunun aynisi)
        a._broadcast_ports = lambda: [port_a, port_b]
        b._broadcast_ports = lambda: [port_b, port_a]
        a.sock, b.sock = a._open_socket(port_a, "127.0.0.1"), b._open_socket(port_b, "127.0.0.1")
        a.running = b.running = True
        threads = [threading.Thread(target=n._listen_broadcasts, daemon=True) for n in (a, b)]
        for thread in threads:
            thread.start()
        try:
            a._send_presence_packet()
            self.assertTrue(wait_until(lambda: any(d.name == "Alpha" for d in b.found), 10),
                            "B, A'yi gercek UDP uzerinden bulamadi")
            self.assertTrue(wait_until(lambda: any(d.name == "Beta" for d in a.found), 10),
                            "A, B'nin yanitini (discovery_port) alamadi")
        finally:
            a.running = b.running = False
            a.sock.close()
            b.sock.close()
            for thread in threads:
                thread.join(3)


def free_tcp_port_for(name):
    return 40000 + (sum(map(ord, name)) % 1000)


class ServerStopTest(unittest.TestCase):
    def test_stop_wakes_the_accept_thread_and_returns_quickly(self) -> None:
        lb = Loopback().start()
        thread = lb.server.server_thread
        self.assertTrue(thread.is_alive())
        started = time.time()
        lb.server.stop()
        self.assertLess(time.time() - started, 2.5)
        self.assertFalse(thread.is_alive(), "accept() thread'i stop() sonrasi hala bloklu (Linux close() davranisi)")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", lb.server.port), timeout=1)

    def test_stop_is_safe_twice_and_before_start(self) -> None:
        lb = Loopback()
        lb.server.stop()  # hic baslamamis
        lb.start()
        lb.server.stop()
        lb.server.stop()

    def test_wakeup_connection_is_not_handled_as_a_client(self) -> None:
        lb = Loopback().start()
        handled = []
        lb.server._handle_client = lambda *a, **k: handled.append(a)
        lb.server.stop()
        self.assertEqual(handled, [])


if __name__ == "__main__":
    unittest.main()
