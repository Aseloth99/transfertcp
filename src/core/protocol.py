"""Network protocol definitions"""

import json
from enum import Enum
from typing import Dict, Any, Optional, Tuple


class MessageType(Enum):
    """Message types for protocol"""
    # Discovery
    DISCOVER = "discover"
    DISCOVER_RESPONSE = "discover_response"
    GOODBYE = "goodbye"
    
    # Connection
    HANDSHAKE = "handshake"
    HANDSHAKE_ACK = "handshake_ack"
    HANDSHAKE_REJECT = "handshake_reject"
    
    # Transfer
    FILE_INFO = "file_info"
    FILE_INFO_ACK = "file_info_ack"
    FILE_INFO_REJECT = "file_info_reject"
    CHUNK_DATA = "chunk_data"
    CHUNK_ACK = "chunk_ack"
    
    # Control
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    
    # Status
    TRANSFER_COMPLETE = "transfer_complete"
    TRANSFER_COMPLETE_ACK = "transfer_complete_ack"
    TRANSFER_ERROR = "transfer_error"
    
    # Heartbeat
    PING = "ping"
    PONG = "pong"


class Protocol:
    """Protocol handler for network messages"""

    # Mesaj zarfının (envelope) biçim sürümü; bu değer eski sürümlerle aynıdır ve
    # DEĞİŞMEZ. Yalnızca ana sürüm (1) uyumluluk için denetlenir (is_compatible_version).
    VERSION = "1.0"
    HEADER_SIZE = 8  # Size of length prefix in bytes

    # Yetenek anlaşması (handshake'te `proto` + `features`). Eski sürümler bu alanları
    # göndermez/yok sayar; karşı taraf ilan etmedikçe yeni davranışlar ETKİNLEŞMEZ.
    PROTO_VERSION = 2
    FEATURE_COMPLETE_ACK = "complete_ack"    # TRANSFER_COMPLETE_ACK/ERROR zorunlu, ACK yoksa başarı sayılmaz
    FEATURE_SHA256 = "sha256"                # akış SHA-256 özeti TRANSFER_COMPLETE içinde, alıcı doğrular
    FEATURE_RESUME_META = "resume_meta"      # .part yanında meta; devam etmeden önce eşleşme doğrulanır
    LOCAL_FEATURES = (FEATURE_COMPLETE_ACK, FEATURE_SHA256, FEATURE_RESUME_META)

    @staticmethod
    def negotiate_features(remote_data: Any) -> frozenset:
        """Karşı tarafın handshake verisinden ortak (etkin) özellik kümesini çıkarır.

        `proto` < 2 veya `features` yoksa/geçersizse boş küme döner (eski davranış).
        """
        if not isinstance(remote_data, dict):
            return frozenset()
        proto = remote_data.get('proto')
        features = remote_data.get('features')
        if isinstance(proto, bool) or not isinstance(proto, int) or proto < 2:
            return frozenset()
        if not isinstance(features, (list, tuple)):
            return frozenset()
        offered = {item for item in features if isinstance(item, str)}
        return frozenset(offered & set(Protocol.LOCAL_FEATURES))

    @staticmethod
    def is_compatible_version(message: Any) -> bool:
        """Zarf sürümünün ana numarası uyumlu mu (eksikse eski sürüm sayılır, uyumlu)."""
        if not isinstance(message, dict):
            return False
        version = message.get('version')
        if version is None:
            return True
        major = str(version).split('.', 1)[0]
        return major == Protocol.VERSION.split('.', 1)[0]

    @staticmethod
    def create_message(msg_type: MessageType, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a protocol message"""
        return {
            'version': Protocol.VERSION,
            'type': msg_type.value,
            'data': data
        }
    
    @staticmethod
    def encode_message(message: Dict[str, Any]) -> bytes:
        """Encode message to bytes with length prefix"""
        json_str = json.dumps(message)
        json_bytes = json_str.encode('utf-8')
        length = len(json_bytes)
        # Prefix with 8-byte length
        length_prefix = length.to_bytes(Protocol.HEADER_SIZE, byteorder='big')
        return length_prefix + json_bytes
    
    @staticmethod
    def decode_message(data: bytes) -> Optional[Dict[str, Any]]:
        """Decode message from bytes"""
        try:
            json_str = data.decode('utf-8')
            return json.loads(json_str)
        except Exception:
            return None
    
    @staticmethod
    def create_discover_message(device_name: str, hostname: str, 
                               port: int, instance_id: Optional[str] = None,
                               fingerprint: Optional[str] = None,
                               discovery_port: Optional[int] = None) -> Dict[str, Any]:
        """Create discovery broadcast message"""
        data: Dict[str, Any] = {
            'device_name': device_name,
            'hostname': hostname,
            'port': port
        }
        if instance_id:
            data['instance_id'] = instance_id
        if fingerprint:
            data['fingerprint'] = fingerprint
        if discovery_port:
            data['discovery_port'] = discovery_port
        return Protocol.create_message(MessageType.DISCOVER, data)
    
    @staticmethod
    def create_discover_response(device_name: str, hostname: str,
                                 port: int, instance_id: Optional[str] = None,
                                 fingerprint: Optional[str] = None,
                                 discovery_port: Optional[int] = None) -> Dict[str, Any]:
        """Create discovery response message"""
        data: Dict[str, Any] = {
            'device_name': device_name,
            'hostname': hostname,
            'port': port
        }
        if instance_id:
            data['instance_id'] = instance_id
        if fingerprint:
            data['fingerprint'] = fingerprint
        if discovery_port:
            data['discovery_port'] = discovery_port
        return Protocol.create_message(MessageType.DISCOVER_RESPONSE, data)
    
    @staticmethod
    def create_goodbye_message(device_name: str, hostname: str,
                               port: int, instance_id: Optional[str] = None) -> Dict[str, Any]:
        """Create goodbye broadcast message when application closes"""
        data: Dict[str, Any] = {
            'device_name': device_name,
            'hostname': hostname,
            'port': port
        }
        if instance_id:
            data['instance_id'] = instance_id
        return Protocol.create_message(MessageType.GOODBYE, data)
    
    @staticmethod
    def create_handshake(device_name: str, hostname: str,
                         fingerprint: Optional[str] = None,
                         supports_encryption: bool = False,
                         proto: Optional[int] = None,
                         features: Optional[Any] = None) -> Dict[str, Any]:
        """Create handshake message (proto/features: yetenek ilanı; None = eski biçim)"""
        data: Dict[str, Any] = {
            'device_name': device_name,
            'hostname': hostname,
            'supports_encryption': supports_encryption
        }
        if fingerprint:
            data['fingerprint'] = fingerprint
        if proto is not None:
            data['proto'] = proto
            data['features'] = list(features or ())
        return Protocol.create_message(MessageType.HANDSHAKE, data)

    @staticmethod
    def create_handshake_ack(fingerprint: Optional[str] = None,
                             supports_encryption: bool = False,
                             proto: Optional[int] = None,
                             features: Optional[Any] = None) -> Dict[str, Any]:
        """Create handshake acknowledgment (proto/features: yetenek ilanı)"""
        data: Dict[str, Any] = {
            'supports_encryption': supports_encryption
        }
        if fingerprint:
            data['fingerprint'] = fingerprint
        if proto is not None:
            data['proto'] = proto
            data['features'] = list(features or ())
        return Protocol.create_message(MessageType.HANDSHAKE_ACK, data)

    @staticmethod
    def create_handshake_reject(reason: str) -> Dict[str, Any]:
        """Create handshake rejection"""
        return Protocol.create_message(MessageType.HANDSHAKE_REJECT, {
            'reason': reason
        })
    
    @staticmethod
    def create_file_info(transfer_id: str, filename: str, filesize: int,
                        checksum: str, is_folder: bool = False, 
                        relative_path: Optional[str] = None,
                        folder_name: Optional[str] = None,
                        folder_total: Optional[int] = None,
                        folder_id: Optional[str] = None,
                        mtime_ns: Optional[int] = None) -> Dict[str, Any]:
        """Create file info message (mtime_ns: kaynak dosyanın değişiklik zamanı, resume doğrulaması)"""
        data = {
            'transfer_id': transfer_id,
            'filename': filename,
            'filesize': filesize,
            'checksum': checksum,
            'is_folder': is_folder
        }
        if mtime_ns is not None:
            data['mtime_ns'] = mtime_ns
        if relative_path:
            data['relative_path'] = relative_path
        if folder_name:
            data['folder_name'] = folder_name
        if folder_total is not None:
            data['folder_total'] = folder_total
        if folder_id:
            data['folder_id'] = folder_id
        return Protocol.create_message(MessageType.FILE_INFO, data)
    
    @staticmethod
    def create_file_info_ack(transfer_id: str, success: bool = True,
                            resumed_from_chunk: int = 0,
                            resumed_bytes: int = 0) -> Dict[str, Any]:
        """Create file info acknowledgment with optional resume support"""
        data = {
            'transfer_id': transfer_id,
            'success': success,
        }
        if resumed_from_chunk > 0 or resumed_bytes > 0:
            data['resumed_from_chunk'] = resumed_from_chunk
            data['resumed_bytes'] = resumed_bytes
        return Protocol.create_message(MessageType.FILE_INFO_ACK, data)

    
    @staticmethod
    def create_file_info_reject(transfer_id: str, reason: str) -> Dict[str, Any]:
        """Create file info rejection"""
        return Protocol.create_message(MessageType.FILE_INFO_REJECT, {
            'transfer_id': transfer_id,
            'reason': reason
        })
    
    @staticmethod
    def create_chunk_data(transfer_id: str, chunk_index: int, 
                         total_chunks: int) -> Dict[str, Any]:
        """Create chunk data header (actual data sent separately)"""
        return Protocol.create_message(MessageType.CHUNK_DATA, {
            'transfer_id': transfer_id,
            'chunk_index': chunk_index,
            'total_chunks': total_chunks
        })
    
    @staticmethod
    def create_chunk_ack(transfer_id: str, chunk_index: int) -> Dict[str, Any]:
        """Create chunk acknowledgment"""
        return Protocol.create_message(MessageType.CHUNK_ACK, {
            'transfer_id': transfer_id,
            'chunk_index': chunk_index
        })
    
    @staticmethod
    def create_pause(transfer_id: str) -> Dict[str, Any]:
        """Create pause message"""
        return Protocol.create_message(MessageType.PAUSE, {
            'transfer_id': transfer_id
        })
    
    @staticmethod
    def create_resume(transfer_id: str, from_chunk: int) -> Dict[str, Any]:
        """Create resume message"""
        return Protocol.create_message(MessageType.RESUME, {
            'transfer_id': transfer_id,
            'from_chunk': from_chunk
        })
    
    @staticmethod
    def create_cancel(transfer_id: str) -> Dict[str, Any]:
        """Create cancel message"""
        return Protocol.create_message(MessageType.CANCEL, {
            'transfer_id': transfer_id
        })
    
    @staticmethod
    def create_transfer_complete(transfer_id: str, checksum: str) -> Dict[str, Any]:
        """Create transfer complete message"""
        return Protocol.create_message(MessageType.TRANSFER_COMPLETE, {
            'transfer_id': transfer_id,
            'checksum': checksum
        })

    @staticmethod
    def create_transfer_complete_ack(transfer_id: str, success: bool = True,
                                     error: Optional[str] = None) -> Dict[str, Any]:
        """Create transfer complete acknowledgment (error: success=False ise alıcı mesajı)"""
        data: Dict[str, Any] = {
            'transfer_id': transfer_id,
            'success': success
        }
        if error:
            data['error'] = error
        return Protocol.create_message(MessageType.TRANSFER_COMPLETE_ACK, data)
    
    @staticmethod
    def create_transfer_error(transfer_id: str, error: str) -> Dict[str, Any]:
        """Create transfer error message"""
        return Protocol.create_message(MessageType.TRANSFER_ERROR, {
            'transfer_id': transfer_id,
            'error': error
        })
    
    @staticmethod
    def create_ping() -> Dict[str, Any]:
        """Create ping message"""
        return Protocol.create_message(MessageType.PING, {})
    
    @staticmethod
    def create_pong() -> Dict[str, Any]:
        """Create pong message"""
        return Protocol.create_message(MessageType.PONG, {})
    
    @staticmethod
    def parse_message(message: Dict[str, Any]) -> Tuple[Optional[MessageType], Dict[str, Any]]:
        """Parse a message and return type and data"""
        if not isinstance(message, dict):
            return None, {}
        try:
            msg_type_str = message.get('type')
            msg_type = MessageType(msg_type_str)
            data = message.get('data', {})
            if not isinstance(data, dict):
                return None, {}
            return msg_type, data
        except (ValueError, KeyError, TypeError):
            return None, {}

