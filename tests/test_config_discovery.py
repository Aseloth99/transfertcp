"""Madde 7: atomik config/guven deposu yazimi, bozuk JSON yedegi, port goc mantigi ve
UDP kesif sertlestirmesi (SIO_UDP_CONNRESET, ozel port kullanimi, dogrulama/sinirlar).

Gercek ag kullanilmaz: kesif soketleri yalnizca 127.0.0.1 uzerinde acilir, start()/yayin yapilmaz.
"""

import glob
import json
import os
import socket
import sys
import threading
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import wait_until  # noqa: E402

import src.core.crypto as crypto  # noqa: E402
from src.core.discovery import NetworkDiscovery  # noqa: E402
from src.utils.config import ConfigManager  # noqa: E402
from src.utils.paths import get_user_config_dir  # noqa: E402
from src.utils.ports import DEFAULT_TRANSFER_PORT  # noqa: E402


def make_config(content=None):
    name = f"cfg_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(get_user_config_dir(), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if content is not None:
        with open(path, "wb") as handle:
            handle.write(content)
    return ConfigManager(name), path


class ConfigRobustnessTest(unittest.TestCase):
    def _backups(self, path):
        return glob.glob(path + ".corrupt-*")

    def test_truncated_json_is_backed_up_not_silently_overwritten(self) -> None:
        original = b'{"general": {"device_name": "Evim", "first_run": fals'
        cfg, path = make_config(original)
        backups = self._backups(path)
        self.assertEqual(len(backups), 1, "bozuk dosya yedeklenmedi")
        with open(backups[0], "rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertTrue(cfg.get("general", "first_run"), "varsayilana donulmedi")
        with open(path, "r", encoding="utf-8") as handle:
            self.assertIsInstance(json.load(handle), dict)  # yeni dosya gecerli

    def test_non_object_and_non_utf8_files_are_backed_up(self) -> None:
        for content in (b"[1, 2, 3]", b"\xff\xfe\x00junk\x80"):
            with self.subTest(content=content[:6]):
                cfg, path = make_config(content)
                self.assertEqual(len(self._backups(path)), 1)
                self.assertEqual(cfg.get("transfer", "port"), DEFAULT_TRANSFER_PORT)

    def test_valid_config_is_loaded_and_not_backed_up(self) -> None:
        cfg, path = make_config(json.dumps({"general": {"device_name": "Test PC"}}).encode())
        self.assertEqual(cfg.get("general", "device_name"), "Test PC")
        self.assertEqual(self._backups(path), [])

    def test_save_with_unserializable_value_keeps_previous_file(self) -> None:
        cfg, path = make_config()
        cfg.set("general", "device_name", "Ilk")
        with open(path, "rb") as handle:
            before = handle.read()
        cfg.config["general"]["bozuk"] = object()  # json'a yazilamaz
        cfg.save()  # hata yutulur ama dosya yarim kalmamali
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before, "basarisiz kayit mevcut dosyayi bozdu (atomik degil)")
        self.assertEqual(glob.glob(path + "*.tmp"), [])

    def test_failed_replace_keeps_original_and_cleans_tmp(self) -> None:
        cfg, path = make_config()
        cfg.set("general", "device_name", "Ilk")
        with open(path, "rb") as handle:
            before = handle.read()
        cfg.config["general"]["device_name"] = "Ikinci"
        with mock.patch("src.utils.fileio.os.replace", side_effect=OSError("kilitli")):
            cfg.save()
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(glob.glob(path + "*.tmp"), [])

    def test_save_flushes_to_disk_with_fsync(self) -> None:
        cfg, path = make_config()
        with mock.patch("src.utils.fileio.os.fsync", wraps=os.fsync) as fsync:
            cfg.set("general", "device_name", "X")
        self.assertGreaterEqual(fsync.call_count, 1)

    def test_concurrent_sets_always_leave_valid_json(self) -> None:
        cfg, path = make_config()
        errors = []

        def worker(index):
            try:
                for turn in range(25):
                    cfg.set("general", f"k{index}", turn)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["general"]["k7"], 24)
        self.assertEqual(glob.glob(path + "*.tmp"), [])


class PortMigrationTest(unittest.TestCase):
    def _port_after_load(self, port):
        cfg, _path = make_config(json.dumps({"transfer": {"port": port}}).encode())
        return cfg.get("transfer", "port")

    def test_user_chosen_high_ports_are_kept(self) -> None:
        # Ayarlar arayuzu 1024-65535 arasini sectirir; eskiden >=49152 her acilista sifirlaniyordu
        for port in (49152, 50000, 60000, 65535, 40000, 1024):
            with self.subTest(port=port):
                self.assertEqual(self._port_after_load(port), port)

    def test_legacy_default_ports_are_migrated(self) -> None:
        for port in (5000, 52980, 59144):
            with self.subTest(port=port):
                self.assertEqual(self._port_after_load(port), DEFAULT_TRANSFER_PORT)

    def test_invalid_ports_fall_back_to_default(self) -> None:
        for port in ("abc", 0, -5, 70000, None, True, 1.5):
            with self.subTest(port=port):
                self.assertEqual(self._port_after_load(port), DEFAULT_TRANSFER_PORT)


class TrustStoreTest(unittest.TestCase):
    def tearDown(self) -> None:
        for backup in glob.glob(crypto._trust_path() + ".corrupt-*"):
            os.remove(backup)
        crypto.clear_trusted_devices()

    def test_corrupt_trust_file_is_backed_up_and_not_lost_on_next_write(self) -> None:
        path = crypto._trust_path()
        with open(path, "wb") as handle:
            handle.write(b'{"devices": [ {"fingerprint": "abc"')
        self.assertEqual(crypto.list_trusted_devices(), [])
        backups = glob.glob(path + ".corrupt-*")
        self.assertEqual(len(backups), 1)
        crypto.trust_device("ab" * 32, "Yeni", "10.0.0.9")  # sonraki yazim
        self.assertEqual(len(crypto.list_trusted_devices()), 1)
        with open(backups[0], "rb") as handle:
            self.assertIn(b'"fingerprint": "abc"', handle.read())

    def test_trust_save_is_atomic(self) -> None:
        crypto.trust_device("cd" * 32, "A", "10.0.0.1")
        path = crypto._trust_path()
        with open(path, "rb") as handle:
            before = handle.read()
        with mock.patch("src.utils.fileio.os.replace", side_effect=OSError("kilitli")):
            with self.assertRaises(OSError):
                crypto.trust_device("ef" * 32, "B", "10.0.0.2")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(glob.glob(path + "*.tmp"), [])


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_discovery():
    with mock.patch.object(NetworkDiscovery, "_collect_local_ips", return_value={"127.0.0.1"}):
        disc = NetworkDiscovery()
    disc._send_discover_response = lambda *a, **k: None  # gercek ag/yanit yok
    disc.found = []
    disc.on_device_found = lambda device: disc.found.append(device)
    return disc


class DiscoveryValidationTest(unittest.TestCase):
    def test_invalid_ports_do_not_create_devices(self) -> None:
        for bad in (0, -1, 65536, 10 ** 9, "38520", True, None, 1.5, [38520], {"a": 1}):
            with self.subTest(port=bad):
                disc = make_discovery()
                disc._handle_discover({"device_name": "X", "hostname": "h", "port": bad}, "10.0.0.5")
                disc._handle_discover_response({"device_name": "X", "hostname": "h", "port": bad}, "10.0.0.5")
                disc._handle_goodbye({"port": bad}, "10.0.0.5")
                self.assertEqual(disc.devices, {})

    def test_valid_and_missing_port_still_work(self) -> None:
        disc = make_discovery()
        disc._handle_discover({"device_name": "A", "hostname": "ha", "port": 40001}, "10.0.0.5")
        disc._handle_discover({"device_name": "B", "hostname": "hb"}, "10.0.0.6")  # eski surum: port yok
        self.assertIn("10.0.0.5:40001", disc.devices)
        self.assertIn(f"10.0.0.6:{DEFAULT_TRANSFER_PORT}", disc.devices)

    def test_names_are_sanitized(self) -> None:
        disc = make_discovery()
        disc._handle_discover({"device_name": 12345, "hostname": ["x"], "port": 40002}, "10.0.0.7")
        device = disc.devices["10.0.0.7:40002"]
        self.assertEqual((device.name, device.hostname), ("Unknown", "Unknown"))
        disc._handle_discover({"device_name": "A\x00\x1b[31m" + "B" * 200, "hostname": "h", "port": 40003}, "10.0.0.7")
        long_name = disc.devices["10.0.0.7:40003"].name
        self.assertLessEqual(len(long_name), NetworkDiscovery.MAX_TEXT_LENGTH)
        self.assertNotIn("\x00", long_name)
        self.assertNotIn("\x1b", long_name)

    def test_per_ip_device_limit(self) -> None:
        disc = make_discovery()
        for port in range(40000, 40050):
            disc._handle_discover({"device_name": "Spam", "hostname": "s", "port": port}, "10.0.0.8")
        self.assertEqual(len(disc.devices), NetworkDiscovery.MAX_DEVICES_PER_IP)

    def test_total_device_limit_still_updates_existing_devices(self) -> None:
        disc = make_discovery()
        disc.MAX_DEVICES = 20
        for host in range(1, 11):
            for port in (40000, 40001, 40002):
                disc._handle_discover({"device_name": "d", "hostname": "h", "port": port}, f"10.1.0.{host}")
        self.assertEqual(len(disc.devices), 20)
        disc._handle_discover({"device_name": "late", "hostname": "h", "port": 41000}, "10.9.9.9")
        self.assertNotIn("10.9.9.9:41000", disc.devices)
        known = disc.devices["10.1.0.1:40000"]
        known.is_online = False
        disc._handle_discover({"device_name": "d", "hostname": "h", "port": 40000}, "10.1.0.1")
        self.assertTrue(known.is_online, "sinira ragmen bilinen cihaz guncellenmeli")

    def test_responses_are_limited_too(self) -> None:
        disc = make_discovery()
        for port in range(41000, 41050):
            disc._handle_discover_response({"device_name": "Spam", "hostname": "s", "port": port}, "10.0.0.20")
        self.assertEqual(len(disc.devices), NetworkDiscovery.MAX_DEVICES_PER_IP)

    def test_manual_devices_are_not_limited(self) -> None:
        disc = make_discovery()
        for port in range(42000, 42020):
            disc.add_manual_device("10.0.0.30", port, f"m{port}")
        self.assertEqual(len(disc.devices), 20)


class DiscoveryListenLoopTest(unittest.TestCase):
    def test_garbage_packets_do_not_break_the_listener(self) -> None:
        disc = make_discovery()
        port = free_udp_port()
        disc.sock = disc._open_socket(port, "127.0.0.1")
        disc._local_ips = set()  # yerel (127.0.0.1) kaynak "kendimiz" sayilmasin
        disc.running = True
        listener = threading.Thread(target=disc._listen_broadcasts, daemon=True)
        listener.start()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        packets = [
            b"\xff\xfe\xfa\x80",                                                    # UTF-8 degil
            b"[1,2,3]",                                                              # dict degil
            b'"just a string"',
            b'{"type":"discover","data":"x"}',                                       # data dict degil
            b'{"type":"discover","data":{"port":"abc","device_name":"X"}}',          # gecersiz port
            b'{"type":["x"]}',
            json.dumps({"version": "1.0", "type": "discover",
                        "data": {"device_name": "Good", "hostname": "gh", "port": 40001}}).encode(),
        ]
        for packet in packets:
            sender.sendto(packet, ("127.0.0.1", port))
        try:
            self.assertTrue(wait_until(lambda: "127.0.0.1:40001" in disc.devices, 10),
                            "gecerli paket, bozuk paketlerden sonra islenmedi")
            self.assertEqual(list(disc.devices), ["127.0.0.1:40001"])
            self.assertTrue(listener.is_alive())
        finally:
            disc.running = False
            disc.sock.close()
            listener.join(3)


@unittest.skipUnless(sys.platform == "win32", "Windows'a ozgu soket davranisi")
class DiscoveryWindowsSocketTest(unittest.TestCase):
    def test_discovery_socket_cannot_be_hijacked_by_reuseaddr(self) -> None:
        disc = make_discovery()
        port = free_udp_port()
        sock = disc._open_socket(port, "127.0.0.1")
        self.addCleanup(sock.close)
        hijacker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(hijacker.close)
        hijacker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError, msg="SO_REUSEADDR ile ayni UDP portuna baglanilabildi (port calma)"):
            hijacker.bind(("127.0.0.1", port))

    def _send_to_closed_port_then_recv(self, sock):
        dead = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dead.bind(("127.0.0.1", 0))
        dead_port = dead.getsockname()[1]
        dead.close()
        sock.settimeout(1.0)
        sock.sendto(b"x", ("127.0.0.1", dead_port))
        time.sleep(0.3)
        return sock.recvfrom(100)

    def test_control_plain_udp_socket_shows_the_winerror_10054_problem(self) -> None:
        plain = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(plain.close)
        plain.bind(("127.0.0.1", 0))
        with self.assertRaises(ConnectionResetError):
            self._send_to_closed_port_then_recv(plain)

    def test_discovery_socket_ignores_icmp_port_unreachable(self) -> None:
        disc = make_discovery()
        sock = disc._open_socket(free_udp_port(), "127.0.0.1")
        self.addCleanup(sock.close)
        with self.assertRaises(socket.timeout):  # 10054 degil: normal zaman asimi
            self._send_to_closed_port_then_recv(sock)


if __name__ == "__main__":
    unittest.main()
