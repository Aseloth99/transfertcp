"""Sunucu saglamligi (Madde 5): yazici olumu, kilit, dogrulama, disk alani, baglanti siniri,
bayat/yarisan alicilar ve hata mesaji siniflandirmasi. Loopback, UI yok.
"""

import collections
import errno
import os
import socket
import struct
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import Loopback, RawPeer, make_bytes, read_file, sha256_hex, wait_until, write_file  # noqa: E402

import builtins  # noqa: E402
import src.core.server as server_module  # noqa: E402
from src.core.client import CompletionNotConfirmed, ReceiverReportedError, TCPClient  # noqa: E402
from src.core.crypto import get_local_fingerprint  # noqa: E402
from src.core.protocol import MessageType, Protocol  # noqa: E402
from src.core.server import DiskWriteError, IntegrityError, SenderProtocolError, TCPServer  # noqa: E402
from src.core.transfer import TransferManager  # noqa: E402
from src.models.transfer import Transfer, TransferDirection  # noqa: E402

FEATURES = list(Protocol.LOCAL_FEATURES)
CHUNK = 16384


# --------------------------------------------------------------------------- yazici olumu

class _BlockedThenFailingFile:
    """.part dosyasi taklidi: ilk write() serbest birakilana kadar bloklar, sonra ENOSPC ile patlar."""

    def __init__(self, release: threading.Event):
        self.release = release

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, data):
        self.release.wait(30)
        raise OSError(errno.ENOSPC, "No space left on device")

    def flush(self):
        pass

    def fileno(self):
        raise OSError("fd yok")


class WriterDeathTest(unittest.TestCase):
    def test_dead_writer_with_full_queue_does_not_hang_receiver(self) -> None:
        release = threading.Event()
        real_open = builtins.open

        def fake_open(path, mode="r", *args, **kwargs):
            if str(path).endswith(".part") and ("w" in mode or "a" in mode):
                return _BlockedThenFailingFile(release)
            return real_open(path, mode, *args, **kwargs)

        # Tampon artık bayt sınırlı: 4096 baytlık parçalarla 48 parçada dolacak kadar küçültülür
        with mock.patch.object(server_module, "open", fake_open, create=True), \
             mock.patch.object(server_module, "WRITE_BUFFER_BYTES", 4096 * 48):
            with Loopback(chunk_size=4096).start() as lb:
                peer = RawPeer(lb.server.port)
                self.addCleanup(peer.close)
                peer.handshake()
                peer.file_info("dead-1", "big.bin", 4096 * 400)
                payload = make_bytes(4096, seed=5)
                sent = 0
                # Kuyruk (48) dolana ve alici put()'ta bloklanana kadar parca gonder:
                # bloklaninca ACK gelmez (recv zaman asimina ugrar) ve dongu biter.
                for index in range(120):
                    reply, _ = peer.chunk("dead-1", index, 400, payload)
                    if reply != MessageType.CHUNK_ACK:
                        break
                    sent += 1
                    peer.sock.settimeout(0.6)
                self.assertGreaterEqual(sent, 45, "kuyruk dolmadi; test senaryosu gecersiz")
                release.set()  # yazici simdi ENOSPC ile olur; alici put'ta bloklu kalmamali

                error_message = None
                for _ in range(10):
                    msg_type, data = peer.recv(timeout=10)
                    if msg_type == MessageType.TRANSFER_ERROR:
                        error_message = data.get("error")
                        break
                    if msg_type is None:
                        break
                self.assertEqual(error_message, "Diskte yeterli boş alan yok.",
                                 "yazici olunce alici kilitlendi / hata iletilmedi")
                self.assertTrue(lb.wait_recv("dead-1", 10))
                self.assertEqual(lb.recv_transfer("dead-1").status.value, "failed")


# --------------------------------------------------------------------------- active_transfers kilidi

class ActiveTransfersLockTest(unittest.TestCase):
    def test_concurrent_iteration_and_registration_never_raises(self) -> None:
        manager = TransferManager()
        for index in range(20000):
            manager.register_transfer(
                Transfer(f"seed-{index}", "f", "f", 1, "127.0.0.1", "x", TransferDirection.RECEIVE))
        errors = []
        stop = threading.Event()

        def iterate():
            try:
                for _ in range(60):
                    manager.get_active_transfers()
                    manager.get_statistics()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                stop.set()

        def mutate():
            index = 0
            while not stop.is_set():
                tid = f"new-{index}"
                manager.register_transfer(
                    Transfer(tid, "f", "f", 1, "127.0.0.1", "x", TransferDirection.RECEIVE))
                if index % 3 == 0:
                    manager.unregister_transfer(f"seed-{index}")
                index += 1

        workers = [threading.Thread(target=iterate), threading.Thread(target=mutate),
                   threading.Thread(target=mutate)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
        self.assertEqual(errors, [], f"es zamanli dolasma hata verdi: {errors[:1]}")


# --------------------------------------------------------------------------- FILE_INFO dogrulama / disk

class FileInfoValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=CHUNK).start()
        self.addCleanup(self.lb.stop)

    def _info(self, **overrides):
        peer = RawPeer(self.lb.server.port)
        self.addCleanup(peer.close)
        peer.handshake()
        message = Protocol.create_file_info("v-1", "v.bin", 10, "")
        message["data"].update(overrides)  # gecerli bir mesajin alanlarini bozuk degerlerle degistir
        peer.send(message)
        return peer.recv()

    def test_invalid_filesize_values_are_rejected(self) -> None:
        for bad in (-1, 2 ** 60, "100", 1.5, True, None, [1]):
            with self.subTest(filesize=bad):
                msg_type, data = self._info(filesize=bad)
                self.assertEqual(msg_type, MessageType.FILE_INFO_REJECT, f"{bad!r} kabul edildi")
                self.assertIn("boyut", data.get("reason", ""))
        self.assertEqual(self.lb.list_downloads(), [])

    def test_invalid_ids_and_names_are_rejected(self) -> None:
        for field, bad in (("transfer_id", 5), ("transfer_id", ""), ("transfer_id", "x" * 500),
                           ("filename", None), ("filename", "   "), ("filename", ["a"]),
                           ("relative_path", 12), ("folder_total", "9"), ("folder_name", {"a": 1})):
            with self.subTest(field=field, value=bad):
                msg_type, _ = self._info(**{field: bad})
                self.assertEqual(msg_type, MessageType.FILE_INFO_REJECT)

    def test_missing_fields_do_not_crash_connection_handler(self) -> None:
        peer = RawPeer(self.lb.server.port)
        self.addCleanup(peer.close)
        peer.handshake()
        message = Protocol.create_file_info("m-1", "m.bin", 10, "")
        del message["data"]["filesize"]
        peer.send(message)
        msg_type, _ = peer.recv()
        self.assertEqual(msg_type, MessageType.FILE_INFO_REJECT)

    def test_data_beyond_declared_size_is_refused(self) -> None:
        peer = RawPeer(self.lb.server.port)
        self.addCleanup(peer.close)
        peer.handshake()
        msg_type, _ = peer.file_info("o-1", "o.bin", 1000)
        self.assertEqual(msg_type, MessageType.FILE_INFO_ACK)
        peer.send(Protocol.create_chunk_data("o-1", 0, 1))
        peer.send_raw(struct.pack("!I", 5000))  # bildirilenden buyuk parca
        self.assertTrue(self.lb.wait_recv("o-1"))
        msg_type, data = peer.recv()
        self.assertEqual(msg_type, MessageType.TRANSFER_ERROR)
        self.assertIn("fazla veri", data.get("error", ""))
        peer.close()
        self.lb.settle()
        self.assertEqual(self.lb.recv_transfer("o-1").status.value, "failed")
        self.assertNotIn("o.bin", self.lb.list_downloads())


class DiskSpaceTest(unittest.TestCase):
    Usage = collections.namedtuple("Usage", "total used free")

    def test_insufficient_free_space_is_rejected_with_reason(self) -> None:
        with Loopback(chunk_size=CHUNK).start() as lb:
            with mock.patch.object(server_module.shutil, "disk_usage",
                                   return_value=self.Usage(10 ** 9, 10 ** 9 - 5000, 5000)):
                peer = RawPeer(lb.server.port)
                self.addCleanup(peer.close)
                peer.handshake()
                msg_type, data = peer.file_info("d-1", "d.bin", 50 * 1024 * 1024)
            self.assertEqual(msg_type, MessageType.FILE_INFO_REJECT)
            self.assertIn("Diskte yeterli boş alan yok", data.get("reason", ""))
            self.assertEqual(lb.list_downloads(), [], ".part/meta olusmamali")

    def test_empty_file_is_accepted_even_when_disk_is_full(self) -> None:
        with Loopback(chunk_size=CHUNK).start() as lb:
            with mock.patch.object(server_module.shutil, "disk_usage",
                                   return_value=self.Usage(10 ** 9, 10 ** 9, 0)):
                peer = RawPeer(lb.server.port)
                self.addCleanup(peer.close)
                peer.handshake()
                msg_type, _ = peer.file_info("d-2", "empty.bin", 0)
            self.assertEqual(msg_type, MessageType.FILE_INFO_ACK)

    def test_sender_ui_shows_receiver_disk_reason_without_retry(self) -> None:
        with Loopback(chunk_size=CHUNK).start() as lb:
            lb.client._retry_delays = (0.05, 0.05)
            src = write_file(os.path.join(lb.source_dir, "big.bin"), make_bytes(100000, seed=6))
            connections = []
            real_accept = lb.server._client_main

            def counting_main(sock, addr):
                connections.append(addr)
                return real_accept(sock, addr)

            with mock.patch.object(lb.server, "_client_main", counting_main):
                with mock.patch.object(server_module.shutil, "disk_usage",
                                       return_value=self.Usage(10 ** 9, 10 ** 9 - 10, 10)):
                    transfer = lb.send(src)
                    self.assertTrue(lb.wait_send(transfer, 20))
            self.assertEqual(transfer.status.value, "failed")
            self.assertIn("Diskte yeterli boş alan yok", transfer.error_message)
            self.assertEqual(len(connections), 1, "alici reddi yeniden denendi")


# --------------------------------------------------------------------------- baglanti siniri

class ConnectionLimitTest(unittest.TestCase):
    def _raw_connect(self, port):
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.addCleanup(sock.close)
        return sock

    def test_connections_over_limit_are_dropped_and_slots_are_released(self) -> None:
        with Loopback().start() as lb:
            lb.server.MAX_CONNECTIONS = 3
            held = [self._raw_connect(lb.server.port) for _ in range(3)]
            self.assertTrue(wait_until(lambda: lb.server._active_clients == 3))

            extra = self._raw_connect(lb.server.port)
            extra.settimeout(3)
            try:
                dropped = extra.recv(1) == b""
            except (ConnectionError, OSError):
                dropped = True
            self.assertTrue(dropped, "sinir asan baglanti kapatilmadi")
            self.assertEqual(lb.server._active_clients, 3)

            held[0].close()  # bir yuva bosalsin
            self.assertTrue(wait_until(lambda: lb.server._active_clients == 2, 10))
            peer = RawPeer(lb.server.port)
            self.addCleanup(peer.close)
            msg_type, _ = peer.handshake()
            self.assertEqual(msg_type, MessageType.HANDSHAKE_ACK, "yuva serbest kalinca yeni baglanti kabul edilmedi")

    def test_finished_client_threads_are_pruned(self) -> None:
        with Loopback().start() as lb:
            for _ in range(40):
                sock = socket.create_connection(("127.0.0.1", lb.server.port), timeout=5)
                sock.close()
            time.sleep(0.5)
            # Temizlik kabul sirasinda yapilir: iki baglanti daha acip listeyi denetle
            keep = [socket.create_connection(("127.0.0.1", lb.server.port), timeout=5) for _ in range(2)]
            for sock in keep:
                self.addCleanup(sock.close)
                time.sleep(0.2)
            self.assertTrue(wait_until(lambda: len(lb.server.client_threads) <= 4, 5),
                            f"biten thread'ler temizlenmedi: {len(lb.server.client_threads)}")

    def test_stop_returns_promptly_with_idle_connections(self) -> None:
        lb = Loopback().start()
        socks = [socket.create_connection(("127.0.0.1", lb.server.port), timeout=5) for _ in range(10)]
        started = time.time()
        lb.server.stop()  # varsayilan (3 sn) bekleme ust siniri; eskiden her thread icin 2 sn = 20 sn
        elapsed = time.time() - started
        for sock in socks:
            sock.close()
        self.assertLess(elapsed, 6.0, f"stop() cok uzun surdu: {elapsed:.1f}s")


# --------------------------------------------------------------------------- bayat / yarisan alicilar

class StaleReceiverTest(unittest.TestCase):
    PAYLOAD = make_bytes(6 * CHUNK + 777, seed=51)

    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=CHUNK).start()
        self.addCleanup(self.lb.stop)
        self.sender_id = get_local_fingerprint()

    def _start(self, fingerprint, tid, chunks):
        peer = RawPeer(self.lb.server.port, fingerprint=fingerprint)
        self.addCleanup(peer.close)
        peer.handshake(proto=2, features=FEATURES)
        msg_type, ack = peer.file_info(tid, "s.bin", len(self.PAYLOAD), extra={"mtime_ns": 777})
        self.assertEqual(msg_type, MessageType.FILE_INFO_ACK, ack)
        for index in range(chunks):
            reply, _ = peer.chunk(tid, index, 7, self.PAYLOAD[index * CHUNK:(index + 1) * CHUNK])
            self.assertEqual(reply, MessageType.CHUNK_ACK)
        return peer, ack

    def test_retry_with_same_transfer_id_supersedes_stale_connection(self) -> None:
        stale, _ = self._start(self.sender_id, "same-id", 2)  # kopmus ama bagli gorunen bayat baglanti
        retry = RawPeer(self.lb.server.port, fingerprint=self.sender_id)
        self.addCleanup(retry.close)
        retry.handshake(proto=2, features=FEATURES)
        msg_type, ack = retry.file_info("same-id", "s.bin", len(self.PAYLOAD), extra={"mtime_ns": 777})
        self.assertEqual(msg_type, MessageType.FILE_INFO_ACK, "bayat baglanti yeni denemeyi engelledi")
        self.assertEqual(ack.get("resumed_bytes"), 2 * CHUNK, "bayat yazicinin verisi diske yazilmadan devam edildi")

        total = 7
        for index in range(2, total):
            reply, _ = retry.chunk("same-id", index, total, self.PAYLOAD[index * CHUNK:(index + 1) * CHUNK])
            self.assertEqual(reply, MessageType.CHUNK_ACK)
        ack_type, ack_data = retry.complete("same-id", sha256_hex(self.PAYLOAD))
        self.assertEqual(ack_type, MessageType.TRANSFER_COMPLETE_ACK, (ack_type, ack_data))
        self.assertTrue(ack_data["success"])
        self.assertTrue(self.lb.wait_recv("same-id"))
        retry.close()
        stale.close()
        self.lb.settle()
        self.assertEqual(self.lb.recv_transfer("same-id").status.value, "completed",
                         "bayat is parcacigi yeni transferi basarisiz isaretledi")
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "s.bin")), self.PAYLOAD)
        self.assertEqual(self.lb.list_downloads(), ["s.bin"])

    def test_different_transfer_for_same_file_is_rejected_while_active(self) -> None:
        active, _ = self._start(self.sender_id, "first-t", 1)
        other = RawPeer(self.lb.server.port, fingerprint="77" * 32)
        self.addCleanup(other.close)
        other.handshake(proto=2, features=FEATURES)
        msg_type, data = other.file_info("other-t", "s.bin", len(self.PAYLOAD), extra={"mtime_ns": 777})
        self.assertEqual(msg_type, MessageType.FILE_INFO_REJECT)
        self.assertIn("başka bir transferde", data.get("reason", ""))
        # ilk transfer etkilenmedi
        reply, _ = active.chunk("first-t", 1, 7, self.PAYLOAD[CHUNK:2 * CHUNK])
        self.assertEqual(reply, MessageType.CHUNK_ACK)


# --------------------------------------------------------------------------- hata siniflandirma

class ErrorClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = TCPServer(TransferManager())
        cls.client = TCPClient(TransferManager())

    def fmt(self, error) -> str:
        return self.server._format_receiver_error(error)

    def test_disk_full_by_errno(self) -> None:
        self.assertEqual(self.fmt(DiskWriteError(OSError(errno.ENOSPC, "No space left on device"))),
                         "Diskte yeterli boş alan yok.")

    @unittest.skipUnless(sys.platform == "win32", "winerror yalnizca Windows'ta")
    def test_windows_error_codes(self) -> None:
        self.assertEqual(self.fmt(DiskWriteError(OSError(0, "There is not enough space on the disk", None, 112))),
                         "Diskte yeterli boş alan yok.")
        self.assertIn("kilitlendi", self.fmt(DiskWriteError(OSError(13, "sharing violation", None, 32))))
        self.assertIn("Erişim engellendi", self.fmt(DiskWriteError(OSError(13, "Access is denied", None, 5))))

    def test_digits_in_message_do_not_cause_false_positives(self) -> None:
        # Eskiden "32" / "5" metinde gecince "kilitlendi"/"erisim engellendi" denirdi
        error = DiskWriteError(OSError(errno.EIO, "I/O error at C:\\tmp\\file_5_32_112.bin"))
        text = self.fmt(error)
        self.assertNotIn("kilitlendi", text)
        self.assertNotIn("Erişim engellendi", text)
        self.assertNotIn("Diskte yeterli", text)
        self.assertIn("file_5_32_112.bin", text, "mesaj kesildi")

    def test_long_messages_are_not_cut_at_40_chars(self) -> None:
        text = self.fmt(Exception("x" * 150 + "SON"))
        self.assertIn("SON", text)
        self.assertLessEqual(len(text), 220)

    def test_network_and_timeout_classes(self) -> None:
        self.assertIn("koptu", self.fmt(ConnectionResetError(errno.ECONNRESET, "reset")))
        self.assertIn("Zaman aşımı", self.fmt(socket.timeout("timed out")))
        self.assertNotIn("Zaman aşımı", self.fmt(DiskWriteError(TimeoutError("diske yazma zaman aşımı"))))

    def test_special_exception_types(self) -> None:
        self.assertIn("SHA-256", self.fmt(IntegrityError("x")))
        self.assertEqual(self.fmt(SenderProtocolError("fazla veri")), "fazla veri")
        chained = Exception("Dosya tamamlanamadı (hedef kilitli olabilir): x")
        self.assertIn("kilitli", self.fmt(chained))

    def test_client_user_error_translates_timeouts(self) -> None:
        for error in (socket.timeout("timed out"), TimeoutError("timed out"), Exception("The read operation timed out")):
            with self.subTest(error=repr(error)):
                self.assertTrue(self.client._user_error(error).startswith("Zaman aşımı"))

    def test_client_user_error_connection_classes(self) -> None:
        self.assertIn("bağlanılamadı", self.client._user_error(ConnectionRefusedError(errno.ECONNREFUSED, "refused")))
        self.assertIn("kapattı", self.client._user_error(ConnectionResetError(errno.ECONNRESET, "reset")))
        self.assertTrue(self.client._user_error(ReceiverReportedError("Disk dolu")).endswith("Disk dolu"))
        self.assertIn("onayı alınamadı", self.client._user_error(CompletionNotConfirmed("x")))


if __name__ == "__main__":
    unittest.main()
