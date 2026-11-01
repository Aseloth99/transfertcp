"""Alici tarafinda veri kaybi regresyon testleri (loopback, UI yok).

Madde 1: hata/iptal/eksik transferde yalnizca .part silinmeli; var olan saglam hedef
dosya korunmali; hedef zaten varsa benzersiz ad uretilmeli (sessiz uzerine yazma yok).
"""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402  (ilk import: sandbox)
from support import Loopback, RawPeer, make_bytes, read_file, write_file  # noqa: E402


def _replace_failing_for(path_matches):
    """os.replace yerine: `path_matches(src, dst)` doğruysa kilitli hedef gibi PermissionError verir."""
    real_replace = os.replace

    def replace(src, dst, *args, **kwargs):
        if path_matches(os.path.normcase(os.path.abspath(src)), os.path.normcase(os.path.abspath(dst))):
            raise PermissionError(13, "Erişim engellendi (test kilidi)", dst)
        return real_replace(src, dst, *args, **kwargs)

    return mock.patch("os.replace", side_effect=replace)


class ReceiveDataSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lb = Loopback(chunk_size=16384).start()
        self.addCleanup(self.lb.stop)
        self.existing = os.path.join(self.lb.download_dir, "data.bin")
        write_file(self.existing, b"KEEP-ME")

    def _open_peer(self) -> RawPeer:
        peer = RawPeer(self.lb.server.port)
        self.addCleanup(peer.close)
        msg_type, _ = peer.handshake()
        self.assertEqual(msg_type, peer.MessageType.HANDSHAKE_ACK)
        return peer

    def test_remote_cancel_keeps_existing_target(self) -> None:
        peer = self._open_peer()
        msg_type, _ = peer.file_info("t-cancel", "data.bin", 100000)
        self.assertEqual(msg_type, peer.MessageType.FILE_INFO_ACK)
        ack_type, _ = peer.chunk("t-cancel", 0, 7, make_bytes(16384))
        self.assertEqual(ack_type, peer.MessageType.CHUNK_ACK)
        peer.cancel("t-cancel")
        self.assertTrue(self.lb.wait_recv("t-cancel"))
        peer.close()
        self.lb.settle()

        self.assertEqual(read_file(self.existing), b"KEEP-ME", "iptal sonrasi var olan dosya silindi")
        self.assertFalse(os.path.exists(self.existing + ".part"), ".part temizlenmeliydi")

    def test_connection_drop_keeps_existing_target_and_part(self) -> None:
        peer = self._open_peer()
        peer.file_info("t-drop", "data.bin", 100000)
        peer.chunk("t-drop", 0, 7, make_bytes(16384))
        peer.close()  # gonderici yarida kopar
        self.assertTrue(self.lb.wait_recv("t-drop"))
        self.lb.settle()

        self.assertEqual(read_file(self.existing), b"KEEP-ME", "eksik transfer var olan dosyayi sildi")
        self.assertTrue(os.path.exists(self.existing + ".part"), "devam icin .part korunmaliydi")
        self.assertEqual(self.lb.recv_transfer("t-drop").status.value, "failed")

    def test_disk_error_path_keeps_existing_target(self) -> None:
        # .part adinda bir DIZIN: yazici thread dosyayi acamaz -> istisna yolu
        os.makedirs(self.existing + ".part")
        peer = self._open_peer()
        peer.file_info("t-err", "data.bin", 100000)
        peer.chunk("t-err", 0, 7, make_bytes(16384))
        self.assertTrue(self.lb.wait_recv("t-err"))
        peer.close()
        self.lb.settle()

        self.assertEqual(read_file(self.existing), b"KEEP-ME", "hata yolu var olan dosyayi sildi")
        self.assertEqual(self.lb.recv_transfer("t-err").status.value, "failed")

    def test_default_overwrites_existing_file_with_same_name(self) -> None:
        payload = make_bytes(50000, seed=6)
        source = write_file(os.path.join(self.lb.source_dir, "data.bin"), payload)

        transfer = self.lb.send(source)
        self.assertTrue(self.lb.wait_send(transfer))
        self.assertTrue(self.lb.wait_recv(transfer.transfer_id))
        self.lb.settle()

        self.assertEqual(read_file(self.existing), payload, "varsayılan: üzerine yazılmalı")
        self.assertFalse(os.path.exists(os.path.join(self.lb.download_dir, "data (1).bin")))
        self.assertEqual(self.lb.recv_transfer(transfer.transfer_id).filepath, self.existing)

    def test_locked_existing_target_falls_back_to_unique_name(self) -> None:
        # Üzerine yazma açık ama hedef kilitli (ör. Excel'de açık): aktarım başarısız olmamalı, "ad (1)" olmalı
        self.lb.server.FINALIZE_ATTEMPTS = 2
        locked = os.path.normcase(os.path.abspath(self.existing))
        payload = make_bytes(50000, seed=7)
        source = write_file(os.path.join(self.lb.source_dir, "data.bin"), payload)

        with _replace_failing_for(lambda src, dst: dst == locked):
            transfer = self.lb.send(source)
            self.assertTrue(self.lb.wait_send(transfer))
            self.assertTrue(self.lb.wait_recv(transfer.transfer_id))
            self.lb.settle()

        self.assertEqual(transfer.status.value, "completed", "kilitli hedef yüzünden aktarım başarısız oldu")
        self.assertEqual(read_file(self.existing), b"KEEP-ME")
        renamed = os.path.join(self.lb.download_dir, "data (1).bin")
        self.assertEqual(read_file(renamed), payload)
        self.assertEqual(self.lb.recv_transfer(transfer.transfer_id).filepath, renamed)

    def test_failed_finalize_never_deletes_the_users_empty_target(self) -> None:
        # Taşıma her yerde başarısızsa yalnızca _claim_final_path'in rezerve ettiği boş dosya geri alınır
        self.lb.server.FINALIZE_ATTEMPTS = 1
        empty = write_file(os.path.join(self.lb.download_dir, "empty.txt"), b"")
        part = write_file(empty + ".part", b"new content")
        part_key = os.path.normcase(os.path.abspath(part))

        with _replace_failing_for(lambda src, dst: src == part_key):
            with self.assertRaises(Exception):
                self.lb.server._finalize_part(part, empty)

        self.assertTrue(os.path.exists(empty), "kullanıcının var olan (boş) dosyası silindi")
        self.assertFalse(os.path.exists(os.path.join(self.lb.download_dir, "empty (1).txt")),
                         "rezerve edilen boş dosya geri alınmadı")
        self.assertEqual(read_file(part), b"new content", ".part korunmalı")

    def test_successful_transfer_never_overwrites_existing(self) -> None:
        self.lb.server.config.set('transfer', 'overwrite_existing', False)
        self.addCleanup(self.lb.server.config.set, 'transfer', 'overwrite_existing', True)
        payload = make_bytes(50000, seed=5)
        source = write_file(os.path.join(self.lb.source_dir, "data.bin"), payload)

        first = self.lb.send(source)
        self.assertTrue(self.lb.wait_send(first))
        self.assertTrue(self.lb.wait_recv(first.transfer_id))
        self.lb.settle()
        self.assertEqual(first.status.value, "completed")

        self.assertEqual(read_file(self.existing), b"KEEP-ME", "var olan dosya ezildi")
        renamed = os.path.join(self.lb.download_dir, "data (1).bin")
        self.assertEqual(read_file(renamed), payload)
        self.assertEqual(self.lb.recv_transfer(first.transfer_id).filepath, renamed)

        second = self.lb.send(source)
        self.assertTrue(self.lb.wait_send(second))
        self.assertTrue(self.lb.wait_recv(second.transfer_id))
        self.lb.settle()
        self.assertEqual(read_file(os.path.join(self.lb.download_dir, "data (2).bin")), payload)
        self.assertEqual(read_file(renamed), payload)

    def test_path_traversal_is_still_blocked(self) -> None:
        peer = self._open_peer()
        payload = make_bytes(1000, seed=9)
        peer.file_info("t-trav", "..\\..\\evil1.txt", len(payload), relative_path="../../evil2.txt")
        peer.chunk("t-trav", 0, 1, payload)
        peer.complete("t-trav")
        self.assertTrue(self.lb.wait_recv("t-trav"))
        peer.close()
        self.lb.settle()

        outside = os.path.dirname(self.lb.download_dir)
        for name in ("evil1.txt", "evil2.txt"):
            self.assertFalse(os.path.exists(os.path.join(outside, name)), f"{name} indirme klasorunun disina yazildi")
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(outside), name)))
        self.assertIn("evil2.txt", self.lb.list_downloads())

    def test_absolute_relative_path_is_confined(self) -> None:
        peer = self._open_peer()
        payload = make_bytes(500, seed=3)
        peer.file_info("t-abs", "abs.txt", len(payload), relative_path="C:/Windows/Temp/abs_evil.txt")
        peer.chunk("t-abs", 0, 1, payload)
        peer.complete("t-abs")
        self.assertTrue(self.lb.wait_recv("t-abs"))
        peer.close()
        self.lb.settle()
        for rel in self.lb.list_downloads():
            full = os.path.abspath(os.path.join(self.lb.download_dir, rel))
            self.assertTrue(full.startswith(os.path.abspath(self.lb.download_dir)))
        self.assertFalse(os.path.exists("C:/Windows/Temp/abs_evil.txt"))


class AppCleanupTest(unittest.TestCase):
    """src.app.Application._cleanup_incomplete_file: alici iptal yolu yalnizca .part silmeli."""

    def test_cleanup_removes_only_part_file(self) -> None:
        import types
        from src.app import Application
        from src.models.transfer import Transfer, TransferDirection

        folder = support.fresh_dir("cleanup")
        final = write_file(os.path.join(folder, "keep.bin"), b"IMPORTANT")
        part = write_file(final + ".part", b"partial")
        meta = write_file(final + ".part.meta", b"{}")
        transfer = Transfer("tid", final, "keep.bin", 10, "127.0.0.1", "peer", TransferDirection.RECEIVE)

        class _Log:
            def info(self, *a, **k): pass
            def error(self, *a, **k): pass

        fake_self = types.SimpleNamespace(logger=_Log())
        Application._cleanup_incomplete_file(fake_self, transfer)

        self.assertEqual(read_file(final), b"IMPORTANT", "iptal temizligi saglam hedef dosyayi sildi")
        self.assertFalse(os.path.exists(part))
        self.assertFalse(os.path.exists(meta))


class AppCompletionTest(unittest.TestCase):
    """src.app.Application._handle_transfer_complete_gui: alicida hata sonrasi devam ve ayni kimlikle yeniden deneme."""

    def setUp(self) -> None:
        from src.app import Application

        support.qt_app()
        self.App = Application
        fake = types.SimpleNamespace(
            _handled_completion_ids=set(),
            _pending_update=None,
            logger=mock.Mock(),
            config=mock.Mock(get=lambda section, key, default=None: default),
            window=mock.Mock(),
            database=mock.Mock(),
            tray_icon=mock.Mock(),
            transfer_manager=mock.Mock(
                get_active_transfers=mock.Mock(return_value=[]),
                get_statistics=mock.Mock(return_value={"total_sent": 0, "total_received": 0}),
            ),
            _find_folder_transfer_info=mock.Mock(return_value=(False, None, None)),
        )
        fake._cleanup_incomplete_file = lambda transfer: Application._cleanup_incomplete_file(fake, transfer)
        self.fake = fake
        for patcher in (mock.patch("src.app.get_active_language", return_value="tr"), mock.patch("src.app.SystemToast")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.folder = support.fresh_dir("complete")

    def _transfer(self, transfer_id: str, name: str = "big.bin"):
        from src.models.transfer import Transfer, TransferDirection
        return Transfer(transfer_id, os.path.join(self.folder, name), name, 100, "127.0.0.1", "peer",
                        TransferDirection.RECEIVE)

    def test_failed_receive_keeps_part_for_resume_cancel_removes_it(self) -> None:
        failed = self._transfer("t-fail")
        part = write_file(failed.filepath + ".part", b"partial")
        meta = write_file(part + ".meta", b"{}")
        failed.fail("Ağ bağlantısı koptu.")
        self.App._handle_transfer_complete_gui(self.fake, failed)
        self.assertTrue(os.path.exists(part), "hata sonrasi .part silindi: devam (resume) imkansiz")
        self.assertTrue(os.path.exists(meta))

        cancelled = self._transfer("t-cancel")
        cancelled.cancel()
        self.App._handle_transfer_complete_gui(self.fake, cancelled)
        self.assertFalse(os.path.exists(part), "iptalde .part temizlenmeli")
        self.assertFalse(os.path.exists(meta))
        self.fake.logger.exception.assert_not_called()

    def test_successful_retry_with_same_transfer_id_is_recorded(self) -> None:
        first = self._transfer("t-retry")
        self.App._handle_file_received_gui(self.fake, first)
        first.fail("Ağ bağlantısı koptu.")
        self.App._handle_transfer_complete_gui(self.fake, first)

        second = self._transfer("t-retry")  # gonderici ayni kimlikle yeniden denedi
        self.App._handle_file_received_gui(self.fake, second)
        second.complete()
        self.App._handle_transfer_complete_gui(self.fake, second)
        self.App._handle_transfer_complete_gui(self.fake, second)  # yinelenen sinyal yine yok sayilmali

        recorded = [call.args[0] for call in self.fake.database.update_transfer.call_args_list]
        self.assertEqual(recorded, [first, second], "basarili yeniden deneme gecmise/arayuze islenmedi")
        self.fake.logger.exception.assert_not_called()


if __name__ == "__main__":
    unittest.main()
