"""TransferTCP"""

from sys import argv, exit
import sys
import os
from os.path import exists
from PyQt6.QtWidgets import QApplication

from src.app import Application
from src.utils.helpers import get_application_path, get_asset_path


def _install_shutdown_hook(app, transfer_app) -> None:
    """Normal çıkışta (tepsi menüsü -> QApplication.quit()) kapanış adımlarını çalıştırır.

    Önceden yalnızca güncelleme yeniden başlatması stop() çağırıyordu; tepsiden çıkışta
    GOODBYE yayını, TCP sunucusunu kapatma ve veritabanı kapatma hiç çalışmıyordu.
    """
    app.aboutToQuit.connect(transfer_app.stop)


def _setup_dpi():
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
            except Exception:
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _set_app_id():
    if sys.platform == "win32":
        try:
            import ctypes
            set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            set_app_id.argtypes = [ctypes.c_wchar_p]
            set_app_id.restype = ctypes.HRESULT
            set_app_id("TransferTCP.App")
        except Exception:
            pass


def _try_raise_existing(socket_name: str) -> bool:
    from PyQt6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(socket_name)
    if sock.waitForConnected(300):
        sock.write(b"raise")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _wait_for_previous_instance() -> None:
    """Güncelleme sonrası açılış (kilit alınmadan ÖNCE): `--wait-pid N` verildiyse güncellemeyi başlatan eski süreç
    çıkana dek (en çok 15 sn) bekler; tek kopya kilidi ve tepsi simgesi çakışmasın. Hata açılışı engellemez."""
    try:
        from src.utils import self_update as su
        su.wait_for_previous_instance(argv)
    except Exception:
        pass


def _startup_guard(lock) -> bool:
    """Paketlenmişse sürüm koruması: güncellemeden sonraki ilk açılışlar "deneme"dir; yeni sürüm iki kez açılışta
    ölürse eski exe geri gelir (ROLLED_BACK) ve bu süreç hemen çıkmalıdır (False döner); geri gelen sürüm tepside
    başlatılır. Tek kopya kilidi alındıktan SONRA çağrılır: kilide takılıp çıkan ikinci başlatmalar (çift tıklama)
    "açılış" sayılıp ÇALIŞAN yeni sürümü geri aldırmasın. Hiçbir hata uygulamanın açılmasını engellemez."""
    try:
        if not getattr(sys, "frozen", False):
            return True
        from src.utils import self_update as su
        from src.utils.updater import UpdateChecker
        if su.startup_guard(sys.executable, UpdateChecker.CURRENT_VERSION) == su.Guard.ROLLED_BACK:
            try:
                lock.unlock()  # geri gelen sürüm kilidi alabilsin
            except Exception:
                pass
            try:
                su.spawn(sys.executable, ["--minimized"])
            except Exception:
                pass
            return False
    except Exception:
        pass
    return True


def _acquire_lock(lock, patient: bool) -> bool:
    """Tek kopya kilidini al. `patient` (güncelleme yeniden başlatması): eski süreç kapanışını bitirirken kilit kısa
    süre daha tutulabilir; "zaten çalışıyor" deyip çıkmadan önce birkaç saniye yeniden denenir."""
    if lock.tryLock(100):
        return True
    if patient:
        import time
        for _ in range(40):  # en çok ~10 sn
            time.sleep(0.25)
            if lock.tryLock(100):
                return True
    return False


def _suppress_startup_console():
    """Otomatik başlatmada python.exe ile açılan CMD penceresini gizle."""
    if sys.platform != "win32" or "--minimized" not in argv:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def main():
    """Main entry point"""
    _suppress_startup_console()
    from src.utils.crashlog import install_crash_log
    install_crash_log()

    # Kaynak dosyalar (assets) göreli yoldan bulunsun; ayarlar kullanıcı dizinine yazılır.
    # Startup'tan gelince CWD System32 olabiliyor.
    app_path = get_application_path()
    os.chdir(app_path)

    _wait_for_previous_instance()

    _setup_dpi()
    _set_app_id()

    from PyQt6.QtCore import Qt, QLockFile
    from PyQt6.QtNetwork import QLocalServer
    import tempfile

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    SOCKET_NAME = "TransferTCP.SingleInstanceServer"
    LOCK_NAME = "TransferTCP.single.lock"
    lock_path = os.path.join(tempfile.gettempdir(), LOCK_NAME)
    lock = QLockFile(lock_path)
    lock.setStaleLockTime(10000)
    if not _acquire_lock(lock, Application._is_update_restart(argv)):
        if _try_raise_existing(SOCKET_NAME):
            return 0
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            pass
        lock = QLockFile(lock_path)
        if not lock.tryLock(100):
            lock.removeStaleLockFile()
            if not lock.tryLock(100):
                # Başka bir kopya çalışıyor ama öne alınamadı: "zaten çalışıyor" kutusu AÇILMAZ, sessizce çıkılır
                # (FlexiKey/MediaCompressor ile aynı); tepsideki kopya kullanıcının tek kopyasıdır.
                return 0

    # Kilit bizde: güncellemeden sonra yeni sürüm açılışta ölüyorsa eski sürümü geri getir (bu süreç çıkar)
    if not _startup_guard(lock):
        return 0

    # Create QApplication
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("TransferTCP")
    app.setOrganizationName("TransferTCP")
    for effect in (
        Qt.UIEffect.UI_AnimateCombo,
        Qt.UIEffect.UI_AnimateMenu,
        Qt.UIEffect.UI_FadeMenu,
        Qt.UIEffect.UI_AnimateTooltip,
    ):
        app.setEffectEnabled(effect, False)

    # Set application icon
    from PyQt6.QtGui import QIcon
    icon_path = get_asset_path("icons", "app_icon.png")
    if exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Single instance local server
    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    server.listen(SOCKET_NAME)

    # Create and start application
    transfer_app = Application()

    def _on_incoming_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.disconnected.connect(conn.deleteLater)
            conn.readyRead.connect(lambda: transfer_app._show_window())
            transfer_app._show_window()

    server.newConnection.connect(_on_incoming_connection)

    _install_shutdown_hook(app, transfer_app)
    transfer_app.start()

    # Run event loop
    try:
        code = app.exec()
    finally:
        transfer_app.stop()  # idempotent: aboutToQuit zaten çağırdıysa bir şey yapmaz
    lock.unlock()
    server.close()
    transfer_app.teardown_qt_objects()  # GUI nesneleri Python sonlandırmasından ÖNCE, sabit sırayla (rastgele yıkım sırası çökertiyordu)
    return code


if __name__ == "__main__":
    exit(main())
