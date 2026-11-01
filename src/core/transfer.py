"""Transfer manager - handles file transfer operations"""

import os
import threading
from queue import Queue, Empty
from typing import Dict, Optional, Callable, List
import uuid

from ..models.transfer import Transfer, TransferStatus, TransferDirection
from ..utils.logger import get_logger
from ..utils.helpers import calculate_file_hash


class TransferManager:
    """Manages file transfers with queue and progress tracking"""
    
    def __init__(self, max_concurrent: int = 3):
        """
        Initialize transfer manager
        
        Args:
            max_concurrent: Maximum concurrent transfers
        """
        self.max_concurrent = max_concurrent
        self.logger = get_logger()
        
        # Transfer storage. active_transfers GUI, sunucu ve istemci thread'lerinden erişilir;
        # dolaşma/değiştirme _lock altında yapılır (aksi halde "dictionary changed size during iteration").
        self.active_transfers: Dict[str, Transfer] = {}
        self._lock = threading.RLock()
        self.transfer_queue: Queue = Queue()
        
        # Thread control
        self.worker_threads = []
        self.running = False
        
        # Callbacks
        self.on_progress: Optional[Callable] = None
        self.on_complete: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        
        # Statistics
        self.total_bytes_sent = 0
        self.total_bytes_received = 0
    
    def start(self):
        """Start transfer manager"""
        if self.running:
            return
        
        self.running = True
        
        # Start worker threads
        for i in range(self.max_concurrent):
            thread = threading.Thread(target=self._worker, daemon=True)
            thread.start()
            self.worker_threads.append(thread)
        
        self.logger.info(f"Transfer manager started with {self.max_concurrent} workers")
    
    def stop(self):
        """Stop transfer manager"""
        self.running = False
        
        # Wait for workers to finish
        for thread in self.worker_threads:
            thread.join(timeout=2)
        
        self.worker_threads.clear()
        self.logger.info("Transfer manager stopped")
    
    def create_transfer(self, filepath: str, device_ip: str, device_name: str,
                       direction: TransferDirection, relative_path: Optional[str] = None,
                       device_port: Optional[int] = None) -> Optional[Transfer]:
        """
        Create a new transfer
        
        Args:
            filepath: Path to file
            device_ip: Target device IP
            device_name: Target device name
            direction: Transfer direction
            relative_path: Relative path within folder (for folder transfers)
            
        Returns:
            Transfer object or None if file doesn't exist
        """
        if direction == TransferDirection.SEND and not os.path.exists(filepath):
            self.logger.error(f"File not found: {filepath}")
            return None
        
        # Generate unique transfer ID
        transfer_id = str(uuid.uuid4())
        
        # Get file info
        filename = os.path.basename(filepath)
        if direction == TransferDirection.SEND:
            filesize = os.path.getsize(filepath)
        else:
            filesize = 0  # Will be set when receiving file info
        
        # Create transfer object
        transfer = Transfer(
            transfer_id=transfer_id,
            filepath=filepath,
            filename=filename,
            filesize=filesize,
            device_ip=device_ip,
            device_name=device_name,
            direction=direction,
            relative_path=relative_path,
            device_port=device_port,
        )
        
        return transfer
    
    def queue_transfer(self, transfer: Transfer):
        """Add transfer to queue"""
        self.register_transfer(transfer)
        self.transfer_queue.put(transfer)
        self.logger.info(f"Transfer queued: {transfer.filename}")

    def register_transfer(self, transfer: Transfer) -> Optional[Transfer]:
        """Transferi kayda ekler; aynı kimlikli eski (bayat) kayıt varsa onu döndürür."""
        with self._lock:
            previous = self.active_transfers.get(transfer.transfer_id)
            self.active_transfers[transfer.transfer_id] = transfer
            return previous

    def unregister_transfer(self, transfer_id: str) -> Optional[Transfer]:
        with self._lock:
            return self.active_transfers.pop(transfer_id, None)

    def snapshot_transfers(self) -> List[Transfer]:
        """Kilit altında alınmış güvenli kopya (dolaşırken sözlük değişse de hata vermez)."""
        with self._lock:
            return list(self.active_transfers.values())

    def pause_transfer(self, transfer_id: str) -> bool:
        """Pause a transfer"""
        transfer = self.get_transfer(transfer_id)
        if transfer:
            transfer.pause()
            self.logger.info(f"Transfer paused: {transfer.filename}")
            return True
        return False

    def resume_transfer(self, transfer_id: str) -> bool:
        """Resume a transfer"""
        transfer = self.get_transfer(transfer_id)
        if transfer:
            transfer.resume()
            # Re-queue the transfer
            self.transfer_queue.put(transfer)
            self.logger.info(f"Transfer resumed: {transfer.filename}")
            return True
        return False

    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a transfer"""
        transfer = self.get_transfer(transfer_id)
        if transfer:
            transfer.cancel()
            self.logger.info(f"Transfer cancelled: {transfer.filename}")

            if self.on_complete:
                self.on_complete(transfer)

            return True
        return False

    def get_transfer(self, transfer_id: str) -> Optional[Transfer]:
        """Get transfer by ID"""
        with self._lock:
            return self.active_transfers.get(transfer_id)

    def get_active_transfers(self) -> List[Transfer]:
        """Get all active transfers"""
        return [t for t in self.snapshot_transfers() if t.is_active]
    
    def get_queue_size(self) -> int:
        """Get number of transfers in queue"""
        return self.transfer_queue.qsize()
    
    def _worker(self):
        """Worker thread for processing transfers (currently not used - handled by client/server)"""
        while self.running:
            try:
                # Get transfer from queue (with timeout)
                transfer = self.transfer_queue.get(timeout=1)
                
                # Check if transfer is cancelled or paused
                if transfer.status in [TransferStatus.CANCELLED, TransferStatus.PAUSED]:
                    continue
                
            except Empty:
                continue
            except Exception as e:
                self.logger.exception(f"Worker error: {e}")
    
    def update_progress(self, transfer_id: str, bytes_transferred: int, speed: float):
        """Update transfer progress"""
        transfer = self.get_transfer(transfer_id)
        if transfer:
            transfer.update_progress(bytes_transferred, speed)
            
            # Call progress callback
            if self.on_progress:
                self.on_progress(transfer)
    
    def complete_transfer(self, transfer_id: str, success: bool = True, 
                         error_message: Optional[str] = None):
        """Mark transfer as complete"""
        transfer = self.get_transfer(transfer_id)
        if not transfer:
            return
        
        if success:
            transfer.complete()
            self.logger.info(f"Transfer completed: {transfer.filename}")
            
            # Update statistics
            if transfer.direction == TransferDirection.SEND:
                self.total_bytes_sent += transfer.filesize
            else:
                self.total_bytes_received += transfer.filesize
        else:
            if transfer.status != TransferStatus.CANCELLED:
                transfer.fail(error_message or "Bilinmeyen hata")
                self.logger.error(f"Transfer failed: {transfer.filename} - {error_message}")
            else:
                self.logger.info(f"Transfer cancelled: {transfer.filename} - {error_message}")
        
        # Call completion callback
        if self.on_complete:
            self.on_complete(transfer)
    
    def calculate_checksum(self, filepath: str, chunk_size: int) -> Optional[str]:
        """Calculate file checksum"""
        return calculate_file_hash(filepath, chunk_size)
    
    def get_statistics(self) -> Dict[str, int]:
        """Get transfer statistics"""
        return {
            'total_sent': self.total_bytes_sent,
            'total_received': self.total_bytes_received,
            'active_transfers': len(self.get_active_transfers()),
            'queued_transfers': self.get_queue_size()
        }

