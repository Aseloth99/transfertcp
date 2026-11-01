"""Alıcı diske yazma tamponu BAYT olarak sınırlıdır (4 MB'lık parçalarla 48 parça = 192 MB bellek olmasın)."""

import os
import queue
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402,F401  (ilk import: sandbox)
from support import Loopback, make_bytes, read_file, write_file  # noqa: E402

from src.core import server as server_module  # noqa: E402
from src.core.server import _ByteBoundedQueue  # noqa: E402


class ByteBoundedQueueTest(unittest.TestCase):
    def test_blocks_by_bytes_not_by_item_count(self) -> None:
        q = _ByteBoundedQueue(maxsize=20)
        q.put(b"a" * 10)
        q.put(b"b" * 10)
        with self.assertRaises(queue.Full):
            q.put(b"c", timeout=0.05)  # 20 bayt doldu; tek baytlık parça bile sığmaz
        self.assertEqual(q.get(), b"a" * 10)
        q.put(b"c", timeout=0.5)  # yer açılınca girer

    def test_one_big_chunk_always_fits_into_an_empty_queue(self) -> None:
        q = _ByteBoundedQueue(maxsize=10)
        q.put(b"x" * 100, timeout=0.5)  # sınırı aşan tek parça kuyruk boşken kilitlenmemeli
        with self.assertRaises(queue.Full):
            q.put(b"y", timeout=0.05)
        self.assertEqual(len(q.get()), 100)
        self.assertTrue(q.empty())

    def test_sentinel_none_and_empty_semantics(self) -> None:
        q = _ByteBoundedQueue(maxsize=8)
        q.put(None)
        self.assertIsNone(q.get())
        self.assertTrue(q.empty())

    def test_producer_resumes_when_consumer_drains(self) -> None:
        q = _ByteBoundedQueue(maxsize=16)
        received = []

        def consumer():
            for _ in range(10):
                received.append(q.get(timeout=2))
                time.sleep(0.01)

        thread = threading.Thread(target=consumer)
        thread.start()
        for i in range(10):
            q.put(bytes([i]) * 8, timeout=2)
        thread.join(timeout=5)
        self.assertEqual([item[0] for item in received], list(range(10)), "sıra ve içerik korunmalı")

    def test_default_limit_is_a_few_tens_of_megabytes(self) -> None:
        self.assertLessEqual(server_module.WRITE_BUFFER_BYTES, 64 * 1024 * 1024)
        self.assertGreaterEqual(server_module.WRITE_BUFFER_BYTES, 8 * 1024 * 1024)


class TransferWithTinyBufferTest(unittest.TestCase):
    def test_file_arrives_intact_even_when_the_buffer_is_smaller_than_the_file(self) -> None:
        lb = Loopback(chunk_size=262144).start()
        self.addCleanup(lb.stop)
        payload = make_bytes(6 * 1024 * 1024 + 123, seed=11)
        source = write_file(os.path.join(lb.source_dir, "buyuk.bin"), payload)
        with mock.patch.object(server_module, "WRITE_BUFFER_BYTES", 512 * 1024):
            transfer = lb.send(source)
            self.assertTrue(lb.wait_send(transfer))
            self.assertTrue(lb.wait_recv(transfer.transfer_id))
            lb.settle()
        self.assertEqual(transfer.status.value, "completed")
        self.assertEqual(read_file(os.path.join(lb.download_dir, "buyuk.bin")), payload)


if __name__ == "__main__":
    unittest.main()
