"""Device model"""

from datetime import datetime
from typing import Optional


class Device:
    """Represents a network device"""
    
    def __init__(self, ip: str, port: int, name: str, hostname: str):
        """
        Initialize device
        
        Args:
            ip: IP address
            port: Port number
            name: Device name (user-defined)
            hostname: System hostname
        """
        self.ip = ip
        self.port = port
        self.name = name
        self.hostname = hostname
        self.is_online = True
        self.last_seen = datetime.now()
        self.is_favorite = False
        self.custom_name: Optional[str] = None
        self.is_manual = False
        
    def __str__(self) -> str:
        """String representation"""
        display_name = self.custom_name or self.name
        return f"{display_name} ({self.ip})"
    
    def __eq__(self, other) -> bool:
        """Check equality based on IP and port"""
        if not isinstance(other, Device):
            return False
        return self.ip == other.ip and self.port == other.port
    
    def __hash__(self) -> int:
        """Hash based on IP and port"""
        return hash((self.ip, self.port))
    
    @property
    def display_name(self) -> str:
        """Get display name"""
        return self.custom_name or self.name
    
    @property
    def full_address(self) -> str:
        """Get full address (IP:port)"""
        return f"{self.ip}:{self.port}"
    
    def update_last_seen(self):
        """Update last seen timestamp"""
        self.last_seen = datetime.now()
        self.is_online = True
    
    def mark_offline(self):
        """Mark device as offline"""
        self.is_online = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'ip': self.ip,
            'port': self.port,
            'name': self.name,
            'hostname': self.hostname,
            'is_online': self.is_online,
            'last_seen': self.last_seen.isoformat(),
            'is_favorite': self.is_favorite,
            'custom_name': self.custom_name,
            'is_manual': self.is_manual
        }
    
    @staticmethod
    def from_dict(data: dict) -> 'Device':
        """Create device from dictionary"""
        device = Device(
            ip=data['ip'],
            port=data['port'],
            name=data['name'],
            hostname=data['hostname']
        )
        device.is_online = data.get('is_online', True)
        if 'last_seen' in data:
            device.last_seen = datetime.fromisoformat(data['last_seen'])
        device.is_favorite = data.get('is_favorite', False)
        device.custom_name = data.get('custom_name')
        device.is_manual = data.get('is_manual', False)
        return device

