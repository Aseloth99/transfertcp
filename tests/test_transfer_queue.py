"""Sırada bekleyen transferlerin açık gösterimi + kopma tanısı günlüğü.

Kullanıcı, gönderici yuvası (aynı anda en fazla N gönderim) dolu olduğu için 0 B'de "Bekliyor..."
gören transferleri takılma sanıyordu. Burada: (1) durum/metin seçimi saf fonksiyonla, (2) gerçek
TCPClient'ta yuva dolunca `queued_for_slot` işaretlenmesi, iptalin yuvayı sızdırmaması,
(3) başarısız/yeniden denenen denemelerde tanı satırı (süre, parça, bayt, son ACK gecikmesi).
"""

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import FakeReceiver, Loopback, make_bytes, wait_until, write_file  # noqa: E402

from src.core.protocol import MessageType, Protocol  # noqa: E402
from src.models.transfer import Transfer, TransferDirection, TransferStatus  # noqa: E402
from src.utils import transfer_labels  # noqa: E402
from src.utils.locales import t  # noqa: E402

FEATURES = tuple(Protocol.LOCAL_FEATURES)


def make_transfer(**overrides) -> Transfer:
    transfer = Transfer("tid", "/x/f.bin", "f.bin", 100, "10.0.0.2", "Peer", TransferDirection.SEND)
    for key, value in overrides.items():
        setattr(transfer, key, value)
    return transfer


class LabelSelectionTest(unittest.TestCase):
    def test_queued_transfer_shows_explicit_queue_text_with_limit(self) -> None:
        transfer = make_transfer(queued_for_slot=True, queue_limit=3)
        self.assertEqual(transfer_labels.wait_state(transfer), transfer_labels.QUEUED)
        info, speed, _color = transfer_labels.wait_labels(transfer, "tr")
        self.assertIsNone(info)  # "boyut - cihaz" satiri aynen kalir
        self.assertEqual(speed, "Sırada (aynı anda en fazla 3)")
        self.assertEqual(transfer_labels.wait_labels(transfer, "en")[1], "Queued (max 3 at once)")
        self.assertNotIn("Bekliyor", speed)

    def test_plain_pending_is_not_called_queued(self) -> None:
        transfer = make_transfer()  # yuvayi henuz sormadi
        self.assertEqual(transfer_labels.wait_state(transfer), transfer_labels.PENDING)
        self.assertEqual(transfer_labels.wait_labels(transfer, "tr")[1], t("status_pending_short", "tr"))

    def test_retry_keeps_retrying_wording_with_attempt_number(self) -> None:
        transfer = make_transfer(status=TransferStatus.CONNECTING, retry_attempt=2)
        self.assertEqual(transfer_labels.wait_state(transfer), transfer_labels.RETRYING)
        info, speed, color = transfer_labels.wait_labels(transfer, "tr")
        self.assertEqual(info, "Yeniden deneniyor (2)…")
        self.assertEqual(speed, "Yeniden deneniyor…")
        self.assertEqual(color, "warn")
        self.assertEqual(transfer_labels.wait_labels(transfer, "en")[0], "Retrying (2)…")

    def test_first_connect_is_awaiting_approval_not_retrying(self) -> None:
        transfer = make_transfer(status=TransferStatus.CONNECTING, retry_attempt=0)
        self.assertEqual(transfer_labels.wait_state(transfer), transfer_labels.CONNECTING)
        self.assertEqual(transfer_labels.wait_labels(transfer, "tr")[1], t("status_waiting_approval", "tr"))

    def test_active_and_finished_transfers_are_not_wait_states(self) -> None:
        for status in (TransferStatus.TRANSFERRING, TransferStatus.PAUSED, TransferStatus.COMPLETED,
                       TransferStatus.FAILED, TransferStatus.CANCELLED):
            with self.subTest(status=status):
                transfer = make_transfer(status=status, queued_for_slot=True, queue_limit=2)
                self.assertEqual(transfer_labels.wait_state(transfer), transfer_labels.OTHER)
                self.assertIsNone(transfer_labels.wait_labels(transfer, "tr"))

    def test_queue_limit_is_clamped_to_at_least_one(self) -> None:
        self.assertEqual(transfer_labels.queued_text(0, "en"), "Queued (max 1 at once)")
        self.assertEqual(transfer_labels.queued_text(None, "tr"), "Sırada (aynı anda en fazla 1)")

    def test_both_languages_have_the_new_string(self) -> None:
        for lang in ("tr", "en"):
            self.assertIn("{n}", t("transfer_queued", lang))

    def test_creating_a_transfer_item_never_flashes_a_top_level_window(self) -> None:
        # Düğmelere parent'sız iken setVisible(True) demek, klasör gönderirken her dosya için
        # ekranda anlık küçük bir pencere (26x26) açıp kapatıyordu. Qt platformundan bağımsız olsun diye
        # parent'ı olmayan bir widget'ın görünür yapılması doğrudan yakalanır.
        from unittest import mock
        from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton
        support.qt_app()
        import src.gui.transfer_item as item_module
        flashed: list = []

        def spying(base):
            class Spy(base):
                def setVisible(self, visible):  # noqa: N802
                    if visible and self.parent() is None:
                        flashed.append(base.__name__)
                    super().setVisible(visible)

                def show(self):
                    self.setVisible(True)
            return Spy

        with mock.patch.object(item_module, "QPushButton", spying(QPushButton)),              mock.patch.object(item_module, "QLabel", spying(QLabel)),              mock.patch.object(item_module, "QProgressBar", spying(QProgressBar)):
            widget = item_module.TransferItemWidget(make_transfer(queued_for_slot=True, queue_limit=2))
        self.addCleanup(widget.update_timer.stop)
        self.assertEqual(flashed, [])

    def test_transfer_item_widget_renders_the_queue_text(self) -> None:
        support.qt_app()
        from src.gui.transfer_item import TransferItemWidget
        transfer = make_transfer(queued_for_slot=True, queue_limit=2)
        widget = TransferItemWidget(transfer)
        self.addCleanup(widget.update_timer.stop)
        widget.lang = "tr"
        widget._update_ui()
        self.assertEqual(widget.speed_label.text(), "Sırada (aynı anda en fazla 2)")
        self.assertIn("Peer", widget.info_label.text())
        transfer.queued_for_slot = False
        transfer.status = TransferStatus.CONNECTING
        transfer.retry_attempt = 1
        widget._update_ui()
        self.assertEqual(widget.info_label.text(), "Yeniden deneniyor (1)…")


def gated_receiver(gate: threading.Event, *, drop_after_chunks=None):
    """Handshake yanıtını `gate` açılana kadar tutan sahte alıcı (gönderici yuvasını meşgul eder)."""

    def handler(conn: FakeReceiver.Conn) -> None:
        conn.recv()  # handshake
        gate.wait(15)
        conn.send(Protocol.create_handshake_ack(
            fingerprint="ef" * 32, supports_encryption=False,
            proto=Protocol.PROTO_VERSION, features=FEATURES))
        _t, info = conn.recv()  # FILE_INFO
        conn.send(Protocol.create_file_info_ack(info["transfer_id"]))
        total, got, chunks = info["filesize"], 0, 0
        while got < total:
            _t, chunk_data = conn.recv()
            payload = conn.recv_chunk_payload()
            if drop_after_chunks is not None and chunks >= drop_after_chunks:
                return  # bağlantı ACK'siz kopar
            got += len(payload)
            chunks += 1
            conn.send(Protocol.create_chunk_ack(info["transfer_id"], chunk_data["chunk_index"]))
        conn.recv()  # TRANSFER_COMPLETE
        conn.send(Protocol.create_transfer_complete_ack(info["transfer_id"], success=True))

    return handler


class SendSlotQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=16384)
        self.lb.client._max_concurrent = 1
        self.lb.client._send_semaphore = threading.Semaphore(1)
        self.src = write_file(os.path.join(self.lb.source_dir, "q.bin"), make_bytes(40000, seed=7))

    def _send(self, port: int):
        transfer = self.lb.send_mgr.create_transfer(
            self.src, "127.0.0.1", "Peer", TransferDirection.SEND, device_port=port)
        self.lb.send_mgr.queue_transfer(transfer)
        self.lb.client.send_file(transfer)
        return transfer

    def test_second_transfer_is_explicitly_queued_then_runs(self) -> None:
        gate = threading.Event()
        with FakeReceiver(gated_receiver(gate)) as receiver:
            first = self._send(receiver.port)
            self.assertTrue(wait_until(lambda: first.status == TransferStatus.CONNECTING, 5))
            second = self._send(receiver.port)
            self.assertTrue(wait_until(lambda: second.queued_for_slot, 5), "ikinci transfer sıraya alınmadı")
            self.assertEqual(second.queue_limit, 1)
            self.assertEqual(second.status, TransferStatus.PENDING)
            self.assertEqual(transfer_labels.wait_state(second), transfer_labels.QUEUED)
            self.assertFalse(first.queued_for_slot, "çalışan transfer sırada gösterilmemeli")

            gate.set()
            self.assertTrue(self.lb.wait_send(first, 20), "ilk transfer bitmedi")
            self.assertTrue(self.lb.wait_send(second, 20), "sıradaki transfer çalışmadı")
            self.assertEqual(first.status, TransferStatus.COMPLETED)
            self.assertEqual(second.status, TransferStatus.COMPLETED)
            self.assertFalse(second.queued_for_slot, "sıradan çıkınca işaret temizlenmeli")
            self.assertEqual(receiver.errors, [])

    def test_cancel_while_queued_returns_promptly_and_does_not_leak_the_slot(self) -> None:
        gate = threading.Event()
        with FakeReceiver(gated_receiver(gate)) as receiver:
            first = self._send(receiver.port)
            self.assertTrue(wait_until(lambda: first.status == TransferStatus.CONNECTING, 5))
            second = self._send(receiver.port)
            self.assertTrue(wait_until(lambda: second.queued_for_slot, 5))

            self.lb.send_mgr.cancel_transfer(second.transfer_id)
            self.assertTrue(wait_until(lambda: not second.queued_for_slot, 3), "iptal sıradaki iş parçacığını bırakmadı")
            self.assertTrue(wait_until(lambda: second.transfer_id not in self.lb.client._active_sends, 3))
            self.assertEqual(second.status, TransferStatus.CANCELLED)

            gate.set()
            self.assertTrue(self.lb.wait_send(first, 20))
            third = self._send(receiver.port)
            self.assertTrue(self.lb.wait_send(third, 20), "iptal edilen sıradaki transfer yuvayı sızdırdı")
            self.assertEqual(third.status, TransferStatus.COMPLETED)

    def test_free_slot_means_no_queue_flag(self) -> None:
        gate = threading.Event()
        gate.set()
        with FakeReceiver(gated_receiver(gate)) as receiver:
            transfer = self._send(receiver.port)
            self.assertTrue(self.lb.wait_send(transfer, 20))
            self.assertFalse(transfer.queued_for_slot)
            self.assertEqual(transfer.queue_limit, 0)


class DropDiagnosticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=16384)
        self.src = write_file(os.path.join(self.lb.source_dir, "d.bin"), make_bytes(16384 * 5, seed=8))

    def _send(self, port: int):
        transfer = self.lb.send_mgr.create_transfer(
            self.src, "127.0.0.1", "Peer", TransferDirection.SEND, device_port=port)
        self.lb.send_mgr.queue_transfer(transfer)
        self.lb.client.send_file(transfer)
        return transfer

    def test_retried_and_final_failures_log_chunk_bytes_and_ack_latency(self) -> None:
        gate = threading.Event()
        gate.set()
        self.lb.client._retry_delays = (0.05,)
        with FakeReceiver(gated_receiver(gate, drop_after_chunks=2)) as receiver:
            with self.assertLogs("TransferTCP", level="WARNING") as captured:
                transfer = self._send(receiver.port)
                self.assertTrue(self.lb.wait_send(transfer, 20))
        text = "\n".join(captured.output)
        self.assertEqual(transfer.status, TransferStatus.FAILED)
        retry_lines = [line for line in captured.output if "yeniden denenecek" in line]
        self.assertEqual(len(retry_lines), 1, text)
        for needle in ("süre=", "aşama=chunks", "parça=2/5", "gönderilen=32768/81920 B",
                       "son ACK gecikmesi=", "son ACK="):
            self.assertIn(needle, retry_lines[0])
        final_lines = [line for line in captured.output if "son deneme tanısı" in line]
        self.assertEqual(len(final_lines), 1, text)
        self.assertIn("parça=2/5", final_lines[0])

    def test_diag_describe_without_ack_and_before_start(self) -> None:
        from src.core.client import SendAttemptDiag
        diag = SendAttemptDiag()
        self.assertIn("son ACK gecikmesi=yok", diag.describe(100))
        self.assertIn("aşama=connect", diag.describe())
        self.assertEqual(self.lb.client._diag_text(make_transfer()), "deneme başlamadı")


if __name__ == "__main__":
    unittest.main()
