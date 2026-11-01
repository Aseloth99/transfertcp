"""Helper functions and utilities"""

from os.path import abspath, join, relpath, getsize
import os
import sys
from os import walk, makedirs, sep
from socket import socket as Socket, AF_INET, SOCK_DGRAM, SOCK_STREAM, gethostname
from hashlib import sha256
from typing import Optional

from .paths import get_application_path, get_user_config_dir, get_user_data_dir, get_asset_path  # noqa: F401


def get_local_ip() -> str:
    """Get the local IP address of this machine"""
    try:
        # Create a socket to find local IP
        s = Socket(AF_INET, SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # Varsayılan rota yok (çevrimdışı Linux/macOS makinesi): ilk gerçek arayüz adresi
        try:
            from . import netif
            candidate = netif.first_private_ipv4(netif.list_ipv4_interfaces())
            if candidate:
                return candidate
        except Exception:
            pass
        return "127.0.0.1"


def get_hostname() -> str:
    """Get the hostname of this machine"""
    try:
        return gethostname()
    except Exception:
        return "Unknown"


def format_bytes(size: int) -> str:
    """Format bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_speed(bytes_per_sec: float) -> str:
    """Format transfer speed in MB/s or KB/s"""
    if bytes_per_sec <= 0:
        return "0 B/s"
    
    # Convert to MB/s
    mb_per_sec = bytes_per_sec / (1024 * 1024)
    
    if mb_per_sec >= 1.0:
        # Show as MB/s with 2 decimal places
        return f"{mb_per_sec:.2f} MB/s"
    else:
        # Show as KB/s
        kb_per_sec = bytes_per_sec / 1024
        return f"{kb_per_sec:.2f} KB/s"


def format_time(seconds: int, lang: Optional[str] = None) -> str:
    """Kalan süreyi etkin dile göre yazar (TR: sn/dk/sa)."""
    from .locales import configured_language, t

    lang = lang or configured_language()
    total = max(0, int(seconds))
    if total < 60:
        return t("eta_seconds", lang).format(n=total)
    if total < 3600:
        return t("eta_minutes", lang).format(m=total // 60, s=total % 60)
    hours = total // 3600
    minutes = (total % 3600) // 60
    return t("eta_hours", lang).format(h=hours, m=minutes)


def format_duration(seconds: float, lang: Optional[str] = None) -> str:
    """Format total elapsed transfer time (e.g. '1.2 sn', '45 sn', '2 dk 15 sn')."""
    from .locales import configured_language
    lang = lang or configured_language()
    is_tr = (lang == "tr")
    if seconds < 0.1:
        return "< 0.1 sn" if is_tr else "< 0.1 s"
    if seconds < 10.0:
        return f"{seconds:.1f} sn" if is_tr else f"{seconds:.1f} s"
    if seconds < 60.0:
        return f"{int(round(seconds))} sn" if is_tr else f"{int(round(seconds))} s"
    total = int(seconds)
    if total < 3600:
        m = total // 60
        s = total % 60
        return f"{m} dk {s} sn" if is_tr else f"{m}m {s}s"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h} sa {m} dk {s} sn" if is_tr else f"{h}h {m}m {s}s"


def calculate_file_hash(filepath: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """Calculate SHA256 hash of a file"""
    try:
        hash_obj = sha256()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                hash_obj.update(data)
        return hash_obj.hexdigest()
    except Exception:
        return None




def ensure_dir(directory: str) -> bool:
    """Ensure directory exists, create if not"""
    try:
        makedirs(directory, exist_ok=True)
        return True
    except Exception:
        return False


def is_port_available(port: int) -> bool:
    """Check if a port is available"""
    try:
        with Socket(AF_INET, SOCK_STREAM) as s:
            s.bind(('', port))
            return True
    except OSError:
        return False


# İşletim sisteminin kendi oluşturduğu klasör süsleme dosyaları: kullanıcının dosyası değil, gönderilmez.
_OS_METADATA_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", ".directory"}


def is_os_metadata_file(full_path: str) -> bool:
    """desktop.ini / Thumbs.db / .DS_Store gibi sistemin yazdığı gizli dosyalar mı?"""
    name = os.path.basename(full_path)
    if name.lower() in _OS_METADATA_NAMES:
        return True
    if sys.platform == "win32":
        try:
            attrs = os.stat(full_path).st_file_attributes  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            return False
        return bool(attrs & 0x2 and attrs & 0x4)  # HIDDEN ve SYSTEM birlikte
    return False


def scan_folder(folder_path: str) -> list:
    """
    Recursively scan folder and return list of all files with their relative paths
    
    Args:
        folder_path: Path to the folder to scan
        
    Returns:
        List of tuples: (full_path, relative_path)
    """
    files = []
    folder_path = abspath(folder_path)
    
    try:
        for root, dirs, filenames in walk(folder_path):
            for filename in filenames:
                full_path = join(root, filename)
                if is_os_metadata_file(full_path):
                    continue
                # Calculate relative path from folder root
                relative_path = relpath(full_path, folder_path)
                # Normalize path separators for cross-platform compatibility. Yalnızca ayırıcısı '\'
                # olan sistemde (Windows): Linux/macOS'ta '\' geçerli bir dosya adı karakteridir ve
                # alt klasöre çevrilmemelidir.
                if sep != '/':
                    relative_path = relative_path.replace(sep, '/')
                files.append((full_path, relative_path))
    except Exception as e:
        # Return empty list on error
        pass
    
    return files


def get_folder_size(folder_path: str) -> int:
    """Calculate total size of all files in a folder"""
    total_size = 0
    try:
        for root, dirs, filenames in walk(folder_path):
            for filename in filenames:
                filepath = join(root, filename)
                if is_os_metadata_file(filepath):
                    continue
                try:
                    total_size += getsize(filepath)
                except (OSError, FileNotFoundError):
                    pass
    except Exception:
        pass
    return total_size
