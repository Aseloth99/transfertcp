"""SQLite database management"""

import sqlite3
import os
import threading
from typing import List, Optional, Dict, Any
from .transfer import Transfer, TransferStatus, TransferDirection
from ..utils.logger import get_logger
from ..utils.fileio import ensure_private_dir
from ..utils.paths import get_user_data_dir


class Database:
    """Database manager for transfer history and settings"""
    
    def __init__(self, db_file: str = None):
        """Initialize database"""
        if not db_file:
            data_dir = get_user_data_dir()
            ensure_private_dir(data_dir)  # POSIX: 0700 (geçmiş/cihaz verisi kişiseldir)
            db_file = os.path.join(data_dir, "transfertcp.db")
        self.db_file = db_file
        self.logger = get_logger()
        self.conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables"""
        try:
            with self._lock:
                self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
                try:
                    self.conn.execute("PRAGMA journal_mode=WAL")
                    self.conn.execute("PRAGMA synchronous=NORMAL")
                except Exception:
                    pass
                
                cursor = self.conn.cursor()
                
                # Transfer history table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS transfer_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        transfer_id TEXT UNIQUE NOT NULL,
                        filename TEXT NOT NULL,
                        filepath TEXT,
                        filesize INTEGER NOT NULL,
                        device_ip TEXT NOT NULL,
                        device_name TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        status TEXT NOT NULL,
                        bytes_transferred INTEGER DEFAULT 0,
                        start_time TEXT,
                        end_time TEXT,
                        speed REAL DEFAULT 0,
                        error_message TEXT,
                        checksum TEXT
                    )
                ''')
                
                # Devices table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        hostname TEXT NOT NULL,
                        is_favorite INTEGER DEFAULT 0,
                        custom_name TEXT,
                        last_seen TEXT,
                        UNIQUE(ip, port)
                    )
                ''')
                
                # Create indexes
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_transfer_device 
                    ON transfer_history(device_ip)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_transfer_time 
                    ON transfer_history(start_time)
                ''')
                
                self.conn.commit()
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
    
    def close(self):
        """Close database connection"""
        with self._lock:
            if self.conn:
                self.conn.close()
                self.conn = None
    
    def add_transfer(self, transfer: Transfer):
        """Add transfer to history"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO transfer_history 
                    (transfer_id, filename, filepath, filesize, device_ip, device_name,
                     direction, status, bytes_transferred, start_time, end_time, 
                     speed, error_message, checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    transfer.transfer_id,
                    transfer.filename,
                    transfer.filepath,
                    transfer.filesize,
                    transfer.device_ip,
                    transfer.device_name,
                    transfer.direction.value,
                    transfer.status.value,
                    transfer.bytes_transferred,
                    transfer.start_time.isoformat() if transfer.start_time else None,
                    transfer.end_time.isoformat() if transfer.end_time else None,
                    transfer.speed,
                    transfer.error_message,
                    transfer.checksum
                ))
                self.conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to add transfer to database: {e}")
    
    def update_transfer(self, transfer: Transfer):
        """Update transfer in history"""
        self.add_transfer(transfer)  # Using REPLACE
    
    def get_transfer_history(self, limit: int = 100, 
                           direction: Optional[TransferDirection] = None) -> List[Dict[str, Any]]:
        """Get transfer history"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                
                if direction:
                    cursor.execute('''
                        SELECT * FROM transfer_history 
                        WHERE direction = ?
                        ORDER BY start_time DESC 
                        LIMIT ?
                    ''', (direction.value, limit))
                else:
                    cursor.execute('''
                        SELECT * FROM transfer_history 
                        ORDER BY start_time DESC 
                        LIMIT ?
                    ''', (limit,))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            
        except Exception as e:
            self.logger.error(f"Failed to get transfer history: {e}")
            return []
    
    def get_transfer_stats(self) -> Dict[str, Any]:
        """Get transfer statistics"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                
                # Total sent
                cursor.execute('''
                    SELECT COUNT(*), COALESCE(SUM(filesize), 0) 
                    FROM transfer_history 
                    WHERE direction = ? AND status = ?
                ''', (TransferDirection.OUTGOING.value, TransferStatus.COMPLETED.value))
                sent_count, sent_bytes = cursor.fetchone()
                
                # Total received
                cursor.execute('''
                    SELECT COUNT(*), COALESCE(SUM(filesize), 0) 
                    FROM transfer_history 
                    WHERE direction = ? AND status = ?
                ''', (TransferDirection.INCOMING.value, TransferStatus.COMPLETED.value))
                recv_count, recv_bytes = cursor.fetchone()
                
                # Failed transfers
                cursor.execute('''
                    SELECT COUNT(*) 
                    FROM transfer_history 
                    WHERE status = ?
                ''', (TransferStatus.FAILED.value,))
                failed_count = cursor.fetchone()[0]
                
                return {
                    'sent_count': sent_count,
                    'sent_bytes': sent_bytes,
                    'received_count': recv_count,
                    'received_bytes': recv_bytes,
                    'failed_count': failed_count,
                    'total_transfers': sent_count + recv_count + failed_count
                }
            
        except Exception as e:
            self.logger.error(f"Failed to get transfer stats: {e}")
            return {
                'sent_count': 0, 'sent_bytes': 0,
                'received_count': 0, 'received_bytes': 0,
                'failed_count': 0, 'total_transfers': 0
            }
    
    def search_transfers(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search transfers by filename or device"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute('''
                    SELECT * FROM transfer_history 
                    WHERE filename LIKE ? OR device_name LIKE ?
                    ORDER BY start_time DESC 
                    LIMIT ?
                ''', (f'%{query}%', f'%{query}%', limit))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            
        except Exception as e:
            self.logger.error(f"Failed to search transfers: {e}")
            return []
    
    def clear_history(self, older_than_days: Optional[int] = None):
        """Clear transfer history"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                
                if older_than_days:
                    cursor.execute('''
                        DELETE FROM transfer_history 
                        WHERE start_time < datetime('now', '-' || ? || ' days')
                    ''', (older_than_days,))
                else:
                    cursor.execute('DELETE FROM transfer_history')
                
                self.conn.commit()
            self.logger.info("Transfer history cleared")
            
        except Exception as e:
            self.logger.error(f"Failed to clear history: {e}")
    
    def save_device(self, device_data: Dict[str, Any]):
        """Save device to database"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO devices 
                    (ip, port, name, hostname, is_favorite, custom_name, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    device_data['ip'],
                    device_data['port'],
                    device_data['name'],
                    device_data['hostname'],
                    device_data.get('is_favorite', 0),
                    device_data.get('custom_name'),
                    device_data.get('last_seen')
                ))
                self.conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to save device: {e}")
    
    def get_devices(self) -> List[Dict[str, Any]]:
        """Get all saved devices"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute('SELECT * FROM devices ORDER BY is_favorite DESC, name ASC')
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Failed to get devices: {e}")
            return []
    
    def get_device(self, ip: str, port: int) -> Optional[Dict[str, Any]]:
        """Get a specific device by IP and port"""
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute('SELECT * FROM devices WHERE ip = ? AND port = ?', (ip, port))
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            self.logger.error(f"Failed to get device: {e}")
            return None


# Global database instance
_db_instance = None


def get_database() -> Database:
    """Get the global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
