"""Test altyapisi: yalitilmis kullanici dizini + loopback (127.0.0.1) sunucu/istemci yardimcilari.

Gercek AppData'ya DOKUNMAZ: APPDATA / LOCALAPPDATA / HOME surec boyunca gecici dizine
yonlendirilir (config, guven deposu, log, veritabani oraya yazilir) ve cikista silinir.
Test modulleri bunu `import support` ile (diger importlardan ONCE) iceri almalidir.

Gercek ag kullanilmaz; yalnizca 127.0.0.1 uzerinde rastgele bos port.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import pathlib
import random
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------------------- sandbox

_ENV_KEYS = ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "HOME", "USERPROFILE")
SANDBOX_ROOT = tempfile.mkdtemp(prefix="transfertcp_test_")
_saved_env = {key: os.environ.get(key) for key in _ENV_KEYS}

os.environ["APPDATA"] = os.path.join(SANDBOX_ROOT, "appdata")
os.environ["LOCALAPPDATA"] = os.path.join(SANDBOX_ROOT, "localappdata")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX_ROOT, "xdg_config")
os.environ["XDG_DATA_HOME"] = os.path.join(SANDBOX_ROOT, "xdg_data")
os.environ["XDG_STATE_HOME"] = os.path.join(SANDBOX_ROOT, "xdg_state")
os.environ["HOME"] = os.path.join(SANDBOX_ROOT, "home")
os.environ["USERPROFILE"] = os.path.join(SANDBOX_ROOT, "home")
for _key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "HOME"):
    os.makedirs(os.environ[_key], exist_ok=True)


def _reset_singletons() -> None:
    import src.utils.config as config_module
    import src.utils.logger as logger_module

    config_module._config_instance = None
    logger_module._logger_instance = None
    try:
        import src.core.crypto as crypto_module
        crypto_module._cached_paths = None
    except Exception:
        pass


_reset_singletons()


# --------------------------------------------------------------------------- gercek kayit defteri korumasi

REGISTRY_WRITE_ATTEMPTS: list = []


def _install_registry_guard() -> None:
    """Hicbir test GERCEK kayit defterine (HKCU Run dahil) yazamaz: yazma girisimi AssertionError verir.

    Kullanicinin gercek "Acilista Baslat" kaydi (HKCU Run TransferTCP) bir test tarafindan sessizce degistirildi
    (kaynaktan calisan uygulama yolu yazildi); bu koruma bunu kokten engeller. Sahte `winreg` modulu enjekte
    eden testler (test_startup.FakeWinreg) etkilenmez: yalnizca gercek modulun yazma islevleri kilitlenir.
    """
    try:
        import winreg
    except ImportError:  # Windows disi
        return
    if getattr(winreg, "_tcp_test_guard", False):
        return
    # yalnizca YAZMA bitleri (KEY_READ'in paylastigi READ_CONTROL 0x20000 bit'i sayilmaz): SET_VALUE, CREATE_SUB_KEY, CREATE_LINK, DELETE
    write_mask = 0x0002 | 0x0004 | 0x0020 | 0x10000

    def refuse(name):
        def blocked(*args, **kwargs):
            REGISTRY_WRITE_ATTEMPTS.append((name, args[:2]))
            raise AssertionError(f"testler gercek kayit defterine yazamaz: winreg.{name}{args[:2]}")
        return blocked

    for name in ("SetValueEx", "SetValue", "DeleteValue", "DeleteKey", "DeleteKeyEx", "CreateKey", "CreateKeyEx"):
        if hasattr(winreg, name):
            setattr(winreg, name, refuse(name))

    real_open = winreg.OpenKey

    def guarded_open(key, sub_key, reserved=0, access=winreg.KEY_READ):
        if access & write_mask:
            REGISTRY_WRITE_ATTEMPTS.append(("OpenKey(write)", (sub_key, access)))
            raise AssertionError(f"testler gercek kayit defterini yazma erisimiyle acamaz: {sub_key!r}")
        return real_open(key, sub_key, reserved, access)

    winreg.OpenKey = guarded_open
    winreg.OpenKeyEx = guarded_open
    winreg._tcp_test_guard = True


_install_registry_guard()


def _cleanup() -> None:
    try:
        import logging
        log = logging.getLogger("TransferTCP")
        for handler in list(log.handlers):
            try:
                handler.close()
            except Exception:
                pass
            log.removeHandler(handler)
    except Exception:
        pass
    for key, value in _saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    shutil.rmtree(SANDBOX_ROOT, ignore_errors=True)


atexit.register(_cleanup)


def fresh_dir(prefix: str = "case") -> str:
    path = os.path.join(SANDBOX_ROOT, f"{prefix}_{uuid.uuid4().hex[:8]}")
    os.makedirs(path, exist_ok=True)
    return path


# --------------------------------------------------------------------------- Qt

_qt_apps: list = []


def qt_app():
    """Surec boyunca tek bir QApplication (offscreen). QWidget testleri bunu kullanmali.

    Bir QCoreApplication (widget'siz) once yaratilirsa sonradan QApplication yaratilamaz;
    bu yuzden Qt kullanan TUM testler `support.qt_app()` uzerinden gider.
    """
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
        _qt_apps.append(app)  # GC edilmesin
    return app


# --------------------------------------------------------------------------- yardimcilar

def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_bytes(size: int, seed: int = 1) -> bytes:
    return random.Random(seed).randbytes(size)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_file(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def wait_until(predicate: Callable[[], bool], timeout: float = 15.0, interval: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# --------------------------------------------------------------------------- guncelleme paketleri

def fake_pe(machine: int = 0x8664, payload: bytes = b"") -> bytes:
    """Gecerli PE basligi olan kucuk sahte exe (self_update mimari/PE denetimini gecer)."""
    head = bytearray(0x80)
    head[:2] = b"MZ"
    head[0x3C:0x40] = (0x80).to_bytes(4, "little")
    return bytes(head) + b"PE\0\0" + machine.to_bytes(2, "little") + payload


def make_zip(entries: Dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buf.getvalue()


# --------------------------------------------------------------------------- guncelleme akisi (sahte Application)

class FakeConfig:
    """`config.get(bolum, anahtar, varsayilan)` / `set` arayuzu; degerler bellekte."""

    def __init__(self, **values):
        self.values = dict(values)

    def get(self, section, key, default=None):
        return self.values.get(key, default)

    def set(self, section, key, value):
        self.values[key] = value


class FakeUpdateDialog:
    """UpdateDialog'un uygulamanin kullandigi yuzeyi: cagrilari kaydeder (gercek pencere acilmaz)."""

    def __init__(self):
        self.calls = []

    def show_downloading_state(self): self.calls.append("downloading")
    def show_download_complete(self): self.calls.append("complete")
    def show_installing_state(self): self.calls.append("installing")
    def show_install_complete(self): self.calls.append("install_complete")
    def show_error(self, message, retry=True): self.calls.append(("error", message, retry))
    def show_notice(self, message): self.calls.append(("notice", message))
    def update_download_progress(self, downloaded, total, speed): self.calls.append(("progress", downloaded, total))
    def raise_(self): self.calls.append("raise")
    def activateWindow(self): self.calls.append("activate")
    def reject(self): self.calls.append("reject")
    def hide(self): self.calls.append("hide")  # _quit_for_update: pencere cikistan once gizlenir (E2E A3 native crash duzeltmesi)
    def deleteLater(self): self.calls.append("deleteLater")  # ...ve yok edilir (yalniz hide() yetmedi)


APP_UPDATE_METHODS = (
    "_main_window_visible", "_update_in_progress", "_declined_version", "_install_unsupported_reason",
    "_stop_auto_update_timer", "_blocked_text", "_update_failed", "_postpone_install_for_transfers",
    "_start_update_download", "_start_installation", "_on_download_complete", "_on_download_failed",
    "_on_install_failed", "_on_install_complete", "_quit_for_update", "_start_silent_update",
    "_notify_silent_failure", "_is_idle_for_update", "_auto_update_enabled", "_try_auto_update",
    "_on_dialog_update_accepted", "_cancel_update_download", "_defer_update", "_on_update_available",
    "_schedule_auto_update", "_open_update_dialog", "show_pending_update",
)


def make_update_app(*, dialog=None, transfers=0, visible=False, minimized=False, pending=True, mandatory=False,
                    checksum="a" * 64, config=None):
    """Sahte `self`: Application'in guncelleme yontemleri GERCEK, bagimliliklari (pencere, tepsi, kurucu, is parcacigi) sahte."""
    import types
    from unittest import mock

    import src.app as app_module

    class _Log:
        def __init__(self):
            self.infos, self.warnings, self.errors = [], [], []

        def info(self, m, *a, **k): self.infos.append(str(m))
        def warning(self, m, *a, **k): self.warnings.append(str(m))
        def error(self, m, *a, **k): self.errors.append(str(m))

    app = types.SimpleNamespace(
        logger=_Log(),
        config=config or FakeConfig(),
        update_dialog=dialog,
        update_installer=types.SimpleNamespace(
            last_verified=True, downloaded_file=None,
            cleanup=mock.Mock(), cancel_download=mock.Mock(),
        ),
        update_checker=types.SimpleNamespace(current_version="1.0.0"),
        window=types.SimpleNamespace(
            isVisible=lambda: visible, isMinimized=lambda: minimized,
            set_update_available=mock.Mock(),
        ),
        tray_icon=mock.Mock(),
        transfer_manager=types.SimpleNamespace(get_active_transfers=lambda: [object()] * transfers),
        _pending_update=(
            {"version": "1.2.3", "download_url": "https://macik.com.tr/x", "file_size": 1000,
             "checksum": checksum, "release_notes": "n", "is_mandatory": mandatory} if pending else None
        ),
        _silent_update=False, _auto_update_timer=None, download_thread=None, install_thread=None,
        _update_phase="idle", _downloading_version=None, _ready_update=None, _quitting_for_update=False,
    )
    for name in APP_UPDATE_METHODS:
        setattr(app, name, types.MethodType(getattr(app_module.Application, name), app))
    app.update_is_idle = app_module.Application.update_is_idle
    return app


# --------------------------------------------------------------------------- loopback ortami

class Loopback:
    """Ayni surecte gercek TCPServer + TCPClient (ayri TransferManager'larla)."""

    def __init__(self, chunk_size: int = 16384, *, accept_anyone: bool = True):
        from src.core.client import TCPClient
        from src.core.server import TCPServer
        from src.core.transfer import TransferManager
        from src.utils.config import get_config
        import src.core.crypto as crypto

        self.root = fresh_dir("loop")
        self.download_dir = os.path.join(self.root, "downloads")
        self.source_dir = os.path.join(self.root, "source")
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.source_dir, exist_ok=True)

        self.config = get_config()
        cfg = self.config.config
        cfg.setdefault("transfer", {})
        cfg.setdefault("advanced", {})
        cfg["transfer"]["download_folder"] = self.download_dir
        cfg["transfer"]["chunk_size"] = chunk_size
        cfg["transfer"]["port"] = free_port()
        cfg["transfer"]["speed_limit"] = 0
        cfg["advanced"]["encryption_enabled"] = False
        cfg["advanced"]["accept_from_anyone"] = accept_anyone

        try:
            crypto.clear_trusted_devices()
        except Exception:
            pass

        self.recv_mgr = TransferManager()
        self.send_mgr = TransferManager()
        self.server = TCPServer(self.recv_mgr)
        self.client = TCPClient(self.send_mgr)
        self.client._retry_delays = ()  # testlerde yeniden deneme beklemesi olmasin

        self._events: Dict[tuple, threading.Event] = {}
        self._events_lock = threading.Lock()
        self.send_mgr.on_complete = lambda t: self._event("send", t.transfer_id).set()
        self.recv_mgr.on_complete = lambda t: self._event("recv", t.transfer_id).set()

    # -- yasam dongusu
    def start(self) -> "Loopback":
        self.server.start()
        if not self.server.running:
            raise RuntimeError("Test sunucusu baslatilamadi")
        return self

    def stop(self) -> None:
        try:
            self.server.stop(join_timeout=0.3)  # bosta bekleyen test baglantilarini uzun bekleme
        except Exception:
            pass

    def __enter__(self) -> "Loopback":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- olaylar
    def _event(self, side: str, transfer_id: str) -> threading.Event:
        with self._events_lock:
            return self._events.setdefault((side, transfer_id), threading.Event())

    def wait_send(self, transfer, timeout: float = 20.0) -> bool:
        return self._event("send", transfer.transfer_id).wait(timeout)

    def wait_recv(self, transfer_id: str, timeout: float = 20.0) -> bool:
        return self._event("recv", transfer_id).wait(timeout)

    def settle(self, timeout: float = 10.0) -> None:
        """Sunucunun tum istemci is parcaciklari bitene kadar bekle."""
        deadline = time.time() + timeout
        for thread in list(self.server.client_threads):
            thread.join(max(0.0, deadline - time.time()))

    # -- gonderim
    def send(self, path: str, relative_path: Optional[str] = None):
        from src.models.transfer import TransferDirection
        transfer = self.send_mgr.create_transfer(
            path, "127.0.0.1", "LoopbackPeer", TransferDirection.SEND,
            relative_path=relative_path,
            device_port=self.server.port,
        )
        self.send_mgr.queue_transfer(transfer)
        self.client.send_file(transfer)
        return transfer

    def recv_transfer(self, transfer_id: str):
        return self.recv_mgr.active_transfers.get(transfer_id)

    def list_downloads(self) -> List[str]:
        found = []
        for base, _dirs, files in os.walk(self.download_dir):
            for name in files:
                found.append(os.path.relpath(os.path.join(base, name), self.download_dir).replace("\\", "/"))
        return sorted(found)


# --------------------------------------------------------------------------- ham protokol istemcisi

class RawPeer:
    """TCPServer'a protokol duzeyinde konusan test istemcisi (eski/bozuk gondericileri taklit eder)."""

    def __init__(self, port: int, *, name: str = "RawPeer", fingerprint: Optional[str] = None):
        from src.core.protocol import Protocol, MessageType
        self.Protocol = Protocol
        self.MessageType = MessageType
        self.name = name
        self.fingerprint = fingerprint or ("ab" * 32)
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.sock.settimeout(10)
        self.ack_data: dict = {}

    # -- dusuk seviye
    def send(self, message: dict) -> None:
        from src.core.netio import send_all
        send_all(self.sock, self.Protocol.encode_message(message))

    def recv(self, timeout: Optional[float] = None):
        """(MessageType | None, data) doner; baglanti kapanmissa (None, {})."""
        from src.core.netio import recv_exact
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            header = recv_exact(self.sock, self.Protocol.HEADER_SIZE)
            if not header:
                return None, {}
            length = int.from_bytes(header, "big")
            body = recv_exact(self.sock, length)
            if not body:
                return None, {}
            message = self.Protocol.decode_message(body)
            return self.Protocol.parse_message(message)
        except (ConnectionError, OSError):
            return None, {}

    def send_raw(self, data: bytes) -> None:
        from src.core.netio import send_all
        send_all(self.sock, data)

    # -- protokol adimlari
    def handshake(self, *, proto=None, features=None, extra: Optional[dict] = None):
        message = self.Protocol.create_handshake(
            self.name, "rawhost", fingerprint=self.fingerprint, supports_encryption=False
        )
        if proto is not None:
            message["data"]["proto"] = proto
        if features is not None:
            message["data"]["features"] = list(features)
        if extra:
            message["data"].update(extra)
        self.send(message)
        msg_type, data = self.recv()
        self.ack_data = data
        return msg_type, data

    def file_info(self, transfer_id: str, filename: str, filesize: int, *,
                  relative_path: Optional[str] = None, checksum: str = "", extra: Optional[dict] = None):
        message = self.Protocol.create_file_info(
            transfer_id, filename, filesize, checksum, relative_path=relative_path
        )
        if extra:
            message["data"].update(extra)
        self.send(message)
        return self.recv()

    def chunk(self, transfer_id: str, index: int, total: int, payload: bytes, *, wait_ack: bool = True):
        self.send(self.Protocol.create_chunk_data(transfer_id, index, total))
        self.send_raw(struct.pack("!I", len(payload)) + payload)
        if wait_ack:
            return self.recv()
        return None

    def complete(self, transfer_id: str, checksum: str = ""):
        self.send(self.Protocol.create_transfer_complete(transfer_id, checksum))
        return self.recv()

    def cancel(self, transfer_id: str) -> None:
        self.send(self.Protocol.create_cancel(transfer_id))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- sahte alici (istemci testleri icin)

class FakeReceiver:
    """Betikli sahte alici: her baglantida `handler(peer)` calisir (RawPeer benzeri sunucu tarafi)."""

    class Conn:
        def __init__(self, sock: socket.socket):
            from src.core.protocol import Protocol
            self.sock = sock
            self.Protocol = Protocol
            self.sock.settimeout(15)

        def send(self, message: dict) -> None:
            from src.core.netio import send_all
            send_all(self.sock, self.Protocol.encode_message(message))

        def recv(self):
            from src.core.netio import recv_exact
            try:
                header = recv_exact(self.sock, self.Protocol.HEADER_SIZE)
                if not header:
                    return None, {}
                body = recv_exact(self.sock, int.from_bytes(header, "big"))
                if not body:
                    return None, {}
                return self.Protocol.parse_message(self.Protocol.decode_message(body))
            except (ConnectionError, OSError):
                return None, {}

        def recv_chunk_payload(self) -> Optional[bytes]:
            from src.core.netio import recv_exact
            size = recv_exact(self.sock, 4)
            if not size:
                return None
            return recv_exact(self.sock, struct.unpack("!I", size)[0])

        def close(self) -> None:
            try:
                self.sock.close()
            except OSError:
                pass

    def __init__(self, handler: Callable[["FakeReceiver.Conn"], None]):
        self.handler = handler
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.connections = 0
        self._running = True
        self.errors: List[BaseException] = []
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            try:
                sock, _addr = self.listener.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock: socket.socket) -> None:
        conn = FakeReceiver.Conn(sock)
        try:
            self.handler(conn)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)
        finally:
            conn.close()

    def stop(self) -> None:
        self._running = False
        try:
            self.listener.close()
        except OSError:
            pass

    def __enter__(self) -> "FakeReceiver":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
