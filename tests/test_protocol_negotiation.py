"""Protokol yetenek anlasmasi (handshake proto/features) ve zarf surumu testleri."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import FakeReceiver, Loopback, RawPeer, make_bytes, read_file, write_file  # noqa: E402

from src.core.protocol import MessageType, Protocol  # noqa: E402


class NegotiateFeaturesTest(unittest.TestCase):
    def test_legacy_peer_has_no_features(self) -> None:
        self.assertEqual(Protocol.negotiate_features({}), frozenset())
        self.assertEqual(Protocol.negotiate_features({"device_name": "x"}), frozenset())
        self.assertEqual(Protocol.negotiate_features(None), frozenset())
        self.assertEqual(Protocol.negotiate_features("junk"), frozenset())

    def test_proto_without_features_or_old_proto_is_legacy(self) -> None:
        self.assertEqual(Protocol.negotiate_features({"proto": 2}), frozenset())
        self.assertEqual(Protocol.negotiate_features({"proto": 1, "features": ["sha256"]}), frozenset())
        self.assertEqual(Protocol.negotiate_features({"proto": True, "features": ["sha256"]}), frozenset())
        self.assertEqual(Protocol.negotiate_features({"proto": "2", "features": ["sha256"]}), frozenset())
        self.assertEqual(Protocol.negotiate_features({"proto": 2, "features": "sha256"}), frozenset())

    def test_only_common_known_features_are_enabled(self) -> None:
        got = Protocol.negotiate_features(
            {"proto": 2, "features": ["sha256", "complete_ack", "from_the_future", 7, None]}
        )
        self.assertEqual(got, frozenset({"sha256", "complete_ack"}))
        full = Protocol.negotiate_features({"proto": 3, "features": list(Protocol.LOCAL_FEATURES)})
        self.assertEqual(full, frozenset(Protocol.LOCAL_FEATURES))

    def test_envelope_version_major_check(self) -> None:
        self.assertTrue(Protocol.is_compatible_version({"version": "1.0"}))
        self.assertTrue(Protocol.is_compatible_version({"version": "1.7"}))
        self.assertTrue(Protocol.is_compatible_version({"type": "handshake"}))  # eski/eksik: uyumlu
        self.assertFalse(Protocol.is_compatible_version({"version": "2.0"}))
        self.assertFalse(Protocol.is_compatible_version(["not", "a", "dict"]))

    def test_parse_message_survives_non_dict_payloads(self) -> None:
        for junk in (None, [], [1, 2], "text", 5):
            self.assertEqual(Protocol.parse_message(junk), (None, {}))
        self.assertEqual(Protocol.parse_message({"type": "handshake", "data": "oops"}), (None, {}))
        self.assertEqual(Protocol.parse_message({"type": ["unhashable"]}), (None, {}))


class HandshakeWireTest(unittest.TestCase):
    def test_client_handshake_advertises_proto_and_features(self) -> None:
        seen = {}

        def handler(conn: FakeReceiver.Conn) -> None:
            msg_type, data = conn.recv()
            seen["type"], seen["data"] = msg_type, data
            conn.send(Protocol.create_handshake_reject("test_stop"))

        with FakeReceiver(handler) as fake:
            lb = Loopback()
            src = write_file(os.path.join(lb.source_dir, "a.bin"), b"x" * 10)
            lb.server.port = fake.port  # yalnizca hedef port icin; sunucu baslatilmiyor
            transfer = lb.send(src)
            self.assertTrue(lb.wait_send(transfer))

        self.assertEqual(seen["type"], MessageType.HANDSHAKE)
        self.assertEqual(seen["data"]["proto"], Protocol.PROTO_VERSION)
        self.assertEqual(set(seen["data"]["features"]), set(Protocol.LOCAL_FEATURES))

    def test_server_ack_advertises_proto_and_features(self) -> None:
        with Loopback().start() as lb:
            peer = RawPeer(lb.server.port)
            self.addCleanup(peer.close)
            msg_type, data = peer.handshake(proto=2, features=["sha256"])
            self.assertEqual(msg_type, MessageType.HANDSHAKE_ACK)
            self.assertEqual(data["proto"], Protocol.PROTO_VERSION)
            self.assertEqual(set(data["features"]), set(Protocol.LOCAL_FEATURES))

    def test_incompatible_envelope_version_is_rejected(self) -> None:
        with Loopback().start() as lb:
            peer = RawPeer(lb.server.port)
            self.addCleanup(peer.close)
            message = Protocol.create_handshake("Future", "host", fingerprint="cd" * 32)
            message["version"] = "2.0"
            peer.send(message)
            msg_type, data = peer.recv()
            self.assertEqual(msg_type, MessageType.HANDSHAKE_REJECT)
            self.assertEqual(data.get("reason"), "unsupported_version")

    def test_legacy_sender_without_proto_still_transfers(self) -> None:
        """Eski surum gonderici (proto/features yok) hala dosya gonderebilmeli."""
        with Loopback().start() as lb:
            peer = RawPeer(lb.server.port)
            self.addCleanup(peer.close)
            msg_type, _ = peer.handshake()  # proto/features YOK
            self.assertEqual(msg_type, MessageType.HANDSHAKE_ACK)
            payload = make_bytes(30000, seed=11)
            msg_type, _ = peer.file_info("legacy-1", "legacy.bin", len(payload))
            self.assertEqual(msg_type, MessageType.FILE_INFO_ACK)
            half = 16384
            self.assertEqual(peer.chunk("legacy-1", 0, 2, payload[:half])[0], MessageType.CHUNK_ACK)
            self.assertEqual(peer.chunk("legacy-1", 1, 2, payload[half:])[0], MessageType.CHUNK_ACK)
            ack_type, ack_data = peer.complete("legacy-1")
            self.assertEqual(ack_type, MessageType.TRANSFER_COMPLETE_ACK)
            self.assertTrue(ack_data.get("success"))
            self.assertTrue(lb.wait_recv("legacy-1"))
            lb.settle()
            self.assertEqual(read_file(os.path.join(lb.download_dir, "legacy.bin")), payload)


class FinalizeFailureCompatTest(unittest.TestCase):
    """Kaydetme (os.replace) asamasi basarisiz olursa gonderici bunu hata olarak gormeli.

    Eski surum gonderici yalnizca 'kaydedemedi' kalibli TRANSFER_ERROR'u hata sayar; yeni
    surum gonderici ise duz alici metnini alir (kalip eklenmez).
    """

    PAYLOAD = make_bytes(20000, seed=61)

    def _upload_with_failing_finalize(self, lb, *, new_protocol: bool):
        peer = RawPeer(lb.server.port, fingerprint="aa" * 32)
        self.addCleanup(peer.close)
        if new_protocol:
            peer.handshake(proto=2, features=list(Protocol.LOCAL_FEATURES))
            peer.file_info("fin-1", "fin.bin", len(self.PAYLOAD), extra={"mtime_ns": 1})
        else:
            peer.handshake()
            peer.file_info("fin-1", "fin.bin", len(self.PAYLOAD))
        for index in range(2):
            peer.chunk("fin-1", index, 2, self.PAYLOAD[index * 16384:(index + 1) * 16384])
        checksum = support.sha256_hex(self.PAYLOAD) if new_protocol else ""
        return peer.complete("fin-1", checksum)

    def test_legacy_sender_gets_error_text_it_recognises(self) -> None:
        from unittest import mock
        with Loopback(chunk_size=16384).start() as lb:
            with mock.patch.object(type(lb.server), "_finalize_part",
                                   side_effect=Exception("Dosya tamamlanamadı (hedef kilitli olabilir): x")):
                msg_type, data = self._upload_with_failing_finalize(lb, new_protocol=False)
        self.assertEqual(msg_type, MessageType.TRANSFER_ERROR)
        self.assertIn("kaydedemedi", data["error"])

    def test_new_sender_gets_plain_receiver_text(self) -> None:
        from unittest import mock
        with Loopback(chunk_size=16384).start() as lb:
            with mock.patch.object(type(lb.server), "_finalize_part",
                                   side_effect=Exception("Dosya tamamlanamadı (hedef kilitli olabilir): x")):
                msg_type, data = self._upload_with_failing_finalize(lb, new_protocol=True)
        self.assertEqual(msg_type, MessageType.TRANSFER_ERROR)
        self.assertNotIn("kaydedemedi", data["error"])
        self.assertIn("kilitli", data["error"])


if __name__ == "__main__":
    unittest.main()
