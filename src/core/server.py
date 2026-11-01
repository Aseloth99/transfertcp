"""TCP Server for receiving files"""

import hashlib
import json
import shutil
import socket
import ssl
import sys
import threading
import os
import time
import queue
from typing import Optional, Callable, Dict, List
from collections import deque
import struct


from .crypto import (
    ApprovalRequest,
    evaluate_peer,
    get_local_fingerprint,
    is_accept_from_anyone,
    is_encryption_enabled,
    trust_device,
    wrap_server_socket,
)
from .netio import (
    HANDSHAKE_TIMEOUT,
    TLS_CHUNK,
    TRANSFER_TIMEOUT,
    configure_socket,
    make_listen_socket,
    recv_exact,
    send_all,
    socket_has_data,
)
from .protocol import Protocol, MessageType
from .transfer import TransferManager
from ..models.transfer import Transfer, TransferDirection, TransferStatus

from ..utils.logger import get_logger
from ..utils.config import get_config
from ..utils import oserr
from ..utils.fileio import atomic_write_json, hash_file_prefix
from ..utils.filenames import fs_key, resolve_target
from ..utils.helpers import format_bytes
from ..utils.oserr import classify_os_error
from ..utils.paths import get_download_folder
from ..utils.ports import DEFAULT_TRANSFER_PORT


class IntegrityError(Exception):
    """Alınan verinin SHA-256 özeti göndericinin bildirdiğiyle uyuşmuyor."""


class DiskWriteError(Exception):
    """Yazıcı thread'i/diske yazma başarısız; özgün istisna `original`da (errno/winerror için) saklanır."""

    def __init__(self, original: BaseException):
        self.original = original
        super().__init__(f"Dosya diske yazılamadı: {original}")


class SenderProtocolError(Exception):
    """Gönderici protokolü ihlal etti (ör. bildirilen boyuttan fazla veri)."""


# Diske yazma tamponu transfer başına bu kadar bayta kadar büyür; dolunca ağdan okuma (ve ACK) bekler.
WRITE_BUFFER_BYTES = 24 * 1024 * 1024
SLOW_IO_SECONDS = 2.0  # bu süreden uzun bekleyen disk işlemleri günlüğe uyarı olarak yazılır


class _ByteBoundedQueue(queue.Queue):
    """Kuyruk dolulğunu ADET değil BAYT olarak sınırlar.

    Eskiden 48 parçalık kuyruk 256 KB'lık parçalarla ~12 MB tutuyordu; yerel ağda parçalar 4 MB olunca aynı
    kuyruk transfer başına 192 MB (3 eşzamanlı transferde ~600 MB) bellek tutabilir hale geldi. `maxsize` artık
    bayt sınırıdır; tek bir parça sınırı aşsa da kuyruğa girer (kuyruk boşken put asla kilitlenmez).
    """

    def _init(self, maxsize):
        super()._init(maxsize)
        self._bytes = 0

    def _qsize(self):
        return self._bytes

    @staticmethod
    def _weight(item) -> int:
        # Sentinel (None) de 1 sayılır: `Queue.get` doluluğu `_qsize()` ile anlar, 0 görürse sonsuza dek beklerdi
        return len(item) if item else 1

    def _put(self, item):
        super()._put(item)
        self._bytes += self._weight(item)

    def _get(self):
        item = super()._get()
        self._bytes -= self._weight(item)
        return item


class TCPServer:
    """TCP server for receiving file transfers"""

    MAX_CONNECTIONS = 32            # eşzamanlı gelen bağlantı üst sınırı
    MAX_FILE_SIZE = 16 * 1024 ** 4  # 16 TiB: bunun üstündeki filesize geçersiz sayılır
    MAX_ID_LENGTH = 128

    def __init__(self, transfer_manager: TransferManager):
        """
        Initialize TCP server
        
        Args:
            transfer_manager: Transfer manager instance
        """
        self.transfer_manager = transfer_manager
        self.config = get_config()
        self.logger = get_logger()
        
        self.server_socket: Optional[socket.socket] = None
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        
        self.port = self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)
        self.chunk_size = self.config.get('transfer', 'chunk_size', 1048576)
        self._last_update_time: dict[str, float] = {}
        
        # Client handlers (eşzamanlı bağlantı sınırı + biten thread'lerin temizliği)
        self.client_threads: List[threading.Thread] = []
        self._clients_lock = threading.Lock()
        self._active_clients = 0

        # Aynı .part'a yazan canlı alıcılar: {anahtar: {'sock','thread','sender','transfer_id'}}
        self._receivers: Dict[str, dict] = {}
        self._receivers_lock = threading.Lock()

        # Callbacks
        self.on_connection: Optional[Callable] = None
        self.on_file_received: Optional[Callable] = None
        self.on_device_approval: Optional[Callable] = None
        self.on_port_changed: Optional[Callable] = None
        self.port_retries = 10
        # Güncelleme yeniden başlatması: eski süreç çıkarken tercih edilen port birkaç yüz ms meşgul kalabilir.
        # `bind_retry_seconds` > 0 ise tercih edilen port bu süre boyunca yeniden denenir (varsayılan: hemen vazgeç).
        self.bind_retry_seconds = 0.0
        # False: başka porta kayılırsa yapılandırmaya YAZILMAZ (geçici bir meşguliyet kalıcı port değişikliğine dönüşmesin).
        self.remember_port_fallback = True
    
    def start(self):
        """Start the server, trying the next ports if the preferred one is busy."""
        if self.running:
            return

        preferred = int(self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT) or DEFAULT_TRANSFER_PORT)
        last_error = None

        port_bases = [preferred]
        if DEFAULT_TRANSFER_PORT not in port_bases:
            port_bases.append(DEFAULT_TRANSFER_PORT)

        for base in port_bases:
            for offset in range(self.port_retries):
                candidate = base + offset
                if candidate > 65535:
                    break
                try:
                    # Windows: SO_EXCLUSIVEADDRUSE; Linux/macOS: SO_REUSEADDR (REUSEPORT bilerek yok)
                    sock = self._listen(candidate, patient=(candidate == preferred))
                    self.server_socket = sock
                    self.port = candidate
                    self.running = True
                    self.server_thread = threading.Thread(target=self._accept_connections, daemon=True)
                    self.server_thread.start()
                    if candidate != preferred:
                        if self.remember_port_fallback:
                            self.config.set('transfer', 'port', candidate)
                        self.logger.warning(
                            f"Port {preferred} kullanılamadı, {candidate} ile devam ediliyor"
                        )
                        if self.on_port_changed:
                            try:
                                self.on_port_changed(preferred, candidate)
                            except Exception:
                                pass
                    else:
                        self.logger.info(f"TCP Server started on port {self.port}")
                    return
                except OSError as e:
                    last_error = e
                    self.logger.warning(f"Port {candidate} dinlenemedi: {e}")

        self.running = False
        self.logger.error(
            f"TCP sunucusu başlatılamadı (son port denendi): {last_error}"
        )
    
    def _listen(self, port: int, patient: bool = False) -> socket.socket:
        """Dinleme soketi aç. `patient` ve `bind_retry_seconds` > 0 ise OSError'da kısa aralıklarla yeniden dener."""
        deadline = time.time() + (self.bind_retry_seconds if patient else 0.0)
        while True:
            try:
                return make_listen_socket(port)
            except OSError:
                if time.time() >= deadline:
                    raise
                time.sleep(0.25)

    def stop(self, join_timeout: float = 3.0):
        """Stop the server (join_timeout: tüm istemci thread'lerini bekleme üst sınırı, sn)"""
        self.running = False

        listener = self.server_socket
        if listener:
            self._close_listener(listener)

        # Wait for client threads (toplam süre sınırlı: çıkışı 30+ sn bekletmesin)
        with self._clients_lock:
            threads = list(self.client_threads)
        deadline = time.time() + join_timeout
        for thread in threads:
            thread.join(timeout=max(0.05, deadline - time.time()))

        with self._clients_lock:
            self.client_threads.clear()
        self.logger.info("TCP Server stopped")

    def _close_listener(self, listener: socket.socket) -> None:
        """Dinleme soketini kapatıp `accept()`te bekleyen thread'i uyandırır.

        Linux/macOS'ta başka bir thread `accept()` içindeyken yalnızca `close()` onu güvenilir
        biçimde uyandırmaz (thread bloklu kalır; Linux'ta hiç, macOS'ta hataya bağlı). Bu yüzden
        `running=False` iken, dinleyici HÂLÂ açıkken yerel bir "uyandırma" bağlantısı yapılır:
        `accept()` döner, döngü `running`i görüp çıkar. Sonra soket kapatılır.
        """
        port = None
        try:
            port = listener.getsockname()[1]
        except OSError:
            pass
        thread = self.server_thread
        if port and thread is not None and thread.is_alive() and thread is not threading.current_thread():
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            except OSError:
                pass  # soket zaten kapalı/uyandı: sorun yok
            thread.join(timeout=1.0)
        try:
            listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # dinleyen soketi shutdown'ı (macOS/Windows) reddedebilir
        try:
            listener.close()
        except OSError:
            pass

    def _accept_connections(self):
        """Accept incoming connections"""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                if not self.running:
                    # stop() uyandırma bağlantısı (veya kapanış sırasında gelen son bağlantı)
                    try:
                        client_socket.close()
                    except OSError:
                        pass
                    break

                # Eşzamanlı bağlantı sınırı: boşta bekleyen/kötü niyetli bağlantılar kaynağı tüketmesin
                with self._clients_lock:
                    # Biten thread'leri listeden çıkar (liste sınırsız büyümesin)
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    accepted = self._active_clients < self.MAX_CONNECTIONS
                    if accepted:
                        self._active_clients += 1
                if not accepted:
                    self.logger.warning(
                        f"Bağlantı sınırı ({self.MAX_CONNECTIONS}) dolu; {address[0]} reddedildi"
                    )
                    try:
                        client_socket.close()
                    except OSError:
                        pass
                    continue

                try:
                    configure_socket(client_socket, HANDSHAKE_TIMEOUT)
                    self.logger.info(f"Client connected from {address}")

                    # Handle client in separate thread
                    thread = threading.Thread(
                        target=self._client_main,
                        args=(client_socket, address),
                        daemon=True
                    )
                    thread.start()
                    with self._clients_lock:
                        self.client_threads.append(thread)
                except Exception:
                    self._release_client_slot()
                    try:
                        client_socket.close()
                    except OSError:
                        pass
                    raise

                if self.on_connection:
                    self.on_connection(address[0])

            except Exception as e:
                if self.running:
                    self.logger.error(f"Error accepting connection: {e}")
                    time.sleep(0.1)  # EMFILE gibi kalıcı hatalarda sıkı döngüyü önle

    def _release_client_slot(self) -> None:
        with self._clients_lock:
            if self._active_clients > 0:
                self._active_clients -= 1

    def _client_main(self, client_socket: socket.socket, address: tuple):
        """Bağlantı thread'inin gövdesi: işlem bitince (hata dahil) yuvayı serbest bırakır."""
        try:
            self._handle_client(client_socket, address)
        finally:
            self._release_client_slot()

    def _handle_client(self, client_socket: socket.socket, address: tuple):
        """Handle client connection with STARTTLS negotiation"""
        try:
            # Receive plain handshake first
            message = self._receive_message(client_socket)
            if not message:
                return
            
            msg_type, data = Protocol.parse_message(message)

            if msg_type == MessageType.HANDSHAKE:
                if not Protocol.is_compatible_version(message):
                    self.logger.warning(
                        f"Uyumsuz protokol sürümü {message.get('version')!r} ({address[0]}), reddedildi"
                    )
                    try:
                        self._send_message(client_socket, Protocol.create_handshake_reject("unsupported_version"))
                    except Exception:
                        pass
                    return

                device_name = data.get('device_name', 'Unknown')
                peer_fp = data.get('fingerprint')
                client_supports_enc = bool(data.get('supports_encryption', False))
                server_supports_enc = is_encryption_enabled()
                will_encrypt = client_supports_enc and server_supports_enc
                # Yeni davranışlar yalnızca karşı taraf ilan ederse etkin (eski sürüm = boş küme)
                peer_features = Protocol.negotiate_features(data)

                if not self._authorize_peer(client_socket, address, device_name, peer_fp):
                    return

                local_fp = get_local_fingerprint()
                ack = Protocol.create_handshake_ack(
                    fingerprint=local_fp,
                    supports_encryption=will_encrypt,
                    proto=Protocol.PROTO_VERSION,
                    features=Protocol.LOCAL_FEATURES,
                )
                self._send_message(client_socket, ack)
                
                if will_encrypt:
                    try:
                        client_socket = wrap_server_socket(client_socket)
                        configure_socket(client_socket, TRANSFER_TIMEOUT)
                        self.logger.info(f"TLS 1.3 session established with {device_name} ({address[0]})")
                    except Exception as tls_error:
                        self.logger.error(f"TLS handshake failed from {address[0]}: {tls_error}")
                        return
                else:
                    configure_socket(client_socket, TRANSFER_TIMEOUT)
                    self.logger.info(f"Plain TCP session with {device_name} ({address[0]})")

                self.logger.info(
                    f"Handshake complete with {device_name} "
                    f"(proto={data.get('proto', 1)}, features={sorted(peer_features)})"
                )

                # Receive file info
                self._receive_file(client_socket, address, device_name,
                                   peer_fp=peer_fp, features=peer_features)
            
        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            self._graceful_close(client_socket)

    @staticmethod
    def _graceful_close(sock: socket.socket, linger: float = 1.5) -> None:
        """Düz TCP'de önce FIN gönderip kalan veriyi kısa süre boşaltır.

        Okunmamış veri varken doğrudan close() RST üretir ve göndericinin henüz okumadığı
        son TRANSFER_ERROR/ACK mesajı kaybolabilir (gönderici yalnızca "bağlantı koptu" görür).
        TLS soketinde kapatma bildirimi için shutdown() kullanılamadığından doğrudan kapatılır.
        """
        try:
            if not isinstance(sock, ssl.SSLSocket):
                try:
                    sock.shutdown(socket.SHUT_WR)
                    sock.settimeout(0.5)
                    deadline = time.time() + linger
                    while time.time() < deadline:
                        if not sock.recv(65536):
                            break
                except OSError:
                    pass
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _authorize_peer(self, client_socket: socket.socket, address: tuple,
                        device_name: str, fingerprint: Optional[str]) -> bool:
        """Trust-on-first-use gate for incoming senders."""
        peer_fp = fingerprint or f"legacy:{address[0]}"
        status, previous = evaluate_peer(peer_fp, address[0])

        if status == "ok":
            trust_device(peer_fp, device_name, address[0])
            return True

        if status == "mismatch":
            old_name = (previous or {}).get("device_name", "Unknown")
            self.logger.warning(
                f"Identity changed for {address[0]}: was {old_name}, now {device_name}"
            )

        if is_accept_from_anyone():
            trust_device(peer_fp, device_name, address[0])
            self.logger.info(f"Auto-accepted {device_name} ({address[0]}) — accept from anyone")
            return True

        request = ApprovalRequest(device_name, address[0], peer_fp)
        if self.on_device_approval:
            try:
                self.on_device_approval(request)
                request.event.wait(timeout=90)
            except Exception as approval_error:
                self.logger.error(f"Device approval callback failed: {approval_error}")
        else:
            request.approved = False

        if not request.approved:
            self.logger.info(f"User rejected incoming device {device_name} ({address[0]})")
            try:
                self._send_message(
                    client_socket,
                    Protocol.create_handshake_reject("user_rejected")
                )
            except Exception:
                pass
            return False

        trust_device(peer_fp, device_name, address[0])
        self.logger.info(f"User trusted {device_name} ({address[0]})")
        return True
    
    def _receive_file(self, client_socket: socket.socket, address: tuple,
                     device_name: str, peer_fp: Optional[str] = None,
                     features: frozenset = frozenset()):
        """Receive file from client.

        features: el sıkışmada anlaşılan ortak özellikler (boş = eski sürüm gönderici).
        """
        transfer = None
        transfer_id = None
        claimed_part = None  # _claim_part ile sahiplenilen .part yolu (finally'de bırakılır)
        claim_entry = None
        completing = False  # tamamlanma/kaydetme aşamasına gelindi mi (hata iletiminde kullanılır)

        def _superseded() -> bool:
            """Aynı kimlikli yeni bir deneme bu bağlantının yerini aldı mı (bayat thread)."""
            return claim_entry is not None and claim_entry['superseded'].is_set()

        try:
            # Receive file info
            message = self._receive_message(client_socket)
            if not message:
                return
            
            msg_type, data = Protocol.parse_message(message)
            
            if msg_type != MessageType.FILE_INFO:
                return
            
            # Gelen alanları doğrula (tip/negatif/aşırı boyut): geçersizse FILE_INFO_REJECT
            problem = self._validate_file_info(data)
            if problem:
                self.logger.warning(f"Geçersiz FILE_INFO ({address[0]}): {problem}")
                self._reject_file_info(client_socket, data.get('transfer_id'), problem)
                return

            transfer_id = data['transfer_id']
            filename = data['filename']
            filesize = data['filesize']
            checksum = data.get('checksum') or ""
            relative_path = data.get('relative_path')  # For folder transfers
            folder_name = data.get('folder_name')
            folder_total = data.get('folder_total')
            folder_id = data.get('folder_id')

            self.logger.info(f"Receiving file: {filename} ({filesize} bytes, relative_path: {relative_path}, folder: {folder_name}, total: {folder_total}, folder_id: {folder_id})")

            # Get download folder
            download_folder = get_download_folder(self.config.get('transfer', 'download_folder', ''))

            # Sanitize destination path against directory traversal
            filepath = self._sanitize_path(download_folder, relative_path, filename)

            if self._is_running_executable(filepath):
                root, ext = os.path.splitext(filepath)
                filepath = f"{root}-gelen{ext}"
                self.logger.warning(f"Hedef çalışan exe, farklı ada yazılıyor: {filepath}")

            part_path = filepath + ".part"
            meta_path = self._meta_path(part_path)
            sender_id = peer_fp or f"legacy:{address[0]}"

            # Aynı .part'a yazan başka canlı alıcı: aynı göndericiyse (ağ kopması sonrası yeniden deneme)
            # bayat bağlantı kapatılır; farklı göndericiyse reddedilir (iki yazıcı dosyayı bozardı).
            claim_error, claim_entry = self._claim_part(part_path, client_socket, sender_id, transfer_id)
            if claim_error:
                self.logger.warning(f"{filename}: {claim_error}")
                self._reject_file_info(client_socket, transfer_id, claim_error)
                return
            claimed_part = part_path

            # Yeni davranışlar yalnızca gönderici ilan ettiyse etkin (eski gönderici = eski davranış)
            use_sha = Protocol.FEATURE_SHA256 in features
            use_meta = Protocol.FEATURE_RESUME_META in features

            # .part ve meta için klasör hazır olsun
            file_dir = os.path.dirname(filepath)
            if file_dir:
                try:
                    os.makedirs(file_dir, exist_ok=True)
                except Exception as dir_err:
                    self.logger.warning(f"Could not create directory {file_dir}: {dir_err}")

            # Hedef sürücüde yeterli boş alan var mı (yarım .part zaten yer tutuyor)
            existing_part = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
            needed = max(0, filesize - existing_part)
            free = self._free_space(filepath)
            if needed > 0 and free is not None and needed + self.DISK_RESERVE > free:
                reason = (f"Diskte yeterli boş alan yok (gerekli: {format_bytes(needed)}, "
                          f"boş: {format_bytes(free)}).")
                self.logger.warning(f"{filename}: {reason}")
                self._reject_file_info(client_socket, transfer_id, reason)
                return

            mtime_ns = data.get('mtime_ns')
            expected_meta = {
                'v': 1,
                'transfer_id': transfer_id,
                'filename': os.path.basename(filepath),
                'relative_path': relative_path or "",
                'filesize': filesize,
                'mtime_ns': mtime_ns if isinstance(mtime_ns, int) and not isinstance(mtime_ns, bool) else None,
                'sender': sender_id,
            }

            # Yarım kalmış .part varsa devam et — ama yalnızca eşleşiyorsa (meta doğrulaması)
            piece_size = TLS_CHUNK if is_encryption_enabled() else self.chunk_size
            resumed_from_chunk, resumed_bytes = self._plan_resume(
                part_path, meta_path, expected_meta, filesize, piece_size, use_meta, filename
            )
            if use_meta:
                try:
                    atomic_write_json(meta_path, expected_meta)
                except OSError as meta_err:
                    self.logger.warning(f"Resume meta yazılamadı ({meta_path}): {meta_err}")

            # Create transfer object FAST
            transfer = Transfer(
                transfer_id=transfer_id,
                filepath=filepath,
                filename=filename,
                filesize=filesize,
                device_ip=address[0],
                device_name=device_name,
                direction=TransferDirection.RECEIVE,
                relative_path=relative_path  # Include relative_path for folder transfers
            )
            transfer.checksum = checksum
            transfer.folder_name = folder_name
            transfer.folder_total = folder_total
            transfer.folder_id = folder_id
            if resumed_bytes > 0:
                transfer.bytes_transferred = resumed_bytes
            
            # Add to active transfers IMMEDIATELY (aynı kimlikli bayat kayıt varsa yerini alır)
            self.transfer_manager.register_transfer(transfer)

            # Send acknowledgment QUICKLY with resume info
            ack = Protocol.create_file_info_ack(
                transfer_id,
                resumed_from_chunk=resumed_from_chunk,
                resumed_bytes=resumed_bytes
            )
            self._send_message(client_socket, ack)
            self.logger.info(f"ACK sent for {filename} (resume chunk: {resumed_from_chunk})")
            
            # NOW do heavy operations (after ACK sent)
            file_dir = os.path.dirname(filepath)
            if file_dir:
                try:
                    os.makedirs(file_dir, exist_ok=True)
                except Exception as dir_err:
                    self.logger.warning(f"Could not create directory {file_dir}: {dir_err}")
            
            # Notify callback (UI update) - thread-safe with error handling
            if self.on_file_received:
                try:
                    self.on_file_received(transfer)
                except Exception as callback_error:
                    self.logger.error(f"Error in file_received callback: {callback_error}", exc_info=True)
                    # Don't fail the transfer if UI callback fails
            
            # Start receiving
            transfer.start()
            
            # Receive file data
            bytes_received = resumed_bytes
            start_time = time.time()
            last_update_time = start_time
            
            # Speed calculation tracking - store last N measurements
            speed_samples = deque()  # deque of (time, bytes) tuples
            speed_window = 2.5  # Calculate speed over last 2.5 seconds for smooth readout
            
            self.logger.info(f"Starting to receive chunks for {filename}...")
            
            # Ensure file directory exists before opening file (double-check)
            file_dir = os.path.dirname(filepath)
            if file_dir:
                try:
                    os.makedirs(file_dir, exist_ok=True)
                except Exception as dir_error:
                    self.logger.error(f"Failed to create file directory {file_dir}: {dir_error}", exc_info=True)
                    raise Exception(f"Dosya klasörü oluşturulamadı: {dir_error}")
            
            file_mode = "ab" if resumed_bytes > 0 else "wb"
            write_queue = _ByteBoundedQueue(maxsize=WRITE_BUFFER_BYTES)
            write_error = [None]
            writer_stop_event = threading.Event()
            # Akış üzerinde SHA-256: yalnızca yazıcı thread dokunur (recv döngüsünü yavaşlatmaz);
            # writer_thread.join() sonrası okunur.
            hasher = hashlib.sha256() if use_sha else None

            def _disk_writer():
                try:
                    if hasher is not None and resumed_bytes > 0:
                        # Devam edilen önek de özete girmeli (uçtan uca bütünlük)
                        hash_file_prefix(hasher, part_path, resumed_bytes)
                    with open(part_path, file_mode, buffering=1024 * 1024) as f:
                        while not writer_stop_event.is_set() or not write_queue.empty():
                            try:
                                chunk_item = write_queue.get(timeout=0.2)
                            except queue.Empty:
                                continue
                            if chunk_item is None:
                                write_queue.task_done()
                                break
                            # Antivirüs veya indeksleme kaynaklı anlık dosya kilitlerinde yeniden dene
                            for write_attempt in range(5):
                                try:
                                    f.write(chunk_item)
                                    break
                                except OSError as wexc:
                                    if write_attempt < 4:
                                        time.sleep(0.05 * (write_attempt + 1))
                                    else:
                                        raise
                            if hasher is not None:
                                hasher.update(chunk_item)
                            write_queue.task_done()
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except OSError:
                            pass
                except Exception as exc:
                    self.logger.error(f"Background disk writer error for {part_path}: {exc}")
                    write_error[0] = exc

            writer_thread = threading.Thread(target=_disk_writer, daemon=True)
            writer_thread.start()

            last_slow_log = 0.0
            try:
                receiver_paused_notified = False
                paused_by_remote = False
                while bytes_received < filesize:
                    if write_error[0]:
                        raise DiskWriteError(write_error[0])

                    # Check if paused or cancelled (LOCAL control)
                    current_status = transfer.status.value if hasattr(transfer.status, 'value') else str(transfer.status)
                    if current_status == 'paused':
                        if not paused_by_remote and not receiver_paused_notified:
                            try:
                                pause_msg = Protocol.create_message(MessageType.PAUSE, {'transfer_id': transfer_id})
                                self._send_message(client_socket, pause_msg)
                                receiver_paused_notified = True
                                self.logger.info(f"Transfer paused locally, notified sender: {filename}")
                            except Exception:
                                pass

                        # While paused, listen for messages without blocking
                        if socket_has_data(client_socket, timeout=0.1):
                            try:
                                message = self._receive_message(client_socket)
                                if message:
                                    msg_type, _ = Protocol.parse_message(message)
                                    if msg_type == MessageType.RESUME:
                                        self.logger.info(f"Transfer resumed by remote sender: {filename}")
                                        paused_by_remote = False
                                        transfer.resume()
                                        continue
                                    elif msg_type == MessageType.CANCEL:
                                        self.logger.info(f"Transfer cancelled by remote sender: {filename}")
                                        break
                            except Exception as e:
                                self.logger.warning(f"Error while waiting in paused state: {e}")
                                break

                        time.sleep(0.05)
                        continue
                    elif receiver_paused_notified:
                        try:
                            resume_msg = Protocol.create_message(MessageType.RESUME, {'transfer_id': transfer_id})
                            self._send_message(client_socket, resume_msg)
                            receiver_paused_notified = False
                            self.logger.info(f"Transfer resumed locally, notified sender: {filename}")
                        except Exception:
                            pass

                    if current_status == 'cancelled':
                        self.logger.info(f"Transfer cancelled (local): {filename}")
                        try:
                            cancel_msg = Protocol.create_cancel(transfer_id)
                            self._send_message(client_socket, cancel_msg)
                            self.logger.info(f"Sent cancel message to sender: {filename}")
                        except Exception as ce:
                            self.logger.debug(f"Failed to send cancel notice: {ce}")
                        break
                    
                    # Receive message
                    try:
                        message = self._receive_message(client_socket)
                        if not message:
                            if transfer.status == TransferStatus.CANCELLED:
                                break
                            self.logger.warning(f"No message received, breaking loop. bytes_received={bytes_received}/{filesize}")
                            break
                        
                        msg_type, chunk_data = Protocol.parse_message(message)
                        
                        if msg_type == MessageType.CANCEL:
                            self.logger.info(f"Transfer cancelled by remote sender: {filename}")
                            transfer.cancel()
                            break
                        elif msg_type == MessageType.PAUSE:
                            self.logger.info(f"Transfer paused by remote sender: {filename}")
                            paused_by_remote = True
                            transfer.pause()
                            continue
                        elif msg_type == MessageType.RESUME:
                            self.logger.info(f"Transfer resumed by remote sender: {filename}")
                            paused_by_remote = False
                            transfer.resume()
                            continue
                        elif msg_type == MessageType.CHUNK_DATA:
                            chunk_index = chunk_data['chunk_index']
                            total_chunks = chunk_data.get('total_chunks', 0)
                            
                            # Receive chunk size (4 bytes)
                            size_data = recv_exact(client_socket, 4)
                            if not size_data:
                                self.logger.warning(f"No chunk size received for chunk {chunk_index}, breaking loop")
                                break
                            chunk_size = struct.unpack('!I', size_data)[0]
                            if chunk_size <= 0 or chunk_size > 16 * 1024 * 1024:
                                self.logger.warning(f"Invalid chunk size {chunk_size} for chunk {chunk_index}")
                                break
                            if bytes_received + chunk_size > filesize:
                                # Bildirilen boyuttan fazla veri: dosya sessizce büyümesin
                                raise SenderProtocolError(
                                    f"Gönderici bildirilen boyuttan fazla veri gönderdi "
                                    f"({bytes_received + chunk_size} > {filesize})"
                                )

                            # Receive chunk data into memory
                            chunk = recv_exact(client_socket, chunk_size)
                            if not chunk:
                                self.logger.warning(f"No chunk data received for chunk {chunk_index}, breaking loop")
                                break
                            
                            # Pipelined ACK: Send ACK immediately upon receiving chunk in memory!
                            # This allows the sender to transmit the next chunk over the wire
                            # in parallel with asynchronous disk write, eliminating OS cache flush stalls.
                            try:
                                ack = Protocol.create_chunk_ack(transfer_id, chunk_index)
                                if transfer.status == TransferStatus.PAUSED and not paused_by_remote:
                                    ack['data']['pause_requested'] = True
                                    receiver_paused_notified = True
                                self._send_message(client_socket, ack)
                                self.logger.debug(f"ACK sent for chunk {chunk_index}/{total_chunks}")
                            except socket.error as sock_error:
                                self.logger.error(f"Socket error sending ACK {chunk_index}: {sock_error}")
                                raise
                            except Exception as ack_error:
                                self.logger.error(f"Failed to send chunk ACK {chunk_index}: {ack_error}")
                                raise
                            
                            # Queue chunk for background disk write. Yazıcı thread ölürse kuyruk dolunca
                            # sonsuza dek bloklanmamak için zaman aşımlı put + yazıcı canlılık kontrolü.
                            enqueue_started = time.monotonic()
                            self._enqueue_chunk(write_queue, chunk, writer_thread, write_error)
                            queue_wait = time.monotonic() - enqueue_started
                            if queue_wait > SLOW_IO_SECONDS and time.monotonic() - last_slow_log > 10:
                                last_slow_log = time.monotonic()
                                self.logger.warning(
                                    f"{filename}: diske yazma kuyruğu {queue_wait:.1f} sn dolu kaldı "
                                    f"(parça {chunk_index}); disk ya da antivirüs yavaş, gönderici ACK bekliyor"
                                )
                            bytes_received += len(chunk)
                            
                            self.logger.debug(f"Received chunk {chunk_index}/{total_chunks}: {len(chunk)} bytes (total: {bytes_received}/{filesize})")
                            
                            # Calculate speed using O(1) sliding window (last 1.5 seconds)
                            current_time = time.time()
                            speed_samples.append((current_time, bytes_received))
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
                                speed = bytes_received / elapsed if elapsed > 0 else 0

                            # Update progress (throttled to every 200ms for stability)
                            if current_time - last_update_time >= 0.2:
                                self.transfer_manager.update_progress(transfer_id, bytes_received, speed)
                                last_update_time = current_time
                        else:
                            self.logger.warning(f"Unexpected message type: {msg_type}, breaking loop")
                            break
                    except socket.timeout:
                        self.logger.warning(f"Timeout receiving chunk, bytes_received={bytes_received}/{filesize}")
                        break
                    except (DiskWriteError, SenderProtocolError):
                        raise  # anlamlı hatalar yutulmasın; alıcı hata yoluna gitsin
                    except Exception as recv_error:
                        self.logger.error(f"Error receiving chunk: {recv_error}, bytes_received={bytes_received}/{filesize}")
                        break
            finally:
                writer_stop_event.set()
                try:
                    write_queue.put(None, timeout=1.0)
                except Exception:
                    pass
                join_started = time.monotonic()
                writer_thread.join(timeout=120)
                join_wait = time.monotonic() - join_started
                if join_wait > 5.0:
                    self.logger.warning(
                        f"{filename}: kalan veri diske {join_wait:.1f} sn'de yazıldı (bitirme/flush); "
                        f"disk ya da antivirüs yavaş olabilir"
                    )

            if write_error[0]:
                raise DiskWriteError(write_error[0])
            if writer_thread.is_alive():
                # Yazıcı hâlâ bitmedi: dosya eksik olabilir, tamamlandı sayma
                raise DiskWriteError(TimeoutError("diske yazma zaman aşımı"))

            # Check if complete (use >= to handle rounding issues)
            if bytes_received >= filesize and transfer.status != TransferStatus.CANCELLED:
                completing = True  # bundan sonraki hatalar "dosya kaydedilemedi" aşamasıdır
                if receiver_paused_notified:
                    # Son parçada yerel duraklatma bildirilmişse göndericinin devam bekleyen
                    # döngüsünü serbest bırak (aksi halde TRANSFER_COMPLETE hiç gelmez)
                    try:
                        self._send_message(client_socket, Protocol.create_message(
                            MessageType.RESUME, {'transfer_id': transfer_id}))
                    except Exception:
                        pass

                # 1) Göndericinin TRANSFER_COMPLETE bildirimini (özet) bekle
                got_complete, peer_checksum = self._await_transfer_complete(client_socket)
                if not got_complete and features:
                    # Yeni sürüm gönderici bildirimi mutlaka gönderir; yoksa tamamlanma doğrulanamaz.
                    # .part devam (resume) için korunur.
                    raise Exception("Gönderici tamamlanma bildirimini göndermedi (bağlantı koptu)")

                # 2) Bütünlük: akış SHA-256 özeti göndericininkiyle eşleşmeli
                digest = None
                if hasher is not None:
                    digest = hasher.hexdigest()
                    if peer_checksum.lower() != digest:
                        self.logger.error(
                            f"SHA-256 uyuşmuyor ({filename}): gelen={digest}, gönderici={peer_checksum or '(yok)'}"
                        )
                        self._delete_if_exists(part_path)
                        self._delete_if_exists(meta_path)
                        raise IntegrityError("SHA-256 uyuşmuyor")

                # 3) Nihai ada taşı: üzerine yazma açıksa var olan dosya değiştirilir (kilitliyse benzersiz ad),
                #    kapalıysa benzersiz ad rezerve edilir (bkz. _finalize_part)
                finalize_started = time.monotonic()
                filepath = self._finalize_part(part_path, filepath)
                finalize_wait = time.monotonic() - finalize_started
                if finalize_wait > 3.0:
                    self.logger.warning(
                        f"{filename}: dosya son adına {finalize_wait:.1f} sn'de taşındı "
                        f"(hedef dosya başka bir program/antivirüs tarafından kullanılıyor olabilir)"
                    )
                self._delete_if_exists(meta_path)

                transfer.filepath = filepath
                if digest:
                    transfer.checksum = digest
                self.transfer_manager.complete_transfer(transfer_id, success=True)
                self.logger.info(f"File received successfully: {filename} ({bytes_received}/{filesize} bytes)")

                # 4) Göndericiye onay (ACK). Başarı bu noktadan sonra geri alınamaz; ACK gönderilemezse
                # yalnızca günlüğe yazılır (gönderici onay alamayınca kendi tarafında başarısız sayar).
                if got_complete:
                    try:
                        self._send_message(client_socket, Protocol.create_transfer_complete_ack(transfer_id, success=True))
                    except Exception as comp_err:
                        self.logger.debug(f"Transfer tamamlanma onayı iletimi: {comp_err}")
                completing = False
            else:
                is_cancelled = (getattr(transfer, 'status', None) == TransferStatus.CANCELLED)
                if is_cancelled:
                    self.logger.info(f"Transfer was cancelled: {filename}")
                    self.transfer_manager.complete_transfer(
                        transfer_id, 
                        success=False, 
                        error_message="Transfer iptal edildi"
                    )
                    self._delete_if_exists(part_path)
                    self._delete_if_exists(meta_path)
                elif _superseded() or self.transfer_manager.get_transfer(transfer_id) is not transfer:
                    # Aynı kimlikle yeni bir deneme devraldı: bu bayat iş parçacığı yeni kaydı bozmamalı
                    self.logger.info(f"Bayat alıcı bağlantısı sonlandı (yeni deneme devraldı): {filename}")
                else:
                    # Eksik transfer: .part devam (resume) için korunur. Var olan hedef
                    # dosyaya (filepath) ASLA dokunulmaz — eskiden burada siliniyordu.
                    self.logger.error(f"Transfer incomplete: {filename} - bytes_received={bytes_received}, filesize={filesize}")
                    self.transfer_manager.complete_transfer(
                        transfer_id,
                        success=False,
                        error_message=f"Eksik transfer: {bytes_received}/{filesize} byte alındı"
                    )

        except Exception as e:
            is_cancelled = transfer and getattr(transfer, 'status', None) == TransferStatus.CANCELLED
            if _superseded() or (transfer is not None and self.transfer_manager.get_transfer(transfer_id) is not transfer):
                # Aynı kimlikle yeni bir deneme devraldı (bayat bağlantı kapatıldı): yeni kaydı bozma
                self.logger.info(f"Bayat alıcı bağlantısı sonlandı (yeni deneme devraldı): {e}")
                return
            if not is_cancelled:
                self.logger.exception(f"Error receiving file: {e}")
            else:
                self.logger.info(f"Transfer was cancelled during receive: {filename}")
            if transfer_id:
                if is_cancelled:
                    user_error = "Transfer iptal edildi"
                else:
                    user_error = self._format_receiver_error(e)

                # Göndericiye hata durumunu bildir (böylece gönderici başarı varsaymaz)
                wire_error = user_error
                if completing and not features:
                    # Eski sürüm gönderici yalnızca bu kalıbı içeren TRANSFER_ERROR'ı hata sayar
                    wire_error = f"Alıcı cihaz dosyayı kaydedemedi: {user_error}"
                try:
                    err_msg = Protocol.create_transfer_error(transfer_id, wire_error)
                    self._send_message(client_socket, err_msg)
                except Exception:
                    pass

                if transfer is not None:
                    self.transfer_manager.complete_transfer(
                        transfer_id,
                        success=False,
                        error_message=user_error
                    )

                # Yalnızca .part (ve yalnızca iptalde) silinir; nihai hedef dosya
                # sağlam olabilir ve hiçbir hata yolunda silinmez.
                if transfer and hasattr(transfer, 'filepath') and is_cancelled:
                    self._delete_if_exists(transfer.filepath + ".part")
                    self._delete_if_exists(self._meta_path(transfer.filepath + ".part"))
        finally:
            if claimed_part is not None:
                self._release_part(claimed_part)

    # -- giriş doğrulama / kaynak yönetimi ---------------------------------------
    DISK_RESERVE = 1024 * 1024  # boş alan denetiminde bırakılan pay (1 MiB)

    def _validate_file_info(self, data: dict) -> Optional[str]:
        """FILE_INFO alanlarını doğrular; geçersizse kullanıcıya dönük gerekçe, yoksa None."""
        transfer_id = data.get('transfer_id')
        filename = data.get('filename')
        filesize = data.get('filesize')
        if not isinstance(transfer_id, str) or not transfer_id or len(transfer_id) > self.MAX_ID_LENGTH:
            return "Geçersiz transfer kimliği."
        if not isinstance(filename, str) or not filename.strip() or len(filename) > 1024:
            return "Geçersiz dosya adı."
        if isinstance(filesize, bool) or not isinstance(filesize, int):
            return "Geçersiz dosya boyutu."
        if filesize < 0 or filesize > self.MAX_FILE_SIZE:
            return "Geçersiz dosya boyutu (negatif veya izin verilen üst sınırı aşıyor)."
        for key in ('relative_path', 'folder_name', 'folder_id'):
            value = data.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 4096):
                return f"Geçersiz alan: {key}."
        folder_total = data.get('folder_total')
        if folder_total is not None and (isinstance(folder_total, bool) or not isinstance(folder_total, int)):
            return "Geçersiz alan: folder_total."
        return None

    def _reject_file_info(self, sock: socket.socket, transfer_id, reason: str) -> None:
        """Göndericiye FILE_INFO_REJECT (gerekçeyle) gönderir; gönderici arayüzünde gösterilir."""
        try:
            tid = transfer_id if isinstance(transfer_id, str) else ""
            self._send_message(sock, Protocol.create_file_info_reject(tid[:self.MAX_ID_LENGTH], reason))
        except Exception:
            pass

    def _free_space(self, path: str) -> Optional[int]:
        """Hedefin bulunduğu sürücüdeki boş bayt (klasör henüz yoksa var olan üst klasörden)."""
        probe = os.path.dirname(os.path.abspath(path))
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            return None  # ölçülemiyorsa engelleme

    def _claim_part(self, part_path: str, sock: socket.socket, sender_id: str,
                    transfer_id: str):
        """`.part` yolunu bu thread'e ayırır: (hata_metni | None, kayıt).

        Çakışmada (hata_metni, None) döner. `kayıt['superseded']` bu bağlantı bayat sayılıp
        yerine yenisi geçtiğinde set edilir; bayat thread bu durumda sessizce çekilir.

        Aynı göndericiden AYNI transfer kimliğiyle gelen yeni deneme (ağ kopması sonrası yeniden
        deneme) bayat bağlantıyı kapatıp onun yazıcısının dosyayı bırakmasını bekler. Başka bir
        transfer/gönderici aynı dosyayı alıyorsa reddedilir (iki yazıcı dosyayı bozardı).
        """
        key = fs_key(part_path)
        me = threading.current_thread()
        with self._receivers_lock:
            old = self._receivers.get(key)
            stale = None
            if old is not None and old['thread'] is not me and old['thread'].is_alive():
                if old['sender'] != sender_id or old['transfer_id'] != transfer_id:
                    return "Bu dosya şu anda başka bir transferde alınıyor; biraz sonra tekrar deneyin.", None
                stale = old
            entry = {
                'sock': sock, 'thread': me, 'sender': sender_id, 'transfer_id': transfer_id,
                'superseded': threading.Event(),
            }
            self._receivers[key] = entry
        if stale is not None:
            self.logger.info(f"Aynı göndericiden yeni deneme: bayat bağlantı kapatılıyor ({os.path.basename(part_path)})")
            stale['superseded'].set()  # bayat thread kapanırken hata/başarısızlık bildirmesin
            # Bloklu recv'i düşürmek için: shutdown (POSIX'te select'i uyandırır) + close (Windows'ta
            # select yalnızca soket kapanınca hata ile döner; shutdown tek başına uyandırmaz).
            try:
                socket.socket.shutdown(stale['sock'], socket.SHUT_RDWR)  # TLS katmanını atlar
            except (OSError, ValueError):
                pass
            try:
                stale['sock'].close()
            except OSError:
                pass
            stale['thread'].join(timeout=10)
        return None, entry

    def _release_part(self, part_path: str) -> None:
        key = fs_key(part_path)
        with self._receivers_lock:
            entry = self._receivers.get(key)
            if entry is not None and entry['thread'] is threading.current_thread():
                del self._receivers[key]

    @staticmethod
    def _enqueue_chunk(write_queue: "queue.Queue", chunk: bytes, writer_thread: threading.Thread,
                       write_error: list) -> None:
        """Yazıcı thread ölürse (kuyruk dolunca) sonsuza dek bloklanmak yerine hatayı yükseltir."""
        while True:
            if write_error[0] is not None:
                raise DiskWriteError(write_error[0])
            if not writer_thread.is_alive():
                raise DiskWriteError(RuntimeError("yazıcı iş parçacığı beklenmedik biçimde durdu"))
            try:
                write_queue.put(chunk, timeout=0.5)
                return
            except queue.Full:
                continue

    # -- resume meta (.part.meta) ------------------------------------------------
    _META_KEYS = ('filename', 'relative_path', 'filesize', 'mtime_ns', 'sender')

    @staticmethod
    def _meta_path(part_path: str) -> str:
        return part_path + ".meta"

    def _read_meta(self, meta_path: str) -> Optional[dict]:
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _meta_matches(self, stored: Optional[dict], expected: dict) -> bool:
        """Devam için: aynı dosya adı/yol, boyut, kaynak değişiklik zamanı ve gönderici kimliği."""
        if not isinstance(stored, dict) or stored.get('v') != 1:
            return False
        # Değişiklik zamanı doğrulanamıyorsa (gönderici bildirmedi) devam EDİLMEZ
        if not isinstance(expected.get('mtime_ns'), int) or isinstance(expected.get('mtime_ns'), bool):
            return False
        return all(stored.get(key) == expected.get(key) for key in self._META_KEYS)

    def _plan_resume(self, part_path: str, meta_path: str, expected_meta: dict,
                     filesize: int, piece_size: int, use_meta: bool, filename: str):
        """(parça_no, bayt) döndürür. Devam uygun değilse .part ve meta silinip (0, 0) dönülür.

        use_meta=True  (gönderici resume_meta ilan etti): meta eşleşmeden devam edilmez.
        use_meta=False (eski gönderici): eski davranış, yalnızca boyuta bakılır (doğrulanamaz).
        """
        if not os.path.isfile(part_path):
            self._delete_if_exists(meta_path)
            return 0, 0
        existing_size = os.path.getsize(part_path)
        if use_meta:
            if not self._meta_matches(self._read_meta(meta_path), expected_meta):
                self.logger.warning(f"{filename}: .part meta ile eşleşmiyor veya meta yok; baştan başlanıyor")
                resumable = False
            else:
                resumable = 0 < existing_size <= filesize
        else:
            self._delete_if_exists(meta_path)  # eski gönderici doğrulanamaz; eski meta güvenilmez
            resumable = 0 < existing_size < filesize

        chunk_no = existing_size // piece_size if (resumable and piece_size > 0) else 0
        aligned = chunk_no * piece_size
        if aligned <= 0:
            self._delete_if_exists(part_path)
            self._delete_if_exists(meta_path)
            return 0, 0
        try:
            with open(part_path, "r+b") as pf:
                pf.truncate(aligned)
        except Exception as res_err:
            self.logger.warning(f"Could not align {part_path} for resume: {res_err}")
            self._delete_if_exists(part_path)
            self._delete_if_exists(meta_path)
            return 0, 0
        self.logger.info(f"Resuming {filename} from chunk {chunk_no} ({aligned}/{filesize} bytes)")
        return chunk_no, aligned

    def _await_transfer_complete(self, sock: socket.socket, timeout: float = 60.0):
        """Göndericinin TRANSFER_COMPLETE mesajını bekler: (alındı_mı, checksum)."""
        try:
            sock.settimeout(timeout)
        except OSError:
            pass
        for _ in range(50):  # sızan PAUSE/RESUME/PING mesajlarını atla
            try:
                message = self._receive_message(sock)
            except (socket.timeout, OSError):
                return False, ""
            if not message:
                return False, ""
            msg_type, data = Protocol.parse_message(message)
            if msg_type == MessageType.TRANSFER_COMPLETE:
                return True, str(data.get('checksum') or "")
            if msg_type in (MessageType.PAUSE, MessageType.RESUME, MessageType.PING, MessageType.PONG):
                continue
            return False, ""
        return False, ""

    def _format_receiver_error(self, error: Exception) -> str:
        """Hata mesajlarını doğru ve net kullanıcı mesajlarına çevirir"""
        if isinstance(error, IntegrityError):
            return "Dosya bütünlüğü doğrulanamadı (SHA-256 uyuşmuyor); dosya silindi, lütfen tekrar gönderin."
        if isinstance(error, SenderProtocolError):
            return self._clip(str(error))

        # Önce gerçek errno/winerror (metindeki rakamlar yanlış pozitif verirdi: "32", "5" ...)
        category = classify_os_error(error)
        if isinstance(error, DiskWriteError) and category in (oserr.TIMEOUT, oserr.CONN_RESET, oserr.UNREACHABLE):
            category = None  # ağ kategorileri disk yazma hatasında anlamsız
        known = {
            oserr.DISK_FULL: "Diskte yeterli boş alan yok.",
            oserr.LOCKED: "Dosya başka bir program (veya antivirüs) tarafından kilitlendi.",
            oserr.ACCESS_DENIED: "Erişim engellendi (Yazma yetkisi yok).",
            oserr.INVALID_NAME: "Dosya adı veya yolu bu sistemde geçersiz.",
            oserr.NOT_FOUND: "Hedef klasör bulunamadı veya erişilemiyor.",
            oserr.CONN_RESET: "Ağ bağlantısı koptu (Gönderici bağlantıyı kesti).",
            oserr.TIMEOUT: "Zaman aşımı. Gönderici cihazdan yanıt alınamadı.",
            oserr.UNREACHABLE: "Ağ bağlantısı koptu.",
        }
        if category in known:
            return known[category]

        msg = str(error)
        lowered = msg.lower()
        if isinstance(error, DiskWriteError):
            return self._clip(f"Diske yazma hatası: {error.original}")
        if "hedef kilitli" in lowered:
            return "Hedef dosya kilitli (başka bir program açık tutuyor olabilir)."
        if "zaman aşımı" in lowered or "timed out" in lowered or "timeout" in lowered:
            return "Zaman aşımı. Gönderici cihazdan yanıt alınamadı."
        if "connection" in lowered or "bağlantı" in lowered:
            return "Ağ bağlantısı koptu."
        return self._clip(f"Dosya alınamadı: {msg}")

    @staticmethod
    def _clip(message: str, limit: int = 200) -> str:
        """Arayüzde taşmasın diye makul üst sınır (eskiden 40 karakterde kesilip anlamsızlaşıyordu)."""
        return message if len(message) <= limit else message[: limit - 1] + "…"

    
    def _is_running_executable(self, path: str) -> bool:
        try:
            if getattr(sys, "frozen", False):
                return fs_key(path) == fs_key(sys.executable)
        except Exception:
            return False
        return False

    def _delete_if_exists(self, path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            self.logger.error(f"Failed to cleanup {path}: {exc}")

    def _claim_final_path(self, filepath: str) -> str:
        """Hedef adı atomik olarak rezerve eder (O_EXCL); var olan dosyayı asla ezmez.

        Ad doluysa "ad (1).uzanti", "ad (2).uzanti"... üretilir. Rezerve edilen boş dosya,
        tamamlanma sırasında os.replace ile .part içeriğiyle değiştirilir.
        """
        directory, name = os.path.split(filepath)
        root, ext = os.path.splitext(name)
        for number in range(0, 10000):
            candidate = filepath if number == 0 else os.path.join(directory, f"{root} ({number}){ext}")
            try:
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
            except FileExistsError:
                continue
            os.close(fd)
            return candidate
        raise Exception("Benzersiz dosya adı üretilemedi (hedef kilitli olabilir)")

    FINALIZE_ATTEMPTS = 15  # antivirüs/indeksleme kaynaklı anlık kilitler için taşıma denemesi

    def _replace_with_retry(self, part_path: str, target: str) -> Optional[OSError]:
        """`os.replace`'i artan beklemelerle dener; başarıda None, yoksa son hatayı döndürür."""
        last_error: Optional[OSError] = None
        for retry in range(self.FINALIZE_ATTEMPTS):
            try:
                os.replace(part_path, target)
                return None
            except OSError as rename_error:
                last_error = rename_error
                if retry < self.FINALIZE_ATTEMPTS - 1:
                    time.sleep(0.15 * (retry + 1))
        return last_error

    def _finalize_part(self, part_path: str, filepath: str) -> str:
        """`.part` dosyasını nihai ada taşır; gerçek yolu döndürür.

        Üzerine yazma açıksa var olan dosya atomik olarak değiştirilir; hedef kilitli/salt okunursa
        (ör. Excel'de açık) aktarım başarısız sayılmaz, benzersiz ada ("ad (1).uzanti") kaydedilir.
        """
        if self.config.get('transfer', 'overwrite_existing', True) and not os.path.isdir(filepath):
            replace_error = self._replace_with_retry(part_path, filepath)  # mevcut dosyanın üzerine atomik yazar
            if replace_error is None:
                return filepath
            self.logger.warning(
                f"Var olan dosyanın üzerine yazılamadı ({replace_error}); benzersiz adla kaydediliyor: {filepath}"
            )
        target = self._claim_final_path(filepath)
        last_error = self._replace_with_retry(part_path, target)
        if last_error is None:
            if target != filepath:
                self.logger.warning(f"Hedef zaten vardı, benzersiz adla kaydedildi: {target}")
            return target
        # Taşıma başarısız: yalnızca _claim_final_path'in rezerve ettiği boş dosyayı geri al
        # (kullanıcının var olan hedef dosyası buraya hiç gelmez)
        try:
            if os.path.isfile(target) and os.path.getsize(target) == 0:
                os.remove(target)
        except OSError:
            pass
        raise Exception(f"Dosya tamamlanamadı (hedef kilitli olabilir): {last_error}") from last_error

    def _sanitize_path(self, base_folder: str, relative_path: Optional[str], filename: str) -> str:
        """Hedef yolu üretir; sonuç HER ZAMAN `base_folder` içinde kalır.

        Windows ayrılmış adları/karakterleri, Linux/macOS NUL/kontrol karakterleri, `..`/mutlak yol,
        sembolik bağ kaçışı ve aşırı uzun adlar `utils.filenames` içinde ele alınır.
        """
        def _warn(reason: str) -> None:
            self.logger.warning(
                f"Directory traversal attempt detected ({reason}): {filename} / {relative_path}. "
                f"Falling back to safe path."
            )

        return resolve_target(base_folder, relative_path, filename, on_fallback=_warn)

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

