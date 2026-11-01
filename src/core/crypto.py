"""TLS 1.3 identity, trust store and socket wrapping for TransferTCP."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..utils.fileio import (
    PRIVATE_FILE_MODE,
    atomic_write_bytes,
    atomic_write_json,
    backup_corrupt_file,
    ensure_private_dir,
    restrict_permissions,
)
from ..utils.logger import get_logger
from ..utils.paths import get_user_data_dir
from ..utils.platform_utils import current_platform


CERT_DIRNAME = "certs"
CERT_FILENAME = "identity.crt"
KEY_FILENAME = "identity.key"
TRUST_FILENAME = "trusted_devices.json"

_identity_lock = threading.Lock()
_trust_lock = threading.Lock()
_cached_paths: Optional[Tuple[str, str]] = None
_cached_fingerprint: Optional[str] = None
_cached_hardware_id: Optional[str] = None


class ApprovalRequest:
    """Blocking request sent from the server thread to the UI thread."""

    def __init__(self, device_name: str, ip: str, fingerprint: str):
        self.device_name = device_name
        self.ip = ip
        self.fingerprint = fingerprint
        self.event = threading.Event()
        self.approved = False


def is_encryption_enabled() -> bool:
    try:
        from ..utils.config import get_config
        return bool(get_config().get("advanced", "encryption_enabled", True))
    except Exception:
        return True


def is_accept_from_anyone() -> bool:
    try:
        from ..utils.config import get_config
        return bool(get_config().get("advanced", "accept_from_anyone", False))
    except Exception:
        return False


def _cert_dir() -> str:
    """Kimlik dizini: POSIX'te yalnızca sahibine açık (0700); Windows'ta kullanıcı profili ACL'i yeter."""
    path = os.path.join(get_user_data_dir(), CERT_DIRNAME)
    ensure_private_dir(path)
    return path


def get_identity_paths() -> Tuple[str, str]:
    folder = _cert_dir()
    return os.path.join(folder, CERT_FILENAME), os.path.join(folder, KEY_FILENAME)


def format_fingerprint(fingerprint: str) -> str:
    """Human-readable AA:BB:CC groups from a hex fingerprint."""
    raw = (fingerprint or "").replace(":", "").replace(" ", "").lower()
    if len(raw) < 16:
        return fingerprint or "—"
    groups = [raw[i:i + 2].upper() for i in range(0, min(len(raw), 32), 2)]
    return " ".join(groups)


def _fingerprint_from_der(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def _ensure_cryptography():
    try:
        from cryptography import x509  # noqa: F401
        from cryptography.hazmat.primitives import hashes  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "TLS için 'cryptography' paketi gerekli. pip install cryptography"
        ) from exc


def _generate_identity(cert_path: str, key_path: str) -> None:
    _ensure_cryptography()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "TransferTCP"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TransferTCP"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.SERVER_AUTH,
                ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("transfertcp.local")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    # Atomik yazım (yarım anahtar/sertifika kalmaz) ve POSIX'te anahtar baştan 0600 ile yaratılır:
    # eskiden önce umask'lı (çoğunlukla 0644) yazılıp sonradan chmod ediliyordu (kısa süre herkese açık).
    # Sertifika herkese açık bilgidir (eşlere zaten gönderilir) ama yine de yalnızca sahibine yazılabilir.
    atomic_write_bytes(key_path, key_pem, mode=PRIVATE_FILE_MODE)
    atomic_write_bytes(cert_path, cert_pem, mode=0o644)


def ensure_identity() -> Tuple[str, str]:
    """Create the long-lived device certificate on first use."""
    global _cached_paths
    with _identity_lock:
        if _cached_paths and os.path.isfile(_cached_paths[0]) and os.path.isfile(_cached_paths[1]):
            return _cached_paths
        cert_path, key_path = get_identity_paths()
        if not (os.path.isfile(cert_path) and os.path.isfile(key_path)):
            get_logger().info("Generating TLS identity certificate")
            _generate_identity(cert_path, key_path)
        else:
            # Eski sürümler anahtarı umask'lı izinle yazmış olabilir; POSIX'te 0600'e çek (Windows: no-op)
            restrict_permissions(key_path, PRIVATE_FILE_MODE)
        _cached_paths = (cert_path, key_path)
        return _cached_paths


def _windows_hardware_parts() -> List[str]:
    """Stable PC identifiers used like an anti-cheat hardware ID."""
    parts: List[str] = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            if guid:
                parts.append(f"guid:{guid}")
    except OSError:
        pass
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            ident, _ = winreg.QueryValueEx(key, "Identifier")
            if ident:
                parts.append(f"cpu:{ident}")
    except OSError:
        pass
    try:
        import ctypes
        serial = ctypes.c_ulong()
        ctypes.windll.kernel32.GetVolumeInformationW(
            "C:\\", None, 0, ctypes.byref(serial), None, None, None, 0
        )
        parts.append(f"vol:{serial.value}")
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
            for name in (
                "BaseBoardProduct",
                "BaseBoardManufacturer",
                "SystemProductName",
                "SystemManufacturer",
            ):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        parts.append(f"{name}:{value}")
                except OSError:
                    continue
    except OSError:
        pass
    return parts


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().strip()


def _linux_hardware_parts(read_text=_read_text) -> List[str]:
    """Linux: systemd/dbus makine kimliği (yeniden kurulumda ve ağ değişiminde sabit)."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = read_text(path)
        except OSError:
            continue
        if value:
            return [f"machine-id:{value}"]
    return []


def _macos_hardware_parts(run=None) -> List[str]:
    """macOS: IOPlatformUUID (ioreg; olmazsa `sysctl kern.uuid`)."""
    import re
    import subprocess

    run = run or (lambda argv: subprocess.run(
        argv, capture_output=True, text=True, timeout=5, check=False).stdout or "")
    try:
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]{16,})"',
                          run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]))
        if match:
            return [f"platform-uuid:{match.group(1).upper()}"]
    except Exception:
        pass
    try:
        value = run(["/usr/sbin/sysctl", "-n", "kern.uuid"]).strip()
        if value:
            return [f"platform-uuid:{value.upper()}"]
    except Exception:
        pass
    return []


def _persisted_device_id() -> str:
    """Makine kimliği okunamazsa: kullanıcı veri klasöründe saklanan rastgele kalıcı kimlik.

    (Eski yedek `uuid.getnode()` MAC bulunamayınca her açılışta farklı rastgele değer döndürüp
    güvenilen cihaz eşleşmesini bozabilirdi.)
    """
    import uuid
    folder = get_user_data_dir()
    ensure_private_dir(folder)
    path = os.path.join(folder, "device_id")
    try:
        value = _read_text(path)
        if len(value) >= 16:
            return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    try:
        atomic_write_bytes(path, value.encode("ascii"), mode=PRIVATE_FILE_MODE)
    except OSError:
        pass
    return value


def _fallback_hardware_parts() -> List[str]:
    import platform
    parts = [
        f"node:{platform.node()}",
        f"machine:{platform.machine()}",
        f"device:{_persisted_device_id()}",
    ]
    return [part for part in parts if part.split(":", 1)[-1]]


def get_hardware_id(platform: Optional[str] = None) -> str:
    """SHA-256 of machine hardware identifiers — survives app reinstall.

    Windows: kayıt defteri/CPU/disk/BIOS kimlikleri (DEĞİŞMEDİ; güvenilen cihaz eşleşmeleri korunur).
    Linux: /etc/machine-id. macOS: IOPlatformUUID. Okunamazsa kalıcı rastgele kimlik dosyası.
    """
    global _cached_hardware_id
    if _cached_hardware_id:
        return _cached_hardware_id
    kind = current_platform(platform)
    parts: List[str] = []
    if kind == "windows":
        parts = _windows_hardware_parts() if os.name == "nt" else []
    elif kind == "linux":
        parts = _linux_hardware_parts()
    elif kind == "macos":
        parts = _macos_hardware_parts()
    if not parts:
        parts = _fallback_hardware_parts()
    elif kind != "windows":
        parts = parts + ["app:TransferTCP"]  # ham makine kimliği başka uygulamalarla aynı özet olmasın
    raw = "|".join(parts).encode("utf-8", "replace")
    _cached_hardware_id = hashlib.sha256(raw).hexdigest()
    return _cached_hardware_id


def get_local_fingerprint() -> str:
    """Public device identity shown in trust dialogs (hardware, not TLS cert)."""
    global _cached_fingerprint
    if _cached_fingerprint:
        return _cached_fingerprint
    try:
        _cached_fingerprint = get_hardware_id()
        return _cached_fingerprint
    except Exception:
        pass
    cert_path, _ = ensure_identity()
    with open(cert_path, "rb") as handle:
        pem = handle.read()
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding
        cert = x509.load_pem_x509_certificate(pem)
        der = cert.public_bytes(Encoding.DER)
    except Exception:
        der = pem
    _cached_fingerprint = _fingerprint_from_der(der)
    return _cached_fingerprint


def fingerprint_from_socket(sock) -> Optional[str]:
    """SHA-256 of the peer certificate seen in the TLS handshake."""
    try:
        der = sock.getpeercert(binary_form=True)
    except Exception:
        return None
    if not der:
        return None
    return _fingerprint_from_der(der)


def _make_context(server_side: bool) -> ssl.SSLContext:
    cert_path, key_path = ensure_identity()
    protocol = ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLS_CLIENT
    ctx = ssl.SSLContext(protocol)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return ctx


def wrap_server_socket(sock):
    ctx = _make_context(server_side=True)
    wrapped = ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
    wrapped.settimeout(30)
    wrapped.do_handshake()
    return wrapped


def wrap_client_socket(sock):
    ctx = _make_context(server_side=False)
    wrapped = ctx.wrap_socket(sock, server_side=False, do_handshake_on_connect=False)
    wrapped.settimeout(30)
    wrapped.do_handshake()
    return wrapped


def _trust_path() -> str:
    folder = get_user_data_dir()
    ensure_private_dir(folder)
    return os.path.join(folder, TRUST_FILENAME)


def _load_trust() -> Dict[str, Any]:
    path = _trust_path()
    if not os.path.isfile(path):
        return {"devices": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
            raise ValueError("güven deposu beklenen biçimde değil")
        return data
    except ValueError as corrupt:  # JSONDecodeError / UnicodeDecodeError / biçim hatası
        # Boş liste dönüp sonraki kayıtta bozuk dosyayı sessizce ezmek yerine yedekle
        backup = backup_corrupt_file(path)
        get_logger().error(
            f"Güvenilen cihaz listesi bozuk ({corrupt}); "
            f"{'yedeklendi: ' + backup if backup else 'yedeklenemedi'}"
        )
        return {"devices": []}
    except Exception:
        return {"devices": []}


def _save_trust(data: Dict[str, Any]) -> None:
    # Atomik yazım: tmp + flush + fsync + os.replace (POSIX'te 0600: güvenilen cihaz listesi kişiseldir)
    atomic_write_json(_trust_path(), data, mode=PRIVATE_FILE_MODE)


def list_trusted_devices() -> List[Dict[str, Any]]:
    with _trust_lock:
        return list(_load_trust().get("devices", []))


def find_trusted(fingerprint: str) -> Optional[Dict[str, Any]]:
    if not fingerprint:
        return None
    fp = fingerprint.lower()
    with _trust_lock:
        for device in _load_trust().get("devices", []):
            if str(device.get("fingerprint", "")).lower() == fp:
                return device
    return None


def find_trusted_by_ip(ip: str) -> Optional[Dict[str, Any]]:
    if not ip:
        return None
    with _trust_lock:
        for device in reversed(_load_trust().get("devices", [])):
            if device.get("ip") == ip:
                return device
    return None


def trust_device(fingerprint: str, device_name: str, ip: str) -> None:
    if not fingerprint:
        return
    fp = fingerprint.lower()
    now = datetime.now(timezone.utc).isoformat()
    with _trust_lock:
        data = _load_trust()
        devices = data.setdefault("devices", [])
        for device in devices:
            if str(device.get("fingerprint", "")).lower() == fp:
                device["device_name"] = device_name or device.get("device_name") or "Unknown"
                device["ip"] = ip or device.get("ip") or ""
                device["last_seen"] = now
                _save_trust(data)
                return
        devices.append({
            "fingerprint": fp,
            "device_name": device_name or "Unknown",
            "ip": ip or "",
            "trusted_at": now,
            "last_seen": now,
        })
        _save_trust(data)


def clear_trusted_devices() -> int:
    with _trust_lock:
        data = _load_trust()
        count = len(data.get("devices", []))
        data["devices"] = []
        _save_trust(data)
        return count


def evaluate_peer(fingerprint: str, ip: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Return (status, device):
      ok        — fingerprint already trusted
      mismatch  — this IP was trusted with a different certificate
      unknown   — first time we see this identity
    """
    known = find_trusted(fingerprint)
    if known:
        return "ok", known
    previous = find_trusted_by_ip(ip)
    if previous and previous.get("fingerprint", "").lower() != (fingerprint or "").lower():
        return "mismatch", previous
    return "unknown", None
