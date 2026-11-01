"""TCP Client for sending files"""

import hashlib
import socket
import os
import stat
import time
import threading
import struct
import queue
from typing import Optional, Callable
from collections import deque


from .crypto import (
    evaluate_peer,
    get_local_fingerprint,
    is_encryption_enabled,
    trust_device,
    wrap_client_socket,
)
from .netio import (
    CONNECT_TIMEOUT,
    HANDSHAKE_TIMEOUT,
    TLS_CHUNK,
    TRANSFER_TIMEOUT,
    tls_chunk_for,
    configure_socket,
    recv_exact,
    send_all,
    socket_has_data,
)
from .protocol import Protocol, MessageType
from .transfer import TransferManager
from ..models.transfer import Transfer, TransferStatus
from ..utils.logger import get_logger
from ..utils import oserr
from ..utils.config import get_config
from ..utils.fileio import hash_file_prefix
from ..utils.oserr import classify_os_error
from ..utils.ports import DEFAULT_TRANSFER_PORT
from ..utils.helpers import get_hostname


class ReceiverReportedError(Exception):
    """Alıcı cihaz açıkça hata bildirdi (TRANSFER_ERROR, FILE_INFO_REJECT, ACK success=False).

    Kalıcı hatadır: yeniden denenmez; mesaj alıcının kullanıcıya dönük metnidir.
    """

    def __init__(self, message: str):
        self.reported_message = (message or "").strip() or "Alıcı cihaz dosyayı kaydedemedi"
        super().__init__(self.reported_message)


class CompletionNotConfirmed(Exception):
    """Alıcıdan TRANSFER_COMPLETE_ACK alınamadı (zaman aşımı/bağlantı koptu): başarı SAYILMAZ.

    Dosya karşıya ulaşmış olabilir; kopya oluşmaması için otomatik yeniden denenmez.
    """


class _ChunkReader(threading.Thread):
    """Dosyayı sırayla parçalara okuyup (ve akış SHA-256'sına katıp) en fazla 2 parçayı önden hazır tutar.

    Ağ gönderimi ve alıcı onayı beklenirken disk okuması + özet hesabı paralel yürür; parçalar sırayla
    üretildiği için özet, gönderim sırasıyla aynıdır. `get()` dosya sonunda b"" döndürür; okuma hatasında
    önceki parçalar teslim edildikten sonra özgün hatayı fırlatır (errno'ya göre sınıflandırılsın diye).
    """

    def __init__(self, handle, remaining: int, piece_size: int, hasher):
        super().__init__(daemon=True, name="chunk-reader")
        self._fh = handle
        self._remaining = max(0, remaining)
        self._piece = max(1, piece_size)
        self._hasher = hasher
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=2)
        self._stop_event = threading.Event()
        self._error: Optional[BaseException] = None

    def run(self) -> None:
        try:
            while self._remaining > 0 and not self._stop_event.is_set():
                chunk = self._fh.read(min(self._piece, self._remaining))
                if not chunk:
                    break
                self._remaining -= len(chunk)
                if self._hasher is not None:
                    self._hasher.update(chunk)
                while not self._stop_event.is_set():
                    try:
                        self._queue.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:  # okuma hatası (USB çıkarıldı, paylaşım koptu...): get() bunu yeniden fırlatır
            self._error = exc
        finally:
            while not self._stop_event.is_set():
                try:
                    self._queue.put(b"", timeout=0.2)
                    break
                except queue.Full:
                    continue

    def get(self) -> bytes:
        while True:
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                if not self.is_alive() and self._queue.empty():
                    chunk = b""
                else:
                    continue
            if not chunk and self._error is not None:
                raise self._error
            return chunk

    def stop(self) -> None:
        self._stop_event.set()


class SendAttemptDiag:
    """Tek bir gönderim denemesinin tanı bilgisi (kopma anında günlüğe yazılır).

    Kopmaların nedenini sonradan çözebilmek için: deneme ne kadar sürdü, hangi aşamadaydı,
    kaçıncı parçada/kaç bayttaydı ve alıcıdan gelen son ACK'in gecikmesi/yaşı nedir.
    (Gerçek kopmaların karşı uygulamanın yeniden başlatılmasıyla aynı saniyede toplandığı
    günlükten görülmüştü; bu satırlar o ayrımı kolaylaştırır.)
    """

    def __init__(self):
        self.started = time.monotonic()
        self.stage = "connect"
        self.chunk_index = 0          # sıradaki (henüz ACK'lenmemiş) parça no (0 tabanlı)
        self.total_chunks = 0
        self.bytes_sent = 0
        self.last_ack_latency: Optional[float] = None  # parça gönderiminden ACK'e geçen süre (sn)
        self.last_ack_at: Optional[float] = None       # son ACK'in monotonic zamanı

    def describe(self, filesize: int = 0) -> str:
        now = time.monotonic()
        parts = [
            f"süre={now - self.started:.1f}s",
            f"aşama={self.stage}",
            f"parça={self.chunk_index}/{self.total_chunks}",
            f"gönderilen={self.bytes_sent}" + (f"/{filesize}" if filesize else "") + " B",
        ]
        if self.last_ack_latency is None:
            parts.append("son ACK gecikmesi=yok")
        else:
            parts.append(f"son ACK gecikmesi={self.last_ack_latency * 1000:.0f}ms")
        if self.last_ack_at is not None:
            parts.append(f"son ACK={now - self.last_ack_at:.1f}s önce")
        return ", ".join(parts)


class TCPClient:
    """TCP client for sending file transfers"""

    def __init__(self, transfer_manager: TransferManager):
        """
        Initialize TCP client
        
        Args:
            transfer_manager: Transfer manager instance
        """
        self.transfer_manager = transfer_manager
        self.config = get_config()
        self.logger = get_logger()
        
        self.chunk_size = self.config.get('transfer', 'chunk_size', 262144)
        self._retry_delays = (1, 5, 10, 30)
        
        # Concurrency semaphore: prevent simultaneous sends from choking router/switch
        max_concurrent = max(1, int(self.config.get('transfer', 'max_concurrent_transfers', 2)))
        self._max_concurrent = max_concurrent
        self._send_semaphore = threading.Semaphore(max_concurrent)
        
        # Track active sends to prevent duplicates
        self._active_sends = set()
        
        # Callbacks
        self.on_transfer_started: Optional[Callable] = None
        self.on_transfer_complete: Optional[Callable] = None

    
    def send_file(self, transfer: Transfer) -> bool:
        """
        Send a file to remote device
        
        Args:
            transfer: Transfer object
            
        Returns:
            True if successful, False otherwise
        """
        # Check if already being sent
        if transfer.transfer_id in self._active_sends:
            self.logger.warning(f"Transfer already in progress: {transfer.filename}")
            return False
        
        # Mark as active
        self._active_sends.add(transfer.transfer_id)
        
        # Start in separate thread
        thread = threading.Thread(
            target=self._send_file_thread,
            args=(transfer,),
            daemon=True
        )
        thread.start()
        return True
    
    def _is_retryable(self, error: Exception, transfer: Transfer) -> bool:
        if transfer.status == TransferStatus.CANCELLED:
            return False
        if isinstance(error, (NameError, TypeError, AttributeError)):
            return False
        # Alıcının bildirdiği hata veya onaysız tamamlanma kalıcıdır (aynı sonucu tekrar alırız)
        if isinstance(error, (ReceiverReportedError, CompletionNotConfirmed)):
            return False
        message = str(error)
        fatal = (
            "Transfer reddedildi",
            "Transfer rejected",
            "Cihaz kimliği değişti",
            "Yol bir dosya değil",
            "Dosya bulunamadı",
            "Path is not a file",
            "File not found",
        )
        return not any(token in message for token in fatal)

    def _wait_retry(self, transfer: Transfer, delay: float) -> bool:
        deadline = time.time() + delay
        while time.time() < deadline:
            if transfer.status == TransferStatus.CANCELLED:
                return False
            time.sleep(0.2)
        return transfer.status != TransferStatus.CANCELLED

    def _user_error(self, error: Exception) -> str:
        error_msg = str(error)
        if isinstance(error, ReceiverReportedError):
            return f"Alıcı cihaz hatası: {error.reported_message}"
        if isinstance(error, CompletionNotConfirmed):
            return ("Alıcıdan tamamlanma onayı alınamadı. Dosya karşıya ulaşmış olabilir; "
                    "lütfen alıcı cihazı kontrol edin.")
        if "unsupported_version" in error_msg:
            return "Alıcı cihaz uyumsuz bir TransferTCP sürümü kullanıyor. İki cihazda da güncel sürüm olmalı."
        if "Parça onayı alınamadı" in error_msg or "No chunk ack received" in error_msg:
            return "Bağlantı kesildi. Alıcı cihaz yanıt vermiyor."
        # Gerçek errno/winerror/istisna türüne göre (socket.timeout mesajı yalnızca "timed out" der)
        category = classify_os_error(error)
        if category == oserr.TIMEOUT:
            return "Zaman aşımı. Alıcı cihaz çok yavaş yanıt veriyor veya ağ bağlantısı kesildi."
        if category == oserr.REFUSED:
            return "Alıcı cihaza bağlanılamadı: TransferTCP orada çalışmıyor veya bağlantı noktası kapalı."
        if category == oserr.UNREACHABLE:
            return "Alıcı cihaza ulaşılamıyor. Aynı ağda olduğunuzdan emin olun."
        if category == oserr.CONN_RESET:
            return "Alıcı cihaz bağlantıyı kapattı."
        if category == oserr.ACCESS_DENIED:
            return "Dosyaya erişim engellendi (okuma izni yok veya başka bir program kilitledi)."
        if "zaman aşımı" in error_msg.lower() or "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            return "Zaman aşımı. Alıcı cihaz çok yavaş yanıt veriyor."
        if "Ağ bağlantısı koptu" in error_msg or "Connection may be broken" in error_msg:
            return "Ağ bağlantısı koptu."
        if "Dosya bilgisi yanıtı alınamadı" in error_msg or "No file info response" in error_msg:
            return "Alıcı cihaz dosya bilgisini onaylamadı."
        if "WinError 10054" in error_msg or "forcibly closed" in error_msg or "bağlantıyı kapattı" in error_msg:
            return "Alıcı cihaz bağlantıyı kapattı."
        if "Yol bir dosya değil" in error_msg or "Path is not a file" in error_msg:
            return "Seçilen yol bir dosya değil. Lütfen bir dosya seçin."
        if "Dosya bulunamadı" in error_msg or "File not found" in error_msg:
            return "Dosya bulunamadı. Dosya silinmiş veya taşınmış olabilir."
        if "Transfer reddedildi" in error_msg or "Transfer rejected" in error_msg:
            return "Transfer alıcı cihaz tarafından reddedildi."
        if "Cihaz kimliği değişti" in error_msg:
            return "Alıcı cihazın kimliği değişti. Güvenilen cihazları temizleyip tekrar deneyin."
        import ssl
        if isinstance(error, ssl.SSLError) or "tls 1.3" in error_msg.lower() or "ssl" in error_msg.lower():
            return "Şifreli oturum kurulamadı. Her iki tarafta da TransferTCP güncel olmalı."
        if "El sıkışma" in error_msg or "handshake" in error_msg.lower():
            return "Bağlantı kurulamadı. Alıcı cihazla iletişim sağlanamadı."
        # Eskiden 50 karakterde kesiliyordu; arayüzde taşmayacak makul bir üst sınır
        return f"Transfer başarısız: {error_msg if len(error_msg) <= 200 else error_msg[:199] + '…'}"

    def _fail_send(self, transfer: Transfer, error: Exception) -> None:
        self.logger.exception(f"Error sending file {transfer.filename}: {error}")
        self.logger.error(
            f"Transfer details: filepath={transfer.filepath}, filesize={transfer.filesize}, "
            f"relative_path={getattr(transfer, 'relative_path', None)}"
        )
        self.logger.error(f"{transfer.filename}: son deneme tanısı: {self._diag_text(transfer)}")
        if transfer.status == TransferStatus.CANCELLED:
            return
        self.transfer_manager.complete_transfer(
            transfer.transfer_id,
            success=False,
            error_message=self._user_error(error),
        )

    def _diag_text(self, transfer: Transfer) -> str:
        """Son gönderim denemesinin tanı satırı (deneme hiç başlamadıysa kısa bir not)."""
        diag = getattr(transfer, "_attempt_diag", None)
        if diag is None:
            return "deneme başlamadı"
        return diag.describe(getattr(transfer, "filesize", 0) or 0)

    def _acquire_send_slot(self, transfer: Transfer) -> bool:
        """Gönderici yuvasını (aynı anda en fazla N gönderim) alır.

        Yuva doluysa transfer açıkça "sırada" işaretlenir (arayüzde 0 B'de sessiz "Bekliyor..."
        yerine "Sırada (aynı anda en fazla N)" görünür). Beklerken iptal edilirse False döner.
        """
        if self._send_semaphore.acquire(blocking=False):
            return True
        transfer.queue_limit = self._max_concurrent
        transfer.queued_for_slot = True
        queued_at = time.monotonic()
        self.logger.info(
            f"{transfer.filename}: sırada (aynı anda en fazla {self._max_concurrent} gönderim); "
            f"yuva bekleniyor"
        )
        try:
            while True:
                if transfer.status == TransferStatus.CANCELLED:
                    return False
                if self._send_semaphore.acquire(timeout=0.2):
                    break
        finally:
            transfer.queued_for_slot = False
        self.logger.info(
            f"{transfer.filename}: sıradan çıktı ({time.monotonic() - queued_at:.1f}s bekledi)"
        )
        return True

    def _send_file_thread(self, transfer: Transfer):
        """Send file in separate thread, retrying on dropped connections."""
        if not self._acquire_send_slot(transfer):
            self._active_sends.discard(transfer.transfer_id)
            return
        try:
            delays = (0,) + self._retry_delays
            try:
                self.logger.info(
                    f"Starting transfer thread for: {transfer.filename} "
                    f"(path: {transfer.filepath}, size: {transfer.filesize}, "
                    f"relative_path={getattr(transfer, 'relative_path', None)})"
                )
                for attempt, delay in enumerate(delays):
                    if transfer.status == TransferStatus.CANCELLED:
                        return
                    transfer.retry_attempt = attempt
                    if delay:
                        transfer.status = TransferStatus.CONNECTING
                        self.logger.warning(
                            f"{transfer.filename}: bağlantı koptu, {delay}s sonra deneme "
                            f"{attempt}/{len(self._retry_delays)}"
                        )
                        if not self._wait_retry(transfer, delay):
                            return
                    try:
                        self._send_file_once(transfer)
                        return
                    except Exception as error:
                        if transfer.status == TransferStatus.CANCELLED:
                            return
                        if not self._is_retryable(error, transfer) or attempt >= len(delays) - 1:
                            self._fail_send(transfer, error)
                            return
                        self.logger.warning(
                            f"{transfer.filename}: deneme {attempt + 1}/{len(delays)} başarısız "
                            f"({error}); {self._diag_text(transfer)}; yeniden denenecek"
                        )
            finally:
                self._active_sends.discard(transfer.transfer_id)
        finally:
            self._send_semaphore.release()


    def _send_file_once(self, transfer: Transfer):
        """Single send attempt. Raises on retryable/fatal errors."""
        diag = SendAttemptDiag()
        transfer._attempt_diag = diag  # kopmada günlüğe yazılacak tanı (bkz. _diag_text)
        sock = None
        reader: Optional[_ChunkReader] = None
        try:
            transfer.status = TransferStatus.CONNECTING
            transfer.bytes_transferred = 0
            transfer.speed = 0.0

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)  # Hızlı LAN bağlantı zaman aşımı: 21 sn Windows takılmasını önler

            target_port = getattr(transfer, "device_port", None) or self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)
            self.logger.info(f"Connecting to {transfer.device_ip}:{target_port}")

            sock.connect((transfer.device_ip, target_port))
            configure_socket(sock, HANDSHAKE_TIMEOUT)
            diag.stage = "handshake"

            # Send handshake with encryption capabilities (STARTTLS negotiation)
            device_name = self.config.get('general', 'device_name', get_hostname())
            hostname = get_hostname()
            supports_enc = is_encryption_enabled()
            local_fp = get_local_fingerprint()
            
            handshake = Protocol.create_handshake(
                device_name,
                hostname,
                fingerprint=local_fp,
                supports_encryption=supports_enc,
                proto=Protocol.PROTO_VERSION,
                features=Protocol.LOCAL_FEATURES,
            )
            self._send_message(sock, handshake)

            # Wait for handshake ack
            response = self._receive_message(sock)
            if not response:
                raise Exception("El sıkışma yanıtı alınamadı")

            msg_type, data = Protocol.parse_message(response)
            if msg_type == MessageType.HANDSHAKE_REJECT:
                raise Exception(f"Transfer reddedildi: {data.get('reason', 'Bilinmeyen')}")
            if msg_type != MessageType.HANDSHAKE_ACK:
                raise Exception("Geçersiz el sıkışma yanıtı")
            if not Protocol.is_compatible_version(response):
                raise Exception("Transfer reddedildi: unsupported_version")

            # Karşı taraf proto/features ilan etmiyorsa (eski sürüm) boş küme: eski davranış
            features = Protocol.negotiate_features(data)
            self.logger.info(f"Peer proto={data.get('proto', 1)}, features={sorted(features)}")

            remote_supports_enc = bool(data.get('supports_encryption', False))
            use_tls = supports_enc and remote_supports_enc
            diag.stage = "tls" if use_tls else "plain"
            if use_tls:
                sock = wrap_client_socket(sock)
                configure_socket(sock, TRANSFER_TIMEOUT)
                self.logger.info("TLS 1.3 session established")
            else:
                configure_socket(sock, TRANSFER_TIMEOUT)
                self.logger.info("Transferring over plain TCP (remote device does not support TLS or encryption disabled)")

            peer_fp = data.get('fingerprint')
            if peer_fp:
                status, _previous = evaluate_peer(peer_fp, transfer.device_ip)
                if status == "mismatch":
                    raise Exception(
                        "Cihaz kimliği değişti. Bu bir güvenlik uyarısı olabilir; "
                        "alıcı TransferTCP'yi yeniden kurduysa Ayarlar'dan güvenilen cihazları temizleyin."
                    )
                trust_device(peer_fp, transfer.device_name or transfer.device_ip, transfer.device_ip)
            
            self.logger.info("Handshake successful")
            transfer.status = TransferStatus.CONNECTING
            transfer.checksum = ""

            use_sha = Protocol.FEATURE_SHA256 in features
            use_meta = Protocol.FEATURE_RESUME_META in features

            # Kaynağı duyurmadan önce doğrula; boyut/değişiklik zamanı resume doğrulamasına gider
            try:
                source_stat = os.stat(transfer.filepath)
            except OSError:
                raise Exception(f"Dosya bulunamadı: {transfer.filepath}")
            if not stat.S_ISREG(source_stat.st_mode):
                raise Exception(f"Yol bir dosya değil: {transfer.filepath}")
            if source_stat.st_size != transfer.filesize:
                # Kuyruğa alındıktan sonra dosya değişmiş: başlıkta GERÇEK boyut bildirilmeli
                self.logger.warning(
                    f"{transfer.filename}: boyut değişti ({transfer.filesize} → {source_stat.st_size}), güncelleniyor"
                )
                transfer.filesize = source_stat.st_size

            # Send file info with relative path and folder metadata if available
            file_info = Protocol.create_file_info(
                transfer.transfer_id,
                transfer.filename,
                transfer.filesize,
                "",
                is_folder=False,
                relative_path=getattr(transfer, 'relative_path', None),
                folder_name=getattr(transfer, 'folder_name', None),
                folder_total=getattr(transfer, 'folder_total', None),
                folder_id=getattr(transfer, 'folder_id', None),
                mtime_ns=source_stat.st_mtime_ns if use_meta else None,
            )
            diag.stage = "file_info"
            self._send_message(sock, file_info)
            
            # Wait for file info ack (with better error handling)
            self.logger.info("Waiting for file info acknowledgment...")
            response = self._receive_message(sock)
            if not response:
                raise Exception("Dosya bilgisi yanıtı alınamadı (zaman aşımı veya bağlantı kapandı)")
            
            msg_type, data = Protocol.parse_message(response)
            if msg_type in (MessageType.FILE_INFO_REJECT, MessageType.TRANSFER_ERROR):
                # Alıcının gerekçesi (ör. disk dolu) gönderici arayüzünde gösterilir
                raise ReceiverReportedError(data.get('reason') or data.get('error') or "Transfer reddedildi")
            elif msg_type != MessageType.FILE_INFO_ACK:
                raise Exception("Geçersiz dosya bilgisi yanıtı")
            
            resumed_chunk = data.get('resumed_from_chunk', 0)
            resumed_bytes = data.get('resumed_bytes', 0)
            valid_resume = (
                isinstance(resumed_bytes, int) and not isinstance(resumed_bytes, bool)
                and isinstance(resumed_chunk, int) and not isinstance(resumed_chunk, bool)
                and 0 <= resumed_bytes <= transfer.filesize and resumed_chunk >= 0
            )
            if not valid_resume:
                self.logger.warning(
                    f"Alıcının devam bilgisi geçersiz ({resumed_chunk}/{resumed_bytes}); baştan gönderiliyor"
                )
                resumed_chunk, resumed_bytes = 0, 0

            self.logger.info("Starting file transfer...")
            transfer.start()
            
            if self.on_transfer_started:
                self.on_transfer_started(transfer)
            
            # Send file data in chunks
            piece_size = tls_chunk_for(transfer.device_ip) if use_tls else self.chunk_size
            total_chunks = (transfer.filesize + piece_size - 1) // piece_size if piece_size else 1
            
            bytes_sent = resumed_bytes
            chunk_index = resumed_chunk
            diag.stage = "chunks"
            diag.total_chunks = total_chunks
            diag.chunk_index = chunk_index
            diag.bytes_sent = bytes_sent
            if bytes_sent > 0:
                transfer.bytes_transferred = bytes_sent
                self.logger.info(
                    f"Resuming {transfer.filename} from chunk {chunk_index}/{total_chunks} "
                    f"({bytes_sent}/{transfer.filesize} bytes)"
                )
            
            start_time = time.time()
            last_update_time = start_time
            
            # Speed calculation tracking - store last N measurements
            speed_samples = deque()  # deque of (time, bytes) tuples
            speed_window = 2.5  # Calculate speed over last 2.5 seconds for smooth readout
            
            # Verify file exists and is readable
            if not os.path.exists(transfer.filepath):
                raise Exception(f"Dosya bulunamadı: {transfer.filepath}")
            
            if not os.path.isfile(transfer.filepath):
                raise Exception(f"Yol bir dosya değil: {transfer.filepath}")
            
            # Akış SHA-256: okunan her parça özete girer; devam edilen önek önceden okunup özete katılır
            hasher = hashlib.sha256() if use_sha else None
            if hasher is not None and bytes_sent > 0:
                hash_file_prefix(
                    hasher, transfer.filepath, bytes_sent,
                    should_stop=lambda: transfer.status == TransferStatus.CANCELLED,
                )

            with open(transfer.filepath, 'rb', buffering=2 * 1024 * 1024) as f:
                if bytes_sent > 0:
                    f.seek(bytes_sent)
                # Sonraki parça, önceki parçanın ağ gönderimi/onayı beklenirken okunup özetlenir
                reader = _ChunkReader(f, transfer.filesize - bytes_sent, piece_size, hasher)
                reader.start()
                sender_paused_notified = False
                paused_by_remote = False
                while bytes_sent < transfer.filesize:

                    # Check if paused or cancelled
                    if transfer.status == TransferStatus.PAUSED:
                        if not paused_by_remote and not sender_paused_notified:
                            try:
                                pause_msg = Protocol.create_message(MessageType.PAUSE, {'transfer_id': transfer.transfer_id})
                                self._send_message(sock, pause_msg)
                                sender_paused_notified = True
                                self.logger.info("Transfer paused (notified remote peer)")
                            except Exception as pe:
                                self.logger.debug(f"Failed to send pause notice: {pe}")
                        time.sleep(0.2)
                        continue
                    elif sender_paused_notified:
                        try:
                            resume_msg = Protocol.create_message(MessageType.RESUME, {'transfer_id': transfer.transfer_id})
                            self._send_message(sock, resume_msg)
                            sender_paused_notified = False
                            self.logger.info("Transfer resumed (notified remote peer)")
                        except Exception as re:
                            self.logger.debug(f"Failed to send resume notice: {re}")
                    
                    if transfer.status == TransferStatus.CANCELLED:
                        self.logger.info("Transfer cancelled (local)")
                        try:
                            cancel_msg = Protocol.create_cancel(transfer.transfer_id)
                            self._send_message(sock, cancel_msg)
                            self.logger.info("Sent cancel notice to receiver")
                        except Exception as ce:
                            self.logger.debug(f"Failed to send cancel notice: {ce}")
                        break
                    
                    # Read chunk (bildirilen boyutu aşma: dosya gönderim sırasında büyümüş olabilir)
                    chunk = reader.get()
                    if not chunk:
                        # End of file reached
                        if bytes_sent < transfer.filesize:
                            self.logger.error(f"Unexpected end of file: {bytes_sent}/{transfer.filesize} bytes read")
                        break

                    # Send chunk header
                    chunk_header = Protocol.create_chunk_data(
                        transfer.transfer_id,
                        chunk_index,
                        total_chunks
                    )
                    chunk_sent_at = time.monotonic()
                    try:
                        self._send_message(sock, chunk_header)

                        # Send chunk size (4 bytes) and chunk data together
                        chunk_size_data = struct.pack('!I', len(chunk))
                        send_all(sock, chunk_size_data + chunk)
                    except OSError as send_error:
                        if transfer.status == TransferStatus.CANCELLED:
                            raise
                        # Alıcı hata yüzünden bağlantıyı kapatmış olabilir; bıraktığı
                        # TRANSFER_ERROR varsa gerçek nedeni kullanıcıya göster.
                        reported = self._pending_receiver_error(sock)
                        if reported:
                            raise ReceiverReportedError(reported) from send_error
                        raise

                    # Wait for chunk ack (with better error handling)
                    try:
                        response = self._receive_message(sock)
                        if not response:
                            if transfer.status == TransferStatus.CANCELLED:
                                break
                            self.logger.error(f"No ACK for chunk {chunk_index + 1}/{total_chunks} - Connection may be broken")
                            raise Exception(f"Parça onayı alınamadı (parça {chunk_index + 1}/{total_chunks})")
                        
                        msg_type, ack_data = Protocol.parse_message(response)
                        if msg_type == MessageType.CANCEL:
                            self.logger.info(f"Transfer cancelled by remote receiver: {transfer.filename}")
                            transfer.cancel()
                            self.transfer_manager.complete_transfer(
                                transfer.transfer_id,
                                success=False,
                                error_message="Transfer alıcı tarafından iptal edildi"
                            )
                            return
                        if msg_type == MessageType.TRANSFER_ERROR:
                            # Alıcı hatası kalıcıdır: "geçersiz yanıt" diye yeniden denenmez
                            self.logger.error(f"Receiver reported error: {ack_data.get('error')}")
                            raise ReceiverReportedError(ack_data.get('error'))
                        if msg_type != MessageType.CHUNK_ACK:
                            self.logger.error(f"Expected CHUNK_ACK, got {msg_type}")
                            raise Exception(f"Geçersiz yanıt türü: {msg_type}")
                            
                    except socket.timeout:
                        if transfer.status == TransferStatus.CANCELLED:
                            break
                        self.logger.error(f"Timeout waiting for ACK {chunk_index + 1}/{total_chunks}")
                        raise Exception(f"Parça onayı için zaman aşımı (parça {chunk_index + 1}/{total_chunks})")
                    except Exception as e:
                        if transfer.status == TransferStatus.CANCELLED:
                            break
                        raise
                    
                    bytes_sent += len(chunk)
                    chunk_index += 1
                    ack_at = time.monotonic()
                    diag.last_ack_latency = ack_at - chunk_sent_at
                    diag.last_ack_at = ack_at
                    diag.bytes_sent = bytes_sent
                    diag.chunk_index = chunk_index

                    # If receiver requested pause, pause cleanly after this chunk
                    if ack_data.get('pause_requested'):
                        self.logger.info("Remote receiver requested pause (clean chunk boundary)")
                        paused_by_remote = True
                        transfer.pause()
                        # Wait for remote resume
                        while transfer.status == TransferStatus.PAUSED:
                            if socket_has_data(sock, timeout=0.2):
                                try:
                                    r = self._receive_message(sock)
                                    if r:
                                        rmt, _ = Protocol.parse_message(r)
                                        if rmt == MessageType.RESUME:
                                            paused_by_remote = False
                                            transfer.resume()
                                            self.logger.info("Remote receiver resumed transfer")
                                            break
                                        elif rmt == MessageType.CANCEL:
                                            transfer.cancel()
                                            break
                                except Exception:
                                    pass
                            time.sleep(0.05)
                    
                    # Calculate speed using O(1) sliding window (last 1.5 seconds)
                    current_time = time.time()
                    speed_samples.append((current_time, bytes_sent))
                    cutoff = current_time - speed_window
                    while speed_samples and speed_samples[0][0] < cutoff:
                        speed_samples.popleft()
                    
                    if len(speed_samples) >= 2:
                        oldest_time, oldest_bytes = speed_samples[0]
                        newest_time, newest_bytes = speed_samples[-1]
                        time_diff = newest_time - oldest_time
                        bytes_diff = newest_bytes - oldest_bytes
                        speed = bytes_diff / time_diff if time_diff > 0 else 0
                    else:
                        elapsed = current_time - start_time
                        speed = bytes_sent / elapsed if elapsed > 0 else 0

                    
                    # Update progress (throttle updates to every 100ms for UI performance)
                    transfer.bytes_transferred = bytes_sent
                    if current_time - last_update_time >= 0.1 or bytes_sent >= transfer.filesize:
                        self.transfer_manager.update_progress(transfer.transfer_id, bytes_sent, speed)
                        last_update_time = current_time
                    
                    # Apply speed limit if set. Süre her parçada yeniden ölçülür ve yalnızca bu denemede
                    # gönderilen bayt sayılır (devam edilen önek değil); eskiden ilk parçanın süresi kalıyordu,
                    # bekleme her parçada büyüyüp alıcıyı zaman aşımına düşürüyordu.
                    speed_limit = self.config.get('transfer', 'speed_limit', 0)
                    if speed_limit > 0 and speed > speed_limit:
                        elapsed = current_time - start_time
                        sleep_time = ((bytes_sent - resumed_bytes) / speed_limit) - elapsed
                        if sleep_time > 0:
                            time.sleep(sleep_time)
            
            # Check if complete
            if bytes_sent >= transfer.filesize and transfer.status != TransferStatus.CANCELLED:
                # Alıcıya transferin bittiğini bildir ve alıcının diske yazma/tamamlama onayını bekle.
                # Yeni sürüm alıcıda (complete_ack) onay ZORUNLU: yoksa başarı sayılmaz.
                strict = Protocol.FEATURE_COMPLETE_ACK in features
                diag.stage = "complete"
                if hasher is not None:
                    transfer.checksum = hasher.hexdigest()  # alıcı akış özetiyle karşılaştırır
                complete_msg = Protocol.create_transfer_complete(transfer.transfer_id, transfer.checksum or "")
                try:
                    self._send_message(sock, complete_msg)
                except OSError as send_error:
                    if not strict:
                        self.logger.debug(f"Transfer tamamlama mesajı gönderilemedi (eski alıcı): {send_error}")
                    else:
                        reported = self._pending_receiver_error(sock)
                        if reported:
                            raise ReceiverReportedError(reported) from send_error
                        raise CompletionNotConfirmed(str(send_error)) from send_error
                else:
                    self._await_completion(sock, transfer, strict)

                elapsed = time.time() - start_time
                final_speed = bytes_sent / elapsed if elapsed > 0 else 0
                transfer.bytes_transferred = bytes_sent
                transfer.speed = final_speed
                transfer.complete()
                self.transfer_manager.update_progress(transfer.transfer_id, bytes_sent, final_speed)
                self.transfer_manager.complete_transfer(transfer.transfer_id, success=True)
                self.logger.info(f"File sent successfully: {transfer.filename} ({bytes_sent}/{transfer.filesize} bytes)")
                if self.on_transfer_complete:
                    self.on_transfer_complete(transfer)

            elif transfer.status == TransferStatus.CANCELLED:
                self.logger.info(f"Transfer cancelled: {transfer.filename}")
                self.transfer_manager.complete_transfer(
                    transfer.transfer_id,
                    success=False,
                    error_message="Transfer iptal edildi"
                )
            else:
                self.logger.error(
                    f"Transfer incomplete: {transfer.filename} - "
                    f"bytes_sent={bytes_sent}, filesize={transfer.filesize}, status={transfer.status}"
                )
                raise Exception("Ağ bağlantısı koptu")
        finally:
            if reader is not None:
                reader.stop()
            if sock:
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
    
    def _await_completion(self, sock: socket.socket, transfer: Transfer, strict: bool) -> None:
        """TRANSFER_COMPLETE'ten sonra alıcının nihai yanıtını bekler.

        strict=True (alıcı `complete_ack` ilan etti): TRANSFER_COMPLETE_ACK(success=True)
        gelmezse CompletionNotConfirmed; TRANSFER_ERROR / success=False ise
        ReceiverReportedError (alıcının metniyle) fırlatılır.
        strict=False (eski alıcı): onay gelmezse eski davranış (başarı varsayımı) korunur,
        ancak alıcının AÇIKÇA bildirdiği hata her zaman iletilir.
        """
        for _ in range(50):  # PAUSE/RESUME gibi sızan kontrol mesajlarını atla
            try:
                response = self._receive_message(sock)
            except socket.timeout as timeout_error:
                if strict:
                    raise CompletionNotConfirmed("tamamlanma onayı için zaman aşımı") from timeout_error
                self.logger.warning("Eski alıcıdan tamamlanma onayı gelmedi; başarı varsayılıyor (eski sürüm uyumu)")
                return
            except OSError as recv_error:
                if strict:
                    raise CompletionNotConfirmed(str(recv_error)) from recv_error
                self.logger.warning(f"Eski alıcıda tamamlanma onayı okunamadı ({recv_error}); başarı varsayılıyor")
                return

            if not response:
                if strict:
                    raise CompletionNotConfirmed("bağlantı kapandı")
                self.logger.warning("Eski alıcı onay göndermeden bağlantıyı kapattı; başarı varsayılıyor (eski sürüm uyumu)")
                return

            msg_type, data = Protocol.parse_message(response)
            if msg_type == MessageType.TRANSFER_COMPLETE_ACK:
                success = data.get('success')
                if success is True or (not strict and success is None):
                    return
                raise ReceiverReportedError(data.get('error'))
            if msg_type == MessageType.TRANSFER_ERROR:
                raise ReceiverReportedError(data.get('error'))
            if msg_type == MessageType.CANCEL:
                raise ReceiverReportedError("Transfer alıcı tarafından iptal edildi")
            if msg_type in (MessageType.PAUSE, MessageType.RESUME, MessageType.PING, MessageType.PONG):
                continue
            if strict:
                raise CompletionNotConfirmed(f"beklenmeyen yanıt türü: {msg_type}")
            self.logger.warning(f"Eski alıcıdan beklenmeyen son yanıt ({msg_type}); başarı varsayılıyor")
            return
        if strict:
            raise CompletionNotConfirmed("tamamlanma onayı gelmedi")

    def _pending_receiver_error(self, sock: socket.socket) -> Optional[str]:
        """Gönderim hatasından sonra alıcının bıraktığı TRANSFER_ERROR metnini (varsa) okur."""
        try:
            sock.settimeout(1.5)
            for _ in range(8):
                response = self._receive_message(sock)
                if not response:
                    return None
                msg_type, data = Protocol.parse_message(response)
                if msg_type == MessageType.TRANSFER_ERROR:
                    return str(data.get('error') or '') or None
                if msg_type == MessageType.TRANSFER_COMPLETE_ACK and data.get('success') is False:
                    return str(data.get('error') or '') or None
        except Exception:
            return None
        return None

    def _send_message(self, sock: socket.socket, message: dict):
        """Send a protocol message"""
        send_all(sock, Protocol.encode_message(message))

    def _receive_message(self, sock: socket.socket) -> Optional[dict]:
        """Receive a protocol message"""
        try:
            length_data = recv_exact(sock, Protocol.HEADER_SIZE)
            if not length_data:
                return None
            length = int.from_bytes(length_data, byteorder='big')
            if length <= 0 or length > 8 * 1024 * 1024:
                return None
            message_data = recv_exact(sock, length)
            if not message_data:
                return None
            return Protocol.decode_message(message_data)
        except socket.timeout:
            raise
        except Exception as e:
            self.logger.error(f"Error receiving message: {e}")
            return None

