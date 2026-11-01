"""Gonderici tarafi: sahte basari onleme (TRANSFER_COMPLETE_ACK zorunlulugu, alici hatalari).

Madde 2: ACK yoksa basari sayilmaz, success=False / TRANSFER_ERROR metni gonderici
arayuzune iletilir, alici hatasi kalici (yeniden denenmez); eski alici (proto yok) icin
eski davranisa (ACK beklemeden kapatma = basari) dusulur.
"""

import errno
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import FakeReceiver, Loopback, make_bytes, read_file, write_file  # noqa: E402

from src.core.protocol import MessageType, Protocol  # noqa: E402

NEW_FEATURES = tuple(Protocol.LOCAL_FEATURES)


def scripted_receiver(on_final, *, legacy=False, on_chunk_error=None, reject_reason=None):
    """Chunk'lari duzgun alip son asamada `on_final(conn, file_info, complete_data)` calistiran sahte alici."""

    def handler(conn: FakeReceiver.Conn) -> None:
        conn.recv()  # handshake
        if legacy:
            conn.send(Protocol.create_handshake_ack(fingerprint="ef" * 32, supports_encryption=False))
        else:
            conn.send(Protocol.create_handshake_ack(
                fingerprint="ef" * 32, supports_encryption=False,
                proto=Protocol.PROTO_VERSION, features=NEW_FEATURES))
        _t, info = conn.recv()  # FILE_INFO
        if reject_reason:
            conn.send(Protocol.create_file_info_reject(info["transfer_id"], reject_reason))
            return
        conn.send(Protocol.create_file_info_ack(info["transfer_id"]))
        total, got = info["filesize"], 0
        while got < total:
            _t, chunk_data = conn.recv()
            payload = conn.recv_chunk_payload()
            if on_chunk_error is not None:
                on_chunk_error(conn)
                return
            got += len(payload)
            conn.send(Protocol.create_chunk_ack(info["transfer_id"], chunk_data["chunk_index"]))
        _t, complete = conn.recv()  # TRANSFER_COMPLETE
        on_final(conn, info, complete)

    return handler


class SenderCompletionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=16384)
        self.src = write_file(os.path.join(self.lb.source_dir, "f.bin"), make_bytes(40000, seed=2))
        # Yeniden deneme olsaydi baglanti sayisi artardi: kalici hata tek baglantida bitmeli
        self.lb.client._retry_delays = (0.05, 0.05)

    def _run(self, handler):
        with FakeReceiver(handler) as fake:
            self.lb.server.port = fake.port
            transfer = self.lb.send(self.src)
            self.assertTrue(self.lb.wait_send(transfer, 30), "gonderici sonuclanmadi")
            return transfer, fake.connections

    # ---- yeni surum alici
    def test_ack_success_true_completes(self) -> None:
        transfer, conns = self._run(scripted_receiver(
            lambda c, i, d: c.send(Protocol.create_transfer_complete_ack(i["transfer_id"], True))))
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(conns, 1)

    def test_ack_success_false_fails_with_receiver_message(self) -> None:
        transfer, conns = self._run(scripted_receiver(
            lambda c, i, d: c.send(Protocol.create_transfer_complete_ack(
                i["transfer_id"], False, error="Diskte yeterli boş alan yok."))))
        self.assertEqual(transfer.status.value, "failed", "success=False sahte basari sayildi")
        self.assertIn("Diskte yeterli boş alan yok.", transfer.error_message)
        self.assertTrue(transfer.error_message.startswith("Alıcı cihaz hatası:"))
        self.assertEqual(conns, 1, "alici hatasi yeniden denendi")

    def test_ack_success_missing_field_is_failure_for_new_receiver(self) -> None:
        def final(conn, info, complete):
            message = Protocol.create_transfer_complete_ack(info["transfer_id"], True)
            del message["data"]["success"]
            conn.send(message)
        transfer, _ = self._run(scripted_receiver(final))
        self.assertEqual(transfer.status.value, "failed")

    def test_transfer_error_text_is_shown_even_without_magic_keywords(self) -> None:
        transfer, conns = self._run(scripted_receiver(
            lambda c, i, d: c.send(Protocol.create_transfer_error(i["transfer_id"], "Beklenmedik alıcı sorunu 42"))))
        self.assertEqual(transfer.status.value, "failed")
        self.assertIn("Beklenmedik alıcı sorunu 42", transfer.error_message)
        self.assertEqual(conns, 1)

    def test_connection_closed_without_ack_is_not_success(self) -> None:
        transfer, conns = self._run(scripted_receiver(lambda c, i, d: None))
        self.assertEqual(transfer.status.value, "failed", "ACK yokken basari sayildi")
        self.assertIn("onay", transfer.error_message.lower())
        self.assertEqual(conns, 1, "onaysiz tamamlanma yeniden denendi (kopya riski)")

    def test_ack_timeout_is_not_success(self) -> None:
        def hang(conn, info, complete):
            import time
            time.sleep(4)
        with mock.patch("src.core.client.TRANSFER_TIMEOUT", 1.0):
            transfer, _ = self._run(scripted_receiver(hang))
        self.assertEqual(transfer.status.value, "failed")
        self.assertIn("onay", transfer.error_message.lower())

    def test_chunk_stage_transfer_error_is_permanent_and_visible(self) -> None:
        transfer, conns = self._run(scripted_receiver(
            lambda c, i, d: None,
            on_chunk_error=lambda c: c.send(Protocol.create_transfer_error("x", "Dosya diske yazılamadı (test)"))))
        self.assertEqual(transfer.status.value, "failed")
        self.assertIn("Dosya diske yazılamadı (test)", transfer.error_message)
        self.assertNotIn("Geçersiz yanıt", transfer.error_message)
        self.assertEqual(conns, 1, "parca asamasi alici hatasi 'gecersiz yanit' diye yeniden denendi")

    def test_file_info_reject_reason_is_shown(self) -> None:
        transfer, conns = self._run(scripted_receiver(lambda c, i, d: None, reject_reason="Diskte yeterli boş alan yok."))
        self.assertEqual(transfer.status.value, "failed")
        self.assertIn("Diskte yeterli boş alan yok.", transfer.error_message)
        self.assertEqual(conns, 1)

    # ---- eski surum alici (proto/features yok): eski davranis
    def test_legacy_receiver_closing_without_ack_is_still_success(self) -> None:
        transfer, _ = self._run(scripted_receiver(lambda c, i, d: None, legacy=True))
        self.assertEqual(transfer.status.value, "completed", "eski alici uyumu bozuldu")

    def test_legacy_receiver_explicit_error_is_surfaced(self) -> None:
        transfer, _ = self._run(scripted_receiver(
            lambda c, i, d: c.send(Protocol.create_transfer_error(i["transfer_id"], "Garip eski alıcı hatası")),
            legacy=True))
        self.assertEqual(transfer.status.value, "failed", "eski alicinin acik hatasi yutuldu")
        self.assertIn("Garip eski alıcı hatası", transfer.error_message)

    def test_legacy_receiver_ack_success_false_is_failure(self) -> None:
        transfer, _ = self._run(scripted_receiver(
            lambda c, i, d: c.send(Protocol.create_transfer_complete_ack(i["transfer_id"], False, error="olmadi")),
            legacy=True))
        self.assertEqual(transfer.status.value, "failed")


class SenderAgainstRealReceiverTest(unittest.TestCase):
    def test_real_server_success_roundtrip(self) -> None:
        payload = make_bytes(70000, seed=4)
        with Loopback(chunk_size=16384).start() as lb:
            src = write_file(os.path.join(lb.source_dir, "ok.bin"), payload)
            transfer = lb.send(src)
            self.assertTrue(lb.wait_send(transfer))
            lb.settle()
            self.assertEqual(transfer.status.value, "completed")
            self.assertEqual(read_file(os.path.join(lb.download_dir, "ok.bin")), payload)

    def test_real_server_write_failure_reaches_sender_ui(self) -> None:
        with Loopback(chunk_size=16384).start() as lb:
            os.makedirs(os.path.join(lb.download_dir, "boom.bin.part"))  # yazici .part'i acamaz
            src = write_file(os.path.join(lb.source_dir, "boom.bin"), make_bytes(200000, seed=8))
            lb.client._retry_delays = (0.05, 0.05)
            transfer = lb.send(src)
            self.assertTrue(lb.wait_send(transfer, 30))
            lb.settle()
            self.assertEqual(transfer.status.value, "failed")
            self.assertTrue(transfer.error_message.startswith("Alıcı cihaz hatası:"), transfer.error_message)


class SpeedLimitTest(unittest.TestCase):
    """Hiz siniri: gecen sure her parcada guncel hesaplanmali, devam edilen onek sinira sayilmamali."""

    CHUNK = 16384
    LIMIT = 16384 * 8  # 128 KB/s: parca basina ~0.125 sn

    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=self.CHUNK)
        self.lb.config.config["transfer"]["speed_limit"] = self.LIMIT
        self.addCleanup(self.lb.config.config["transfer"].__setitem__, "speed_limit", 0)

    def _send(self, size: int, resumed_bytes: int = 0):
        arrivals = []

        def handler(conn: FakeReceiver.Conn) -> None:
            conn.recv()  # handshake
            conn.send(Protocol.create_handshake_ack(
                fingerprint="ef" * 32, supports_encryption=False,
                proto=Protocol.PROTO_VERSION, features=NEW_FEATURES))
            _t, info = conn.recv()  # FILE_INFO
            conn.send(Protocol.create_file_info_ack(
                info["transfer_id"], resumed_from_chunk=resumed_bytes // self.CHUNK, resumed_bytes=resumed_bytes))
            got = resumed_bytes
            while got < info["filesize"]:
                _t, chunk_data = conn.recv()
                got += len(conn.recv_chunk_payload())
                arrivals.append(time.monotonic())
                conn.send(Protocol.create_chunk_ack(info["transfer_id"], chunk_data["chunk_index"]))
            conn.recv()  # TRANSFER_COMPLETE
            conn.send(Protocol.create_transfer_complete_ack(info["transfer_id"], True))

        src = write_file(os.path.join(self.lb.source_dir, "limit.bin"), make_bytes(size, seed=4))
        with FakeReceiver(handler) as fake:
            self.lb.server.port = fake.port
            started = time.monotonic()
            transfer = self.lb.send(src)
            self.assertTrue(self.lb.wait_send(transfer, 60), "gonderici sonuclanmadi")
            duration = time.monotonic() - started
        self.assertEqual(transfer.status.value, "completed")
        return duration, arrivals

    def test_pause_per_chunk_does_not_grow_with_bytes_sent(self) -> None:
        duration, arrivals = self._send(16 * self.CHUNK)
        budget = self.CHUNK / self.LIMIT
        gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
        # Dogru hesapta bekleme parca basina ~1-2 butce; eskiden gonderilen baytla buyuyordu (16. parcada ~1.5 sn)
        self.assertLess(max(gaps), 3 * budget + 0.2, f"parca arasi bekleme buyuyor: {gaps}")
        self.assertGreater(duration, 0.6 * 16 * budget, "hiz siniri uygulanmadi")

    def test_resumed_prefix_does_not_count_against_the_limit(self) -> None:
        resumed = 64 * self.CHUNK  # 1 MiB onceden alinmis: sinira sayilsaydi ilk parcada ~8 sn uyunurdu
        duration, arrivals = self._send(resumed + 4 * self.CHUNK, resumed_bytes=resumed)
        self.assertEqual(len(arrivals), 4)
        self.assertLess(duration, 3.0, "devam edilen onek hiz sinirina sayildi")


class SourceReadErrorTest(unittest.TestCase):
    """Kaynak okunurken hata (USB cikarildi, paylasim koptu): 'ag koptu' degil gercek neden gosterilmeli."""

    def test_read_error_keeps_its_own_classification(self) -> None:
        real_open = open

        class FailingHandle:
            def __init__(self, handle):
                self._handle, self._left = handle, 16384

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._handle.close()

            def seek(self, *args):
                return self._handle.seek(*args)

            def read(self, size=-1):
                if self._left <= 0:
                    raise PermissionError(errno.EACCES, "okuma reddedildi (test)")
                data = self._handle.read(min(size, self._left))
                self._left -= len(data)
                return data

        with Loopback(chunk_size=16384).start() as lb:
            src = write_file(os.path.join(lb.source_dir, "usb.bin"), make_bytes(100000, seed=8))
            with mock.patch("src.core.client.open", create=True,
                            side_effect=lambda path, *a, **k: FailingHandle(real_open(path, *a, **k))):
                transfer = lb.send(src)
                self.assertTrue(lb.wait_send(transfer, 30))
            lb.settle()
        self.assertEqual(transfer.status.value, "failed")
        self.assertNotIn("Ağ bağlantısı koptu", transfer.error_message)
        self.assertIn("erişim engellendi", transfer.error_message)


if __name__ == "__main__":
    unittest.main()
