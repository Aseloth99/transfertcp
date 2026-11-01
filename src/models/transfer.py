"""Transfer model"""

from enum import Enum
from datetime import datetime
from typing import Optional

from ..utils.ports import DEFAULT_TRANSFER_PORT


class TransferStatus(Enum):
    """Transfer status enum"""
    PENDING = "pending"
    CONNECTING = "connecting"
    TRANSFERRING = "transferring"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransferDirection(Enum):
    """Transfer direction enum"""
    SEND = "send"
    RECEIVE = "receive"


class Transfer:
    """Represents a file transfer"""
    
    def __init__(self, transfer_id: str, filepath: str, filename: str,
                 filesize: int, device_ip: str, device_name: str,
                 direction: TransferDirection, relative_path: Optional[str] = None,
                 device_port: Optional[int] = None):
        """
        Initialize transfer
        
        Args:
            transfer_id: Unique transfer ID
            filepath: Full file path
            filename: File name
            filesize: File size in bytes
            device_ip: Remote device IP
            device_name: Remote device name
            direction: Transfer direction (send/receive)
            relative_path: Relative path within folder (for folder transfers)
        """
        self.transfer_id = transfer_id
        self.filepath = filepath
        self.filename = filename
        self.filesize = filesize
        self.device_ip = device_ip
        self.device_name = device_name
        self.device_port = device_port if device_port is not None else DEFAULT_TRANSFER_PORT
        self.direction = direction
        self.relative_path = relative_path  # For folder transfers
        self.folder_name: Optional[str] = None
        self.folder_total: Optional[int] = None
        self.folder_id: Optional[str] = None
        
        self.status = TransferStatus.PENDING
        self.bytes_transferred = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.speed = 0.0  # bytes per second (smoothed)
        self.error_message: Optional[str] = None
        self.checksum: Optional[str] = None
        self.retry_attempt: int = 0
        # Gönderici yuvası (TCPClient._send_semaphore) dolu olduğu için sırada bekliyor mu?
        # Arayüzde "Bekliyor..." yerine açık bir "Sırada (aynı anda en fazla N)" gösterilir.
        self.queued_for_slot: bool = False
        self.queue_limit: int = 0

        # Speed calculation tracking
        self._last_bytes = 0
        self._last_speed_time: Optional[datetime] = None
        self._speed_samples = []  # List of (time, bytes) tuples for speed calculation
        
    @property
    def progress(self) -> float:
        """Get progress percentage (0-100)"""
        if self.filesize == 0:
            return 100.0
        return (self.bytes_transferred / self.filesize) * 100
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time in seconds"""
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.now()
        if isinstance(self.start_time, (int, float)):
            end_val = end.timestamp() if isinstance(end, datetime) else float(end)
            return max(0.0, float(end_val - self.start_time))
        if isinstance(end, (int, float)):
            end = datetime.fromtimestamp(end)
        return max(0.0, (end - self.start_time).total_seconds())
    
    @property
    def estimated_time_remaining(self) -> Optional[int]:
        """Get estimated time remaining in seconds"""
        if self.speed <= 0 or self.bytes_transferred == 0:
            return None
        remaining_bytes = self.filesize - self.bytes_transferred
        return int(remaining_bytes / self.speed)
    
    @property
    def is_active(self) -> bool:
        """Check if transfer is active"""
        return self.status in [
            TransferStatus.PENDING,
            TransferStatus.CONNECTING,
            TransferStatus.TRANSFERRING,
            TransferStatus.PAUSED
        ]
    
    @property
    def is_complete(self) -> bool:
        """Check if transfer is complete"""
        return self.status == TransferStatus.COMPLETED
    
    @property
    def is_failed(self) -> bool:
        """Check if transfer failed"""
        return self.status in [TransferStatus.FAILED, TransferStatus.CANCELLED]
    
    def start(self):
        """Mark transfer as started"""
        self.status = TransferStatus.TRANSFERRING
        if self.start_time is None:
            self.start_time = datetime.now()
    
    def pause(self):
        """Pause transfer"""
        if self.status == TransferStatus.TRANSFERRING:
            self.status = TransferStatus.PAUSED
    
    def resume(self):
        """Resume transfer"""
        if self.status == TransferStatus.PAUSED:
            self.status = TransferStatus.TRANSFERRING
    
    def complete(self):
        """Mark transfer as completed"""
        self.status = TransferStatus.COMPLETED
        self.end_time = datetime.now()
        self.bytes_transferred = self.filesize
    
    def fail(self, error_message: str):
        """Mark transfer as failed"""
        self.status = TransferStatus.FAILED
        self.end_time = datetime.now()
        self.error_message = error_message
    
    def cancel(self):
        """Cancel transfer"""
        self.status = TransferStatus.CANCELLED
        self.end_time = datetime.now()
    
    def update_progress(self, bytes_transferred: int, speed: float):
        """Update transfer progress with speed smoothing"""
        self.bytes_transferred = bytes_transferred
        
        # Use exponential moving average for speed smoothing
        # Alpha = 0.15 provides gentle, smooth speed updates without wild jumps
        alpha = 0.15
        
        if self.speed > 0:
            # Smooth the speed using exponential moving average
            self.speed = (alpha * speed) + ((1 - alpha) * self.speed)
        else:
            # First update, use the speed directly
            self.speed = speed
        
        # Ensure speed is never negative
        if self.speed < 0:
            self.speed = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'transfer_id': self.transfer_id,
            'filepath': self.filepath,
            'filename': self.filename,
            'filesize': self.filesize,
            'device_ip': self.device_ip,
            'device_name': self.device_name,
            'direction': self.direction.value,
            'status': self.status.value,
            'bytes_transferred': self.bytes_transferred,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'speed': self.speed,
            'error_message': self.error_message,
            'checksum': self.checksum
        }

