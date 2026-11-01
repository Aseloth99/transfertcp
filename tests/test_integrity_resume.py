"""Butunluk (akis SHA-256) ve guvenli devam (.part.meta) testleri - loopback, UI yok.

Madde 3: ozet TRANSFER_COMPLETE icinde gider, alici dogrular, uyusmazlikta .part silinir;
devam etmeden once .part meta'si (ad/boyut/mtime/gonderici) eslesmeli, yoksa bastan baslanir.
Eski gonderici (features yok) icin eski, yalnizca-boyut devam davranisi korunur.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import FakeReceiver, Loopback, RawPeer, make_bytes, read_file, sha256_hex, write_file  # noqa: E402

from src.core.crypto import get_local_fingerprint  # noqa: E402
from src.core.protocol import MessageType, Protocol  # noqa: E402

FEATURES = list(Protocol.LOCAL_FEATURES)
CHUNK = 16384


def raw_partial_upload(lb, payload, name, *, chunks, fingerprint, mtime_ns, tid, features=FEATURES,
                       send_complete=False, checksum="", relative_path=None):
    """Yeni protokollu ham gonderici: `chunks` parca gonderip durur (ya da tamamlar)."""
    peer = RawPeer(lb.server.port, fingerprint=fingerprint)
    msg_type, _ = peer.handshake(proto=2 if features is not None else None, features=features)
    assert msg_type == MessageType.HANDSHAKE_ACK, msg_type
    extra = {"mtime_ns": mtime_ns} if mtime_ns is not None else None
    ack_type, ack = peer.file_info(tid, name, len(payload), extra=extra, relative_path=relative_path)
    assert ack_type == MessageType.FILE_INFO_ACK, (ack_type, ack)
    total = (len(payload) + CHUNK - 1) // CHUNK
    for index in range(chunks):
        reply, _ = peer.chunk(tid, index, total, payload[index * CHUNK:(index + 1) * CHUNK])
        assert reply == MessageType.CHUNK_ACK, reply
    result = None
    if send_complete:
        result = peer.complete(tid, checksum)
    return peer, ack, result


class StreamHashTest(unittest.TestCase):
    def test_end_to_end_checksum_is_computed_and_recorded(self) -> None:
        payload = make_bytes(100000, seed=21)
        with Loopback(chunk_size=CHUNK).start() as lb:
            src = write_file(os.path.join(lb.source_dir, "h.bin"), payload)
            transfer = lb.send(src)
            self.assertTrue(lb.wait_send(transfer))
            self.assertTrue(lb.wait_recv(transfer.transfer_id))
            lb.settle()
            self.assertEqual(transfer.status.value, "completed")
            self.assertEqual(transfer.checksum, sha256_hex(payload))
            self.assertEqual(lb.recv_transfer(transfer.transfer_id).checksum, sha256_hex(payload))
            self.assertEqual(lb.list_downloads(), ["h.bin"], "artik .part/.meta kalmamali")

    def test_empty_file_roundtrip(self) -> None:
        with Loopback(chunk_size=CHUNK).start() as lb:
            src = write_file(os.path.join(lb.source_dir, "empty.bin"), b"")
            transfer = lb.send(src)
            self.assertTrue(lb.wait_send(transfer))
            lb.settle()
            self.assertEqual(transfer.status.value, "completed")
            self.assertEqual(read_file(os.path.join(lb.download_dir, "empty.bin")), b"")
            self.assertEqual(lb.list_downloads(), ["empty.bin"])

    def test_wrong_checksum_is_rejected_and_part_removed(self) -> None:
        payload = make_bytes(40000, seed=22)
        with Loopback(chunk_size=CHUNK).start() as lb:
            peer, _, result = raw_partial_upload(
                lb, payload, "bad.bin", chunks=3, fingerprint="aa" * 32, mtime_ns=123, tid="bad-1",
                send_complete=True, checksum="0" * 64)
            self.addCleanup(peer.close)
            self.assertEqual(result[0], MessageType.TRANSFER_ERROR)
            self.assertIn("SHA-256", result[1].get("error", ""))
            self.assertTrue(lb.wait_recv("bad-1"))
            peer.close()
            lb.settle()
            self.assertEqual(lb.recv_transfer("bad-1").status.value, "failed")
            self.assertEqual(lb.list_downloads(), [], "bozuk dosya veya .part/.meta kaldi")

    def test_missing_checksum_is_rejected_when_sha256_negotiated(self) -> None:
        payload = make_bytes(20000, seed=23)
        with Loopback(chunk_size=CHUNK).start() as lb:
            peer, _, result = raw_partial_upload(
                lb, payload, "nochk.bin", chunks=2, fingerprint="aa" * 32, mtime_ns=1, tid="nochk-1",
                send_complete=True, checksum="")
            self.addCleanup(peer.close)
            self.assertEqual(result[0], MessageType.TRANSFER_ERROR)
            peer.close()
            lb.settle()
            self.assertEqual(lb.list_downloads(), [])

    def test_correct_checksum_from_raw_peer_is_accepted(self) -> None:
        payload = make_bytes(33000, seed=24)
        with Loopback(chunk_size=CHUNK).start() as lb:
            peer, _, result = raw_partial_upload(
                lb, payload, "good.bin", chunks=3, fingerprint="aa" * 32, mtime_ns=1, tid="good-1",
                send_complete=True, checksum=sha256_hex(payload))
            self.addCleanup(peer.close)
            self.assertEqual(result[0], MessageType.TRANSFER_COMPLETE_ACK)
            self.assertTrue(result[1]["success"])
            peer.close()
            lb.settle()
            self.assertEqual(read_file(os.path.join(lb.download_dir, "good.bin")), payload)
            self.assertEqual(lb.list_downloads(), ["good.bin"])

    def test_corruption_in_transit_is_detected_end_to_end(self) -> None:
        payload = make_bytes(100000, seed=25)
        flipped = []
        import src.core.client as client_module
        real_send_all = client_module.send_all

        def corrupting_send_all(sock, data):
            if not flipped and len(data) == 4 + CHUNK:  # ilk tam parca: yoldaki bit bozulmasi
                mutable = bytearray(data)
                mutable[4 + 100] ^= 0xFF
                flipped.append(True)
                data = bytes(mutable)
            real_send_all(sock, data)

        with Loopback(chunk_size=CHUNK).start() as lb:
            src = write_file(os.path.join(lb.source_dir, "corrupt.bin"), payload)
            with mock.patch.object(client_module, "send_all", corrupting_send_all):
                transfer = lb.send(src)
                self.assertTrue(lb.wait_send(transfer, 30))
            lb.settle()
            self.assertTrue(flipped)
            self.assertEqual(transfer.status.value, "failed", "bozulan veri basari sayildi")
            self.assertIn("SHA-256", transfer.error_message)
            self.assertEqual(lb.list_downloads(), [], "bozuk dosya kaydedildi")

    def test_sender_cancel_removes_part_and_meta(self) -> None:
        payload = make_bytes(60000, seed=26)
        with Loopback(chunk_size=CHUNK).start() as lb:
            peer, _, _ = raw_partial_upload(
                lb, payload, "cx.bin", chunks=1, fingerprint="aa" * 32, mtime_ns=5, tid="cx-1")
            self.addCleanup(peer.close)
            self.assertTrue(os.path.exists(os.path.join(lb.download_dir, "cx.bin.part.meta")))
            peer.cancel("cx-1")
            self.assertTrue(lb.wait_recv("cx-1"))
            peer.close()
            lb.settle()
            self.assertEqual(lb.list_downloads(), [])


class ResumeMetaTest(unittest.TestCase):
    PAYLOAD = make_bytes(7 * CHUNK + 1234, seed=31)  # 8 parca (son parca kismi)

    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=CHUNK).start()
        self.addCleanup(self.lb.stop)
        self.src = write_file(os.path.join(self.lb.source_dir, "r.bin"), self.PAYLOAD)
        self.mtime_ns = os.stat(self.src).st_mtime_ns
        self.sender_id = get_local_fingerprint()

    def _interrupted_first_attempt(self, **overrides) -> None:
        params = dict(chunks=2, fingerprint=self.sender_id, mtime_ns=self.mtime_ns, tid="first-1")
        params.update(overrides)
        peer, ack, _ = raw_partial_upload(self.lb, self.PAYLOAD, "r.bin", **params)
        self.assertNotIn("resumed_bytes", ack)
        peer.close()  # kopma
        self.assertTrue(self.lb.wait_recv(params["tid"]))
        self.lb.settle()
        part = os.path.join(self.lb.download_dir, "r.bin.part")
        self.assertTrue(os.path.exists(part), ".part devam icin korunmali")
        self.assertTrue(os.path.exists(part + ".meta"), "meta dosyasi yazilmali")

    def _real_send(self):
        with mock.patch.object(Protocol, "create_chunk_data", wraps=Protocol.create_chunk_data) as counter:
            transfer = self.lb.send(self.src)
            self.assertTrue(self.lb.wait_send(transfer, 30))
            self.assertTrue(self.lb.wait_recv(transfer.transfer_id))
            self.lb.settle()
        return transfer, counter.call_count

    def test_matching_part_is_resumed_and_result_is_byte_identical(self) -> None:
        self._interrupted_first_attempt(chunks=2)
        transfer, chunks_sent = self._real_send()
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(chunks_sent, 8 - 2, "devam edilmedi: tum parcalar yeniden gonderildi")
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "r.bin")), self.PAYLOAD)
        self.assertEqual(transfer.checksum, sha256_hex(self.PAYLOAD))
        self.assertEqual(self.lb.list_downloads(), ["r.bin"])

    def test_changed_source_mtime_forces_restart(self) -> None:
        self._interrupted_first_attempt(chunks=2, mtime_ns=self.mtime_ns - 5_000_000_000)
        transfer, chunks_sent = self._real_send()
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(chunks_sent, 8, "kaynak degismisken eski .part'a devam edildi")
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "r.bin")), self.PAYLOAD)

    def test_part_from_different_sender_forces_restart(self) -> None:
        self._interrupted_first_attempt(chunks=2, fingerprint="99" * 32)
        transfer, chunks_sent = self._real_send()
        self.assertEqual(chunks_sent, 8)
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "r.bin")), self.PAYLOAD)

    def test_part_without_meta_forces_restart(self) -> None:
        # Eski surumden kalma/bozuk .part: boyutu makul ama icerigi farkli ve meta yok
        write_file(os.path.join(self.lb.download_dir, "r.bin.part"), make_bytes(2 * CHUNK, seed=99))
        transfer, chunks_sent = self._real_send()
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(chunks_sent, 8, "metasiz .part'a devam edildi")
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "r.bin")), self.PAYLOAD)

    def test_corrupt_meta_forces_restart(self) -> None:
        self._interrupted_first_attempt(chunks=2)
        write_file(os.path.join(self.lb.download_dir, "r.bin.part.meta"), b"{not json")
        transfer, chunks_sent = self._real_send()
        self.assertEqual(chunks_sent, 8)
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "r.bin")), self.PAYLOAD)

    def test_fully_received_part_is_finalized_without_resending(self) -> None:
        payload = make_bytes(3 * CHUNK, seed=32)  # tam 3 parca
        src = write_file(os.path.join(self.lb.source_dir, "full.bin"), payload)
        mtime_ns = os.stat(src).st_mtime_ns
        # Alici tum veriyi aldi ama TRANSFER_COMPLETE gelmeden baglanti koptu
        peer, _, _ = raw_partial_upload(
            self.lb, payload, "full.bin", chunks=3, fingerprint=self.sender_id, mtime_ns=mtime_ns, tid="full-1")
        peer.close()
        self.assertTrue(self.lb.wait_recv("full-1"))
        self.lb.settle()
        self.assertTrue(os.path.exists(os.path.join(self.lb.download_dir, "full.bin.part")))
        self.assertFalse(os.path.exists(os.path.join(self.lb.download_dir, "full.bin")),
                         "TRANSFER_COMPLETE gelmeden dosya kesinlestirilmemeli")

        with mock.patch.object(Protocol, "create_chunk_data", wraps=Protocol.create_chunk_data) as counter:
            transfer = self.lb.send(src)
            self.assertTrue(self.lb.wait_send(transfer, 30))
            self.lb.settle()
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(counter.call_count, 0)
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "full.bin")), payload)

    def test_legacy_sender_still_resumes_by_size(self) -> None:
        """Eski gonderici (features yok): eski davranis, yalnizca boyuta gore devam."""
        peer = RawPeer(self.lb.server.port, fingerprint="ee" * 32)
        peer.handshake()  # proto/features YOK
        peer.file_info("old-1", "r.bin", len(self.PAYLOAD))
        for index in range(2):
            peer.chunk("old-1", index, 8, self.PAYLOAD[index * CHUNK:(index + 1) * CHUNK])
        peer.close()
        self.assertTrue(self.lb.wait_recv("old-1"))
        self.lb.settle()
        self.assertFalse(os.path.exists(os.path.join(self.lb.download_dir, "r.bin.part.meta")),
                         "eski gonderici icin meta yazilmamali")

        second = RawPeer(self.lb.server.port, fingerprint="ee" * 32)
        self.addCleanup(second.close)
        second.handshake()
        msg_type, ack = second.file_info("old-2", "r.bin", len(self.PAYLOAD))
        self.assertEqual(msg_type, MessageType.FILE_INFO_ACK)
        self.assertEqual(ack.get("resumed_bytes"), 2 * CHUNK, "eski davranis (boyuta gore devam) bozuldu")
        for index in range(2, 8):
            reply, _ = second.chunk("old-2", index, 8, self.PAYLOAD[index * CHUNK:(index + 1) * CHUNK])
            self.assertEqual(reply, MessageType.CHUNK_ACK)
        ack_type, ack_data = second.complete("old-2")
        self.assertEqual(ack_type, MessageType.TRANSFER_COMPLETE_ACK)
        self.assertTrue(ack_data["success"])
        second.close()
        self.assertTrue(self.lb.wait_recv("old-2"))
        self.lb.settle()
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "r.bin")), self.PAYLOAD)


class SenderResumeSanityTest(unittest.TestCase):
    def test_bogus_resume_offset_from_receiver_is_ignored(self) -> None:
        """Alici filesize'dan buyuk devam ofseti bildirirse gonderici bastan gonderir."""
        payload = make_bytes(50000, seed=41)
        received = bytearray()

        def handler(conn):
            conn.recv()
            conn.send(Protocol.create_handshake_ack(
                fingerprint="ef" * 32, supports_encryption=False, proto=2, features=FEATURES))
            _t, info = conn.recv()
            conn.send(Protocol.create_file_info_ack(info["transfer_id"], resumed_from_chunk=999, resumed_bytes=10**9))
            while len(received) < info["filesize"]:
                _t, chunk_data = conn.recv()
                received.extend(conn.recv_chunk_payload())
                conn.send(Protocol.create_chunk_ack(info["transfer_id"], chunk_data["chunk_index"]))
            _t, complete = conn.recv()
            conn.send(Protocol.create_transfer_complete_ack(
                info["transfer_id"], sha256_hex(bytes(received)) == complete["checksum"]))

        lb = Loopback(chunk_size=CHUNK)
        src = write_file(os.path.join(lb.source_dir, "s.bin"), payload)
        with FakeReceiver(handler) as fake:
            lb.server.port = fake.port
            transfer = lb.send(src)
            self.assertTrue(lb.wait_send(transfer, 30))
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(bytes(received), payload)


if __name__ == "__main__":
    unittest.main()
