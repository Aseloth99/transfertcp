"""TransferTCP uygulama denetleyicisi: çekirdek bileşenleri (sunucu, istemci, keşif) ve arayüzü bağlar."""

from sys import exit
import sys
import time
from os.path import exists, basename, isdir
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication, QObject, Qt, pyqtSignal, QTimer

from src.gui.main_window import MainWindow
from src.gui.tray_icon import TrayIcon
from src.gui.toast import SystemToast
from src.gui.palette import install_message_box
from src.core.server import TCPServer
from src.core.client import TCPClient
from src.core.discovery import NetworkDiscovery
from src.core.transfer import TransferManager
from src.models.device import Device
from src.models.transfer import Transfer, TransferDirection, TransferStatus
from src.models.database import get_database
from src.utils.config import get_config
from src.utils.logger import get_logger
from src.utils.helpers import get_hostname
from src.utils.paths import get_default_download_dir
from src.utils.updater import UpdateChecker
from src.utils import self_update
from src.utils.update_installer import UpdateInstaller, DownloadThread, InstallThread, current_exe, unsupported_reason
from src.utils.startup import update_startup_path_if_needed
from src.utils.ports import DEFAULT_TRANSFER_PORT
from src.utils.error_text import localize_error
from src.utils.locales import get_active_language, t
from typing import Optional


UPDATE_RESTART_BIND_GRACE = 4.0  # sn: güncelleme yeniden başlatmasında tercih edilen portu bağlamak için en çok bekleme


def _stop_update_threads(app) -> None:
    """Çıkışta süren indirme/kurulum iş parçacığı QThread yıkılırken çökmesin: indirme iptal edilir, kurulum beklenir."""
    thread = getattr(app, "download_thread", None)
    installer = getattr(app, "update_installer", None)
    if thread is not None and thread.isRunning():
        if installer is not None:
            installer.cancel_download()
        if not thread.wait(3000):
            # Ağ okumasında takılı kaldı (en çok 30 sn): çıkıyoruz, QThread çalışırken yıkılıp süreci çökertmesin
            thread.terminate()
            thread.wait(500)
    install = getattr(app, "install_thread", None)
    if install is not None and install.isRunning():
        install.wait(10000)  # exe değiştirme yarıda kalmasın


class Application(QObject):
    # Define signals for thread-safe GUI updates
    device_found_signal = pyqtSignal(object)  # Device
    device_lost_signal = pyqtSignal(object)   # Device
    file_received_signal = pyqtSignal(object)  # Transfer
    transfer_progress_signal = pyqtSignal(object)  # Transfer
    transfer_complete_signal = pyqtSignal(object)
    approval_requested = pyqtSignal(object)
    manual_probe_failed = pyqtSignal(str, int)  # ip, port
    manual_device_offline = pyqtSignal(object)  # Device — ulaşılamadı ama listede dursun

    def __init__(self):
        super().__init__()

        # Track folder transfers: {folder_path: {'total': count, 'completed': count, 'device': Device}}
        self._folder_transfers = {}
        # Track handled transfer completion IDs to prevent duplicate signals
        self._handled_completion_ids = set()
        # stop() idempotent olsun (aboutToQuit + açık çıkış yolları)
        self._stopped = False

        # Initialize components
        self.config = get_config()
        self.logger = get_logger()
        self.database = get_database()

        # Core components
        self.transfer_manager = TransferManager(
            max_concurrent=self.config.get('transfer', 'max_concurrent_transfers', 3)
        )
        self.tcp_server = TCPServer(self.transfer_manager)
        if self._is_update_restart():
            # Güncelleme yeniden başlatması: eski süreç çıkarken port birkaç yüz ms meşgul kalabilir (kısa yeniden deneme)
            # ve bu açılışta başka porta kayılırsa o KALICI olarak kaydedilmez (sonraki açılış yine 38520'yi dener).
            self.tcp_server.bind_retry_seconds = UPDATE_RESTART_BIND_GRACE
            self.tcp_server.remember_port_fallback = False
        self.tcp_client = TCPClient(self.transfer_manager)
        self.discovery = NetworkDiscovery()

        # Update checker
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self._on_update_available)
        self.update_checker.check_message.connect(self._on_update_check_message)

        # Update installer
        self.update_installer = UpdateInstaller()
        self.update_installer.download_progress.connect(self._on_download_progress)
        self.update_installer.download_complete.connect(self._on_download_complete)
        self.update_installer.download_failed.connect(self._on_download_failed)
        self.update_installer.install_started.connect(self._on_install_started)
        self.update_installer.install_complete.connect(self._on_install_complete)
        self.update_installer.install_failed.connect(self._on_install_failed)

        # Update dialog reference
        self.update_dialog = None
        self._pending_update = None
        self._manual_update_request = False
        self._silent_update = False          # kullanıcı onayı beklemeden (otomatik/zorunlu) yürüyen güncelleme
        self._auto_update_timer = None
        self.download_thread = None
        self.install_thread = None
        self._update_phase = "idle"          # "idle" | "downloading" | "installing"
        self._downloading_version = None
        self._ready_update = None            # {'version', 'path'}: indirilmiş + doğrulanmış, henüz kurulmamış paket
        self._quitting_for_update = False    # güncelleme için çıkılıyor: sağlıklı-sürüm temizliği çalışmaz
        self._started_at = time.monotonic()

        # GUI components
        install_message_box()  # özel hata/bilgi/soru kutusu: TCP paleti, simgesi ve dili (pencereden ÖNCE)
        self.window = MainWindow()
        self.window.update_checker = self.update_checker  # Pass reference
        self.update_checker.notice_received.connect(self.window.show_notice)
        self.tray_icon = TrayIcon(lang=get_active_language(self.config))
        self.tray_icon.sync_state = self.window._sync_tray_menus
        self.tray_icon.window_visible = self._main_window_visible
        self.window.tray_icon = self.tray_icon
        # Bildirimler tek ortak yoldan (utils/notify.Notifier): tepsi balonu; tepsi yoksa macOS/Linux araçları
        SystemToast.configure(
            tray_provider=lambda: self.tray_icon.tray if self.tray_icon.is_available() else None,
            icon_provider=lambda: self.window.windowIcon(),
        )

        # Setup
        self._setup_connections()

        self.logger.info("TransferTCP started")

    def _setup_connections(self):
        """Setup signal/slot connections"""
        # Window signals
        self.window.send_files_requested.connect(self._on_send_files)
        self.window.pause_transfer_requested.connect(self._on_pause_transfer)
        self.window.resume_transfer_requested.connect(self._on_resume_transfer)
        self.window.cancel_transfer_requested.connect(self._on_cancel_transfer)
        self.window.refresh_devices_requested.connect(self._on_refresh_devices)
        self.window.manual_device_requested.connect(self._on_manual_device)
        self.window.device_remove_requested.connect(self._on_remove_device)

        # Tray icon signals
        self.tray_icon.show_window.connect(self._show_window)
        self.tray_icon.hide_window.connect(self.window.hide)
        self.tray_icon.open_settings.connect(self.window._open_settings)
        self.tray_icon.quit_app.connect(self.window.quit_application)
        self.tray_icon.clear_history.connect(self.window.clear_all_transfer_history)
        self.tray_icon.update_requested.connect(self.show_pending_update)
        self.window.update_requested.connect(self.show_pending_update)
        self.tray_icon.theme_selected.connect(self.window._change_theme)
        self.tray_icon.language_selected.connect(self.window._change_language)

        # Connect internal signals for thread-safe GUI updates
        self.device_found_signal.connect(
            self._handle_device_found_gui, Qt.ConnectionType.QueuedConnection
        )
        self.device_lost_signal.connect(
            self._handle_device_lost_gui, Qt.ConnectionType.QueuedConnection
        )
        self.manual_probe_failed.connect(
            self._handle_manual_probe_failed_gui, Qt.ConnectionType.QueuedConnection
        )
        self.manual_device_offline.connect(
            self._handle_manual_offline_gui, Qt.ConnectionType.QueuedConnection
        )
        self.file_received_signal.connect(self._handle_file_received_gui, Qt.ConnectionType.QueuedConnection)
        self.transfer_progress_signal.connect(self._handle_transfer_progress_gui)
        self.transfer_complete_signal.connect(self._handle_transfer_complete_gui)
        self.approval_requested.connect(self._handle_device_approval_gui, Qt.ConnectionType.QueuedConnection)

        # Discovery callbacks (will emit signals instead of direct GUI updates)
        self.discovery.on_device_found = self._on_device_found_callback
        self.discovery.on_device_lost = self._on_device_lost_callback

        # Transfer manager callbacks (thread-safe via signals)
        self.transfer_manager.on_progress = self._on_transfer_progress_callback
        self.transfer_manager.on_complete = self._on_transfer_complete_callback

        # Server callbacks (thread-safe via signals)
        self.tcp_server.on_connection = self._on_client_connected
        self.tcp_server.on_file_received = self._on_file_received_callback
        self.tcp_server.on_device_approval = self._on_device_approval_callback
        self.tcp_server.on_port_changed = self._on_port_changed

        # Client callbacks (will use signals for thread-safety)
        self.tcp_client.on_transfer_started = self._on_transfer_started
        # Note: on_complete is handled centrally by self.transfer_manager.on_complete
        self.tcp_client.on_transfer_complete = None

    @staticmethod
    def _is_update_restart(argv=None) -> bool:
        """Bu açılış bir güncellemenin yeniden başlatması mı (`--wait-pid` / `--updated` bayrakları)?"""
        argv = sys.argv if argv is None else argv
        return self_update.flag_value(argv, "--wait-pid") is not None or self_update.updated_from(argv) is not None

    def _run_first_time_setup(self):
        """İlk kurulum: cihaz adı + indirme klasörü tek karşılama penceresinde (eski üç ardışık kutunun yerine).
        Esc / ✕ = varsayılanlarla devam; "Başla" = seçilenlerle. Çıkış istenmişse (tepsiden) hiçbir şey kaydedilmez."""
        from PyQt6.QtWidgets import QApplication
        from src.gui.welcome_dialog import WelcomeDialog
        lang = get_active_language(self.config)

        quitting = {"v": False}
        QApplication.instance().aboutToQuit.connect(lambda: quitting.__setitem__("v", True))

        default_name = get_hostname()
        default_folder = get_default_download_dir()
        dialog = WelcomeDialog(self.window, lang, default_name, default_folder)
        dialog.exec()
        if quitting["v"]:
            # Çıkış (ör. tepsiden) istendi: kurulum yarım kaldı (first_run açık kalır), bir sonraki açılışta yeniden sorulur.
            return

        device_name, download_folder = dialog.values()
        self.config.set('general', 'device_name', device_name)
        self.logger.info(f"Device name set: {device_name}")
        self.config.set('transfer', 'download_folder', download_folder)
        self.config.set('general', 'first_run', False)

    def start(self):
        """Start application components"""
        # Configure logging from settings
        try:
            log_level = self.config.get('advanced', 'log_level', 'WARNING')
            enable_logging = self.config.get('advanced', 'enable_logging', True)
            self.logger.set_level(log_level)
            self.logger.set_enabled(enable_logging)
        except Exception:
            pass

        # Check and update startup registry if program was moved
        if self.config.get('general', 'auto_start', False):
            try:
                start_minimized_pref = self.config.get('general', 'start_minimized', True)
                updated = update_startup_path_if_needed(minimized=start_minimized_pref)
                if updated:
                    self.logger.info("Startup registry path updated (program was moved or flags changed)")
            except Exception as e:
                self.logger.warning(f"Failed to check startup path: {e}")

        # Show tray icon first
        self.tray_icon.show()
        self.window._sync_tray_menus()

        # Check first run IMMEDIATELY - BEFORE starting network
        # Only show setup dialog if this is actually the first run
        was_first_run = self.config.get('general', 'first_run', True)

        # Check if should start minimized (command line flag or user preference, but not on first run)
        start_minimized = self.config.get('general', 'start_minimized', True)
        should_show_window = self._should_show_window(was_first_run, start_minimized, sys.argv)

        # Defer operations to avoid blocking UI
        # Start core components (deferred to avoid blocking UI)
        def start_components():
            try:
                self.transfer_manager.start()
                self.tcp_server.start()
                self.discovery.start()

                # Start update checker (if enabled) - non-blocking
                self.update_checker.start()

                # Update connection status
                self.window.update_connection_status(True)

                # If this was first run, trigger an initial network scan after a short delay
                if was_first_run:
                    QTimer.singleShot(2000, self._on_refresh_devices)  # 2 second delay

                self.logger.info("All components started")
            except Exception as e:
                self.logger.error(f"Failed to start components: {e}")

        # Show window AFTER theme is loaded and UI is ready
        def show_window_if_needed():
            if should_show_window:
                self.window.show()
                self.window.raise_()
                self.window.activateWindow()

                # Run first time setup if needed (after window is shown)
                if was_first_run:
                    # Small delay to ensure window is fully rendered
                    QTimer.singleShot(100, self._run_first_time_setup)
            else:
                # Starting minimized - ensure UI is still properly initialized
                self.logger.info("Starting minimized to tray")
                # Refresh devices after a delay to ensure discovery has started
                QTimer.singleShot(3000, self._on_refresh_devices)

        # Defer operations to allow UI to render properly
        # Order: start components -> show window (if needed)
        QTimer.singleShot(50, start_components)
        QTimer.singleShot(200, show_window_if_needed)  # Show window AFTER everything is ready

        self._schedule_update_followups(sys.argv)

    @staticmethod
    def _should_show_window(was_first_run: bool, start_minimized: bool, argv) -> bool:
        """Açılışta ana pencere açılsın mı? `--show-window`: güncellemeden önce pencere açıktı, yeni sürüm de açar
        ("simge durumunda başlat" ayarını geçersiz kılar). `--minimized`: tepside kalır."""
        if was_first_run or self_update.wants_window(argv):
            return True
        return not start_minimized and '--minimized' not in argv

    def _schedule_update_followups(self, argv):
        """Güncellemeden sonraki ilk açılış: "v{yeni} sürümüne güncellendi" bildirimi; sağlıklı-sürüm onayı."""
        if self_update.updated_from(argv):
            QTimer.singleShot(1500, self._announce_update_installed)
        self._arm_health_confirmation()

    def _announce_update_installed(self):
        """Yeni sürüm `--updated <eski>` ile açıldı: tepsi balonu (bildirimler açıksa) + durum çubuğu iletisi."""
        lang = get_active_language(self.config)
        text = t("update_installed_toast", lang).format(app="TransferTCP", version=self.update_checker.current_version)
        try:
            self.window.show_status_message(text, 8000)
            if self.config.get('general', 'notifications_enabled', True):
                SystemToast.show("TransferTCP", text)
        except Exception as error:
            self.logger.error(f"Güncelleme bildirimi gösterilemedi: {error}")

    def _arm_health_confirmation(self):
        """Güncellemeden sonra yeni sürüm yeterince çalışınca (60 sn) ve temiz çıkışta (açılıştan >= 10 sn sonra)
        eski sürüm yedeği silinir; yeni sürüm açılışta ölürse `startup_guard` eskisini geri getirir."""
        from src.utils.update_policy import is_frozen
        if not is_frozen():
            return
        exe = current_exe()
        QTimer.singleShot(self_update.HEALTHY_AFTER_SECONDS * 1000, lambda: self._confirm_healthy(exe))
        instance = QApplication.instance()
        if instance is not None:
            instance.aboutToQuit.connect(lambda: self._confirm_healthy_on_quit(exe))

    def _confirm_healthy(self, exe: str):
        if not getattr(self, "_quitting_for_update", False):
            self_update.confirm_healthy(exe)

    def _confirm_healthy_on_quit(self, exe: str):
        if time.monotonic() - getattr(self, "_started_at", time.monotonic()) >= 10:
            self._confirm_healthy(exe)

    def stop(self):
        """Stop application components.

        Idempotent: hem QApplication.aboutToQuit hem de açık çıkış yolları (_quit_application,
        güncelleme yeniden başlatması) çağırabilir; kapanış adımları yalnızca bir kez çalışır.
        Bir adımın hatası diğerlerini (ör. GOODBYE yayını, DB kapatma) engellemez.
        """
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self.logger.info("Stopping application...")

        steps = (
            ("discovery", lambda: self.discovery.stop()),            # GOODBYE yayınını da gönderir
            ("tcp_server", lambda: self.tcp_server.stop()),
            ("transfer_manager", lambda: self.transfer_manager.stop()),
            ("update_threads", lambda: _stop_update_threads(self)),
            ("update_checker", lambda: self.update_checker.stop()),
            ("database", lambda: self.database.close()),
        )
        for name, step in steps:
            try:
                step()
            except Exception as error:
                self.logger.error(f"Kapanışta {name} durdurulamadı: {error}")

        self.logger.info("Application stopped")

    def teardown_qt_objects(self):
        """`exec()` bittikten sonra GUI nesnelerini BİLİNEN sırayla (pencere -> menüler -> tepsi -> ana pencere) yok eder.

        E2E'de gerçek exe ara sıra Python sonlandırmasında (`Py_FinalizeEx` -> PyQt6 atexit -> sip) `access violation` ile çıktı:
        PyQt6 sahipsiz QObject'leri (ana pencere, tepsi, menüler) koşudan koşuya değişen sırayla siler ve bazen serbest belleği okur.
        Her çıkış yolunda çalışır; silinmiş ya da sahte nesneler sessizce atlanır.
        """
        from PyQt6 import sip

        tray = getattr(self, "tray_icon", None)
        victims = (
            getattr(self, "update_dialog", None),
            getattr(tray, "lang_menu", None), getattr(tray, "theme_menu", None), getattr(tray, "menu", None),
            getattr(tray, "tray", None), tray, getattr(self, "window", None),
        )
        for obj in victims:
            try:
                if isinstance(obj, QObject) and not sip.isdeleted(obj):
                    sip.delete(obj)
            except Exception:
                pass

    # Device event handlers (callbacks from discovery thread)
    def _on_device_found_callback(self, device: Device):
        """Handle device discovered (called from discovery thread)"""
        self.logger.info(f"Device found: {device.name} at {device.ip}")
        # Emit signal for thread-safe GUI update
        self.device_found_signal.emit(device)

    def _on_device_lost_callback(self, device: Device):
        """Handle device lost (called from discovery thread)"""
        self.logger.info(f"Device lost: {device.name}")
        # Emit signal for thread-safe GUI update
        self.device_lost_signal.emit(device)

    # GUI update handlers (called in main thread)
    def _handle_device_found_gui(self, device: Device):
        """Handle device found - GUI updates (main thread)"""
        self.logger.info(f"Adding device to GUI: {device.name}")
        # Aynı IP farklı port: eski elle eklenen kaydı kaldır
        for _, widget in list(self.window.device_list.devices.values()):
            existing = widget.device
            if existing.ip == device.ip and existing.port != device.port:
                self.window.remove_device(existing)
        self.window.add_device(device)
        lang = get_active_language(self.config)
        if device.is_online:
            self.window.show_status_message(t("device_joined", lang).format(name=device.name))

    def _handle_device_lost_gui(self, device: Device):
        """Handle device lost - GUI updates (main thread)"""
        self.window.update_device(device)
        lang = get_active_language(self.config)
        self.window.show_status_message(t("device_left", lang).format(name=device.name))

    def _on_manual_device(self, ip: str, display_name: str, port: int):
        """IP ile eklenen cihazı hemen listele, arka planda yokla."""
        lang = get_active_language(self.config)
        pending = self.discovery.add_manual_device(ip, port, display_name)
        pending.custom_name = display_name if display_name != ip else None
        self.database.save_device(pending.to_dict())
        self.window.add_device(pending)
        self.window.show_status_message(t("probing_device", lang).format(ip=ip), 4000)

        import threading

        def _probe():
            try:
                device = self.discovery.probe_manual_device(
                    ip, port, timeout=4.0, display_name=display_name
                )
            except Exception as e:
                self.logger.error(f"Manual probe error: {e}")
                device = None
            if device is not None:
                if device.is_manual:
                    self.database.save_device(device.to_dict())
                self.device_found_signal.emit(device)
            else:
                offline = self.discovery.get_device(ip, port)
                if offline is not None:
                    self.database.save_device(offline.to_dict())
                    self.device_found_signal.emit(offline)
                self.manual_probe_failed.emit(ip, port)

        threading.Thread(target=_probe, daemon=True).start()

    def _handle_manual_offline_gui(self, device: Device):
        """Ulaşılamayan elle eklenen cihazı listede çevrimdışı göster."""
        self.window.update_device(device)
        lang = get_active_language(self.config)
        self.window.show_status_message(t("device_unreachable", lang).format(ip=device.ip), 6000)

    def _on_remove_device(self, device: Device):
        """Kullanıcı listeden kaldırdı — keşfin geri getirmesini engelle."""
        try:
            self.discovery.forget_device(device.ip, device.port)
        except Exception as e:
            self.logger.error(f"Remove device error: {e}")

    def _handle_manual_probe_failed_gui(self, ip: str, port: int):
        """Yoklama başarısız — ana iş parçacığında bilgi ver."""
        lang = get_active_language(self.config)
        self.window.show_status_message(t("device_unreachable", lang).format(ip=ip), 6000)

    # Transfer event handlers
    def _on_send_files(self, files: list, device: Device, folder_path: Optional[str] = None):
        """Handle send files request"""
        self.logger.info(f"Sending {len(files)} files to {device.name}")

        # If folder_path is provided, scan folder to get relative paths
        relative_paths_map = {}
        folder_id = None
        folder_key = None
        if folder_path and isdir(folder_path):
            import time
            import uuid
            from src.utils.helpers import scan_folder
            scanned_files = scan_folder(folder_path)

            # Add folder name to relative paths to preserve root folder structure
            folder_name = basename(folder_path)
            folder_id = f"{folder_name}_{uuid.uuid4().hex[:8]}"
            folder_key = f"send_{folder_id}"
            for full_path, rel_path in scanned_files:
                # Prepend the root folder name to the relative path
                # e.g. "image.jpg" -> "Holiday/image.jpg"
                # (kablo biçimi her zaman '/': Linux/macOS'ta '\' dosya adı karakteri olabilir, çevrilmez)
                if rel_path == '.':
                    new_rel_path = f"{folder_name}/{basename(full_path)}"
                else:
                    new_rel_path = f"{folder_name}/{rel_path}"
                relative_paths_map[full_path] = new_rel_path

            # Track folder transfer
            self._folder_transfers[folder_key] = {
                'folder_id': folder_id,
                'folder_path': folder_path,
                'folder_name': folder_name,
                'total': len(files),
                'completed': 0,
                'device': device,
                'transfer_ids': [],
                'completed_ids': set(),
                'success_ids': set(),
                'failed_ids': set(),
                'created_at': time.time(),
            }

        for filepath in files:
            # Get relative path if this is part of a folder transfer
            relative_path = relative_paths_map.get(filepath)

            # Create transfer
            transfer = self.transfer_manager.create_transfer(
                filepath=filepath,
                device_ip=device.ip,
                device_name=device.name,
                direction=TransferDirection.SEND,
                relative_path=relative_path,
                device_port=getattr(device, "port", DEFAULT_TRANSFER_PORT),
            )

            if transfer:
                if folder_path:
                    transfer.folder_name = basename(folder_path)
                    transfer.folder_total = len(files)
                    transfer.folder_path = folder_path
                    transfer.folder_id = folder_id
                # Add to UI first
                self.window.add_transfer(transfer)

                # Queue the transfer (will be processed by transfer manager)
                self.transfer_manager.queue_transfer(transfer)

                # Send file in background
                self.tcp_client.send_file(transfer)

                # Save to database
                self.database.add_transfer(transfer)

                # Track transfer ID if folder transfer
                if folder_key and folder_key in self._folder_transfers:
                    self._folder_transfers[folder_key]['transfer_ids'].append(transfer.transfer_id)

        # Show status message
        if len(files) > 0:
            lang = get_active_language(self.config)
            if folder_path:
                folder_name = basename(folder_path)
                self.window.show_status_message(
                    t("sending_folder", lang).format(folder=folder_name, count=len(files), device=device.name)
                )
            else:
                self.window.show_status_message(
                    t("sending_files", lang).format(count=len(files), device=device.name)
                )

    def _on_pause_transfer(self, transfer_id: str):
        """Handle pause transfer request"""
        transfer = self.transfer_manager.get_transfer(transfer_id)
        if transfer:
            self.logger.info(f"Pausing transfer (local): {transfer.filename}")
            self.transfer_manager.pause_transfer(transfer_id)
            lang = get_active_language(self.config)
            self.window.show_status_message(
                t("transfer_paused", lang).format(filename=transfer.filename), 2000
            )

    def _on_resume_transfer(self, transfer_id: str):
        """Handle resume transfer request"""
        transfer = self.transfer_manager.get_transfer(transfer_id)
        if transfer:
            self.logger.info(f"Resuming transfer: {transfer.filename}")
            self.transfer_manager.resume_transfer(transfer_id)
            lang = get_active_language(self.config)
            self.window.show_status_message(
                t("transfer_resumed", lang).format(filename=transfer.filename), 2000
            )

    def _cleanup_incomplete_file(self, transfer: Transfer):
        """Clean up the incomplete .part file on failure or cancel.

        transfer.filepath nihai hedef dosyadır ve orada kullanıcının eski, sağlam bir
        dosyası bulunabilir; bu yüzden YALNIZCA .part silinir (eskiden hedef de siliniyordu).
        """
        if not transfer or not hasattr(transfer, 'filepath') or not transfer.filepath:
            return
        from os import remove
        try:
            part_file = transfer.filepath + ".part"
            if exists(part_file):
                remove(part_file)
                self.logger.info(f"Cleaned up incomplete .part file: {part_file}")
            meta_file = part_file + ".meta"  # devam (resume) meta dosyası
            if exists(meta_file):
                remove(meta_file)
        except Exception as e:
            self.logger.error(f"Failed to cleanup file {transfer.filename}: {e}")

    def _on_cancel_transfer(self, transfer_id: str):
        """Handle cancel transfer request"""
        transfer = self.transfer_manager.get_transfer(transfer_id)
        if transfer:
            self.logger.info(f"Cancelling transfer: {transfer.filename}")
            self.transfer_manager.cancel_transfer(transfer_id)

            # Clean up incomplete file and .part file if receiving
            if transfer.direction == TransferDirection.RECEIVE:
                self._cleanup_incomplete_file(transfer)

    # Callback from worker threads (emit signals)
    def _on_transfer_progress_callback(self, transfer: Transfer):
        """Handle transfer progress - from worker thread"""
        self.transfer_progress_signal.emit(transfer)

    def _on_transfer_complete_callback(self, transfer: Transfer):
        """Handle transfer complete - from worker thread"""
        self.transfer_complete_signal.emit(transfer)

    def _on_file_received_callback(self, transfer: Transfer):
        """Handle file received - from server thread"""
        self.file_received_signal.emit(transfer)

    # GUI handlers (main thread)
    def _handle_transfer_progress_gui(self, transfer: Transfer):
        """Handle transfer progress update - main thread"""
        # Note: Do NOT write to SQLite DB on every 100ms progress tick;
        # database is updated on start and final completion to avoid disk I/O stalls.

        # Update tray icon only when active transfer count actually changes
        active_count = len(self.transfer_manager.get_active_transfers())
        if getattr(self, '_last_badge_count', -1) != active_count:
            self._last_badge_count = active_count
            self.tray_icon.update_icon_with_badge(active_count)


    def _cleanup_stale_folder_transfers(self):
        """Clean up folder tracking entries older than 30 minutes"""
        import time
        now = time.time()
        stale_keys = [
            k for k, v in self._folder_transfers.items()
            if now - v.get('created_at', now) > 1800
        ]
        for k in stale_keys:
            try:
                del self._folder_transfers[k]
            except KeyError:
                pass

    def _find_folder_transfer_info(self, transfer: Transfer):
        """Find folder transfer info for a given transfer (both sender and receiver)"""
        import time
        self._cleanup_stale_folder_transfers()
        is_folder_transfer = False
        folder_path = None
        folder_info = None

        # Check if transfer has relative_path (indicates folder transfer)
        has_relative_path = hasattr(transfer, 'relative_path') and transfer.relative_path is not None

        # 1. Check sender-side tracking by folder_id or transfer_id
        if transfer.direction == TransferDirection.SEND:
            transfer_folder_id = getattr(transfer, 'folder_id', None)
            if transfer_folder_id:
                sender_key = f"send_{transfer_folder_id}"
                if sender_key in self._folder_transfers:
                    info = self._folder_transfers[sender_key]
                    if transfer.transfer_id not in info.get('transfer_ids', []):
                        info.setdefault('transfer_ids', []).append(transfer.transfer_id)
                    return True, sender_key, info

            for path, info in self._folder_transfers.items():
                if transfer.transfer_id in info.get('transfer_ids', []):
                    return True, path, info

            # If sender-side not matched by ID, try matching by relative_path
            if has_relative_path:
                relative_path = transfer.relative_path
                for path, info in self._folder_transfers.items():
                    folder_base = info.get('folder_name') or basename(path)
                    if relative_path and folder_base in relative_path:
                        if transfer.transfer_id not in info.get('transfer_ids', []):
                            info.setdefault('transfer_ids', []).append(transfer.transfer_id)
                        return True, path, info

        # 2. Receiver-side tracking
        if transfer.direction == TransferDirection.RECEIVE:
            folder_name = getattr(transfer, 'folder_name', None)
            folder_id = getattr(transfer, 'folder_id', None)
            if not folder_name and has_relative_path:
                norm_rel = transfer.relative_path.replace('\\', '/')
                parts = [p for p in norm_rel.split('/') if p]
                if parts:
                    folder_name = parts[0]

            if folder_id or folder_name:
                key = f"recv_{transfer.device_ip}_{folder_id}" if folder_id else f"recv_{transfer.device_ip}_{folder_name}"
                if key not in self._folder_transfers:
                    folder_total = getattr(transfer, 'folder_total', None) or 1
                    self._folder_transfers[key] = {
                        'total': folder_total,
                        'completed': 0,
                        'device_name': transfer.device_name,
                        'folder_name': folder_name or folder_id,
                        'folder_id': folder_id,
                        'transfer_ids': [],
                        'completed_ids': set(),
                        'success_ids': set(),
                        'failed_ids': set(),
                        'created_at': time.time(),
                    }
                info = self._folder_transfers[key]
                cand_total = getattr(transfer, 'folder_total', None)
                if cand_total and cand_total > info.get('total', 0):
                    info['total'] = cand_total
                if folder_name and (not info.get('folder_name') or info.get('folder_name') == folder_id):
                    info['folder_name'] = folder_name
                if transfer.transfer_id not in info.get('transfer_ids', []):
                    info['transfer_ids'].append(transfer.transfer_id)
                return True, key, info

        return is_folder_transfer, folder_path, folder_info

    def _update_folder_transfer_progress(self, transfer: Transfer, folder_info: dict):
        """Update folder transfer progress safely by tracking completed transfer IDs"""
        completed_ids = folder_info.setdefault('completed_ids', set())
        success_ids = folder_info.setdefault('success_ids', set())
        failed_ids = folder_info.setdefault('failed_ids', set())

        if transfer.is_complete:
            completed_ids.add(transfer.transfer_id)
            success_ids.add(transfer.transfer_id)
        elif transfer.is_failed or getattr(transfer, 'status', None) in [TransferStatus.FAILED, TransferStatus.CANCELLED]:
            completed_ids.add(transfer.transfer_id)
            failed_ids.add(transfer.transfer_id)

        folder_info['completed'] = len(completed_ids)

    def _get_folder_name(self, folder_path: str) -> str:
        """Get folder name from path or key"""
        lang = get_active_language(self.config)
        try:
            if folder_path in self._folder_transfers:
                fname = self._folder_transfers[folder_path].get('folder_name')
                if fname:
                    return fname
            if folder_path.startswith("recv_"):
                parts = folder_path.split("_", 2)
                if len(parts) >= 3:
                    raw_name = parts[2]
                    if "_" in raw_name:
                        name_part, suffix = raw_name.rsplit("_", 1)
                        if len(suffix) == 8:
                            return name_part
                    return raw_name
            if folder_path.startswith("send_"):
                raw_name = folder_path[5:]
                if "_" in raw_name:
                    name_part, suffix = raw_name.rsplit("_", 1)
                    if len(suffix) == 8:
                        return name_part
                return raw_name
            return basename(folder_path) or t("folder_default", lang)
        except Exception:
            return t("folder_default", lang)

    def _show_folder_completion_toast(self, folder_path: str, folder_info: dict, transfer: Transfer):
        """Show toast notification when all files in folder are complete"""
        lang = get_active_language(self.config)
        folder_name = folder_info.get('folder_name') or self._get_folder_name(folder_path)
        total = folder_info.get('total', 0)
        success_ids = folder_info.get('success_ids')
        if success_ids is not None:
            success_count = len(success_ids)
        else:
            success_count = folder_info.get('completed', total)

        direction_text = (
            t("direction_sent", lang)
            if transfer.direction == TransferDirection.SEND
            else t("direction_received", lang)
        )

        is_foreground = bool(self.window and self.window.isVisible() and self.window.isActiveWindow())
        notifications_enabled = self.config.get('general', 'notifications_enabled', True) and not is_foreground

        if 0 < success_count < total:
            toast_body = f"{folder_name} ({success_count}/{total}) {direction_text}"
            if notifications_enabled:
                SystemToast.show(t("folder_transfer_complete_title", lang), toast_body)
            self.window.show_status_message(f"✓ {toast_body}")
        elif success_count == total and total > 0:
            toast_body = t("folder_transfer_complete_toast", lang).format(
                folder=folder_name, count=total, direction=direction_text
            )
            if notifications_enabled:
                SystemToast.show(t("folder_transfer_complete_title", lang), toast_body)
            self.window.show_status_message(f"✓ {toast_body}")
        else:
            # 0 successful files
            toast_body = t("file_failed_folder", lang).format(folder=folder_name)
            if notifications_enabled:
                SystemToast.show(folder_name, toast_body)
            self.window.show_status_message(f"✕ {toast_body}")

        # Clean up folder tracking
        if folder_path in self._folder_transfers:
            del self._folder_transfers[folder_path]

    def _handle_transfer_complete_gui(self, transfer: Transfer):
        """Handle transfer completion - main thread"""
        try:
            # Idempotency guard: prevent duplicate completion processing
            if transfer.transfer_id in self._handled_completion_ids:
                return
            self._handled_completion_ids.add(transfer.transfer_id)
            if len(self._handled_completion_ids) > 2000:
                self._handled_completion_ids.clear()

            lang = get_active_language(self.config)

            # Immediately update the transfer widget in GUI so UI shows 100% / Tamamlandı without timer lag
            self.window.update_transfer(transfer)

            # Update database
            self.database.update_transfer(transfer)

            # Yalnızca iptalde .part/.meta silinir; hatada (ağ kopması vb.) sunucu onları devam (resume) için korur
            if transfer.status == TransferStatus.CANCELLED and transfer.direction == TransferDirection.RECEIVE:
                self._cleanup_incomplete_file(transfer)

            # Find folder transfer info
            is_folder_transfer, folder_path, folder_info = self._find_folder_transfer_info(transfer)

            # Update folder transfer progress
            if is_folder_transfer and folder_info:
                self._update_folder_transfer_progress(transfer, folder_info)

            # Check if all transfers are complete and there's a pending update
            active_transfers = self.transfer_manager.get_active_transfers()
            if not active_transfers and hasattr(self, '_pending_update') and self._pending_update:
                # All transfers complete, check if we should auto-start pending update
                update_info = self._pending_update
                if update_info.get('is_mandatory', False):
                    # Auto-start the pending update
                    self.logger.info("All transfers complete, starting pending update")
                    self._start_silent_update()
                    # `_pending_update` SİLİNMEZ: indirme/kurulum hatasında düğme/tepsi öğesi çalışmaya devam etsin
                elif self._auto_update_enabled():
                    self._schedule_auto_update()

            # Show Windows toast / folder completion
            notifications_enabled = self.config.get('general', 'notifications_enabled', True)
            if transfer.is_complete:
                if is_folder_transfer and folder_info and folder_path:
                    # Folder transfer - only show toast when all files are complete
                    try:
                        completed = folder_info.get('completed', 0)
                        total = folder_info.get('total', 0)
                        transfer_ids = folder_info.get('transfer_ids', [])

                        # Verify if any transfer in this folder is still active
                        has_active = any(
                            (t_item := self.transfer_manager.get_transfer(tid)) and t_item.is_active
                            for tid in transfer_ids
                        )

                        if completed >= total and not has_active:
                            # Force update all widgets belonging to this folder to 100% / Tamamlandı
                            for tid in transfer_ids:
                                t_item = self.transfer_manager.get_transfer(tid)
                                if t_item:
                                    self.window.update_transfer(t_item)
                            # Ensure Qt repaints widgets on screen before native toast is presented
                            QApplication.processEvents()
                            self._show_folder_completion_toast(folder_path, folder_info, transfer)
                        else:
                            # Individual file in folder - just update status, no toast
                            filename = getattr(transfer, 'filename', t("file", lang))
                            self.window.show_status_message(
                                t("file_complete_progress", lang).format(
                                    filename=filename, completed=completed, total=total
                                )
                            )
                    except Exception as toast_error:
                        self.logger.error(f"Error showing folder transfer toast: {toast_error}", exc_info=True)
                        filename = getattr(transfer, 'filename', t("file", lang))
                        self.window.show_status_message(
                            t("file_complete", lang).format(filename=filename)
                        )
                else:
                    # Check if transfer has relative_path (folder transfer but not tracked)
                    has_relative_path = hasattr(transfer, 'relative_path') and transfer.relative_path is not None

                    if has_relative_path:
                        # Folder transfer but not tracked - just show status, no toast
                        filename = getattr(transfer, 'filename', t("file", lang))
                        self.window.show_status_message(
                            t("file_complete", lang).format(filename=filename)
                        )
                    else:
                        # Single file transfer - show toast immediately
                        try:
                            # Immediate UI update and event flush before toast
                            self.window.update_transfer(transfer)
                            QApplication.processEvents()

                            filename = getattr(transfer, 'filename', t("file", lang))
                            direction_text = (
                                t("direction_sent", lang)
                                if transfer.direction == TransferDirection.SEND
                                else t("direction_received", lang)
                            )
                            is_foreground = bool(self.window and self.window.isVisible() and self.window.isActiveWindow())
                            if notifications_enabled and not is_foreground:
                                SystemToast.show(
                                    t("transfer_complete_title", lang),
                                    t("transfer_complete_toast", lang).format(
                                        filename=filename, direction=direction_text
                                    ),
                                )
                            self.window.show_status_message(f"✓ {filename} {direction_text}")
                        except Exception as toast_error:
                            self.logger.error(f"Error showing single file toast: {toast_error}", exc_info=True)
                            filename = getattr(transfer, 'filename', t("file", lang))
                            self.window.show_status_message(
                                t("file_complete", lang).format(filename=filename)
                            )
            elif transfer.is_failed:
                try:
                    if is_folder_transfer and folder_info and folder_path:
                        completed = folder_info.get('completed', 0)
                        total = folder_info.get('total', 0)
                        transfer_ids = folder_info.get('transfer_ids', [])
                        has_active = any(
                            (t_item := self.transfer_manager.get_transfer(tid)) and t_item.is_active
                            for tid in transfer_ids
                        )
                        if completed >= total and not has_active:
                            for tid in transfer_ids:
                                t_item = self.transfer_manager.get_transfer(tid)
                                if t_item:
                                    self.window.update_transfer(t_item)
                            QApplication.processEvents()
                            self._show_folder_completion_toast(folder_path, folder_info, transfer)
                        else:
                            error_msg = localize_error(getattr(transfer, 'error_message', None) or t("unknown_error", lang), lang)
                            self.window.show_status_message(
                                t("file_failed", lang).format(filename=transfer.filename, error=error_msg)
                            )
                    else:
                        error_msg = localize_error(getattr(transfer, 'error_message', None) or t("unknown_error", lang), lang)
                        self.window.show_status_message(
                            t("file_failed", lang).format(filename=transfer.filename, error=error_msg)
                        )
                except Exception as error_display_error:
                    self.logger.error(f"Error displaying failure message: {error_display_error}", exc_info=True)
                    self.window.show_status_message(
                        f"✕ {transfer.filename} - {t('transfer_failed_generic', lang)}"
                    )

            # Update statistics
            stats = self.transfer_manager.get_statistics()
            self.window.update_statistics(
                stats['total_sent'],
                stats['total_received']
            )

            # Update tray icon
            active_count = len(self.transfer_manager.get_active_transfers())
            self.tray_icon.update_icon_with_badge(active_count)
        except Exception as e:
            self.logger.exception(f"Error in _handle_transfer_complete_gui: {e}")
            # Still show basic status message even if there's an error
            try:
                lang = get_active_language(self.config)
                if transfer.is_complete:
                    self.window.show_status_message(
                        t("file_complete", lang).format(filename=transfer.filename)
                    )
                elif transfer.is_failed:
                    self.window.show_status_message(
                        t("file_failed", lang).format(
                            filename=transfer.filename,
                            error=localize_error(getattr(transfer, 'error_message', None) or t("unknown_error", lang), lang),
                        )
                    )
            except Exception:
                pass


    def _on_transfer_started(self, transfer: Transfer):
        """Handle transfer started"""
        self.logger.info(f"Transfer started: {transfer.filename}")

    def _on_refresh_devices(self):
        """Handle refresh devices request"""
        self.logger.info("Refreshing devices...")
        if hasattr(self.discovery, 'broadcast_now'):
            self.discovery.broadcast_now()

        self.window.device_list.begin_refresh()

        def add_devices_async():
            try:
                devices = list(self.discovery.get_devices().values())
                shown = [d for d in devices if d.is_online or d.is_manual]

                active_keys = {f"{d.ip}:{d.port}" for d in shown}
                for key in list(self.window.device_list.devices.keys()):
                    if key not in active_keys:
                        _, widget = self.window.device_list.devices[key]
                        if not getattr(widget.device, 'is_manual', False):
                            self.window.remove_device(widget.device)

                for device in shown:
                    self.window.add_device(device)

                lang = get_active_language(self.config)
                self.window.show_status_message(
                    t("devices_found", lang).format(count=len(shown)), 3000
                )
            except Exception as e:
                self.logger.error(f"Error refreshing devices: {e}")
            finally:
                self.window.device_list.end_refresh()

            import threading
            threading.Thread(
                target=self.discovery.reprobe_manual_devices, daemon=True
            ).start()

        QTimer.singleShot(250, add_devices_async)

    def _on_client_connected(self, ip: str):
        """Handle client connection"""
        self.logger.info(f"Client connected from {ip}")

    def _on_port_changed(self, old_port: int, new_port: int):
        """Preferred port was busy; notify the user of the fallback."""
        from src.utils.locales import get_active_language, t
        lang = get_active_language(self.config)
        self.window.show_status_message(
            t("port_changed", lang).format(old=old_port, new=new_port),
            8000,
        )

    def _on_device_approval_callback(self, request):
        """Forward approval request from the server thread to the UI thread."""
        self.approval_requested.emit(request)

    def _handle_device_approval_gui(self, request):
        """Ask the user whether to trust an incoming device."""
        from src.core.crypto import format_fingerprint
        from src.gui.trust_dialog import TrustDeviceDialog
        from src.utils.locales import get_active_language, t

        lang = get_active_language(self.config)
        is_foreground = bool(self.window and self.window.isVisible() and self.window.isActiveWindow())
        try:
            if self.config.get('general', 'notifications_enabled', True) and not is_foreground:
                SystemToast.show(
                    t("trust_toast_title", lang),
                    f"{request.device_name} ({request.ip})",
                    duration="long",
                )
        except Exception:
            pass

        try:
            self._show_window()
        except Exception:
            pass

        body = t("trust_device_text", lang).format(
            name=request.device_name,
            ip=request.ip,
        )
        fingerprint = t("trust_device_fingerprint", lang).format(
            fingerprint=format_fingerprint(request.fingerprint)
        )
        box = TrustDeviceDialog(
            t("trust_device_title", lang),
            body,
            fingerprint,
            t("trust_accept", lang),
            t("trust_reject", lang),
            self.window,
        )
        box.exec()
        request.approved = bool(box.approved)
        request.event.set()

    def _on_update_check_message(self, level: str, title: str, message: str):
        """Manuel denetim sonucu için pop-up açılmaz: ayarlardaki durum satırı gösterir; burada yalnızca günlüğe yazılır."""
        self.logger.info(f"Güncelleme denetimi ({level}): {title} - {message}")

    # ------------------------------------------------------------------ güncelleme akışı
    # Durum: _update_phase "idle" -> "downloading" -> "installing" (-> uygulama TEMİZ çıkar, yeni sürüm açılır).
    # Hata/iptalde "idle"a döner. Aynı anda tek indirme/kurulum vardır (`_update_in_progress`).
    def _main_window_visible(self) -> bool:
        window = getattr(self, "window", None)
        return bool(window is not None and window.isVisible() and not window.isMinimized())

    def _update_in_progress(self) -> bool:
        if getattr(self, "_update_phase", "idle") != "idle":
            return True
        for name in ("download_thread", "install_thread"):
            thread = getattr(self, name, None)
            if thread is not None and thread.isRunning():
                return True
        return False

    def _declined_version(self) -> str:
        """Kullanıcının "Daha sonra" dediği (ya da indirmeyi iptal ettiği) sürüm: otomatik kurulum onu kurmaz."""
        try:
            return str(self.config.get('advanced', 'declined_update_version', None) or '')
        except Exception:
            return ''

    def _install_unsupported_reason(self) -> Optional[str]:
        """Bu çalışma biçiminde (kaynaktan / Windows dışı) kendini güncelleme yok: kullanıcıya gösterilecek metin."""
        reason = unsupported_reason()
        if reason is None:
            return None
        lang = get_active_language(self.config)
        return t("update_unsupported_os" if reason == "os" else "update_unsupported_source", lang)

    def _on_update_available(self, version: str, download_url: str, release_notes: str,
                            is_mandatory: bool, file_size: int, checksum: str):
        """Sessiz denetim yeni sürüm buldu: pop-up AÇILMAZ. Sürüm başlık çubuğundaki "Güncelle" düğmesinde ve
        tepsinin en üstünde ("Güncelle · vX") görünür; "otomatik kur" açıksa uygulama kullanılmıyorken kendiliğinden kurulur."""
        ready = getattr(self, '_ready_update', None)
        if ready and ready.get('version') != version:
            # Daha yeni bir sürüm sunuldu: indirilmiş eski paket kurulmasın
            self._ready_update = None
            if not self._update_in_progress():
                self.update_installer.cleanup()
        self._pending_update = {
            'version': version,
            'download_url': download_url,
            'file_size': file_size,
            'checksum': checksum,
            'release_notes': release_notes,
            'is_mandatory': is_mandatory
        }
        self.window.set_update_available(version)
        self.tray_icon.set_update_available(True, version)

        if is_mandatory:
            active_transfers = self.transfer_manager.get_active_transfers()
            if active_transfers:
                self.logger.info(
                    f"Zorunlu güncelleme var ama {len(active_transfers)} aktarım sürüyor - bitince kurulacak"
                )
                return
            self._start_silent_update()
            return

        self._schedule_auto_update()

    # ------------------------------------------------------------------ otomatik kurulum (kullanılmıyorken)
    AUTO_UPDATE_POLL_MS = 30_000

    @staticmethod
    def update_is_idle(active_transfers: int, window_shown: bool, modal_open: bool) -> bool:
        """Uygulama "kullanılmıyor" mu: aktarım sürerken, bir diyalog açıkken ya da pencere ekrandayken
        (gizli/simge durumunda değilken) değil (kurulum uygulamayı kısa süre yeniden başlatır)."""
        if active_transfers > 0 or modal_open:
            return False
        return not window_shown

    def _is_idle_for_update(self) -> bool:
        from PyQt6.QtWidgets import QApplication
        return self.update_is_idle(
            len(self.transfer_manager.get_active_transfers()),
            self._main_window_visible(),
            QApplication.activeModalWidget() is not None,
        )

    def _auto_update_enabled(self) -> bool:
        return bool(
            self.config.get('advanced', 'auto_update_check', True)
            and self.config.get('advanced', 'auto_update_install', True)
        )

    def _schedule_auto_update(self):
        """"Otomatik kur" açıksa uygun ana kadar yoklar (kapalıysa hiçbir şey yapmaz)."""
        if not self._auto_update_enabled():
            return
        if self._auto_update_timer is None:
            self._auto_update_timer = QTimer()
            self._auto_update_timer.timeout.connect(self._try_auto_update)
        if not self._auto_update_timer.isActive():
            self._auto_update_timer.start(self.AUTO_UPDATE_POLL_MS)
        QTimer.singleShot(3000, self._try_auto_update)

    def _stop_auto_update_timer(self):
        if self._auto_update_timer is not None:
            self._auto_update_timer.stop()

    def _try_auto_update(self):
        info = self._pending_update
        if not info:
            return
        if not self._auto_update_enabled():
            self._stop_auto_update_timer()
            return
        if self._update_in_progress():
            return
        if not info.get('is_mandatory') and self._declined_version() == str(info.get('version')):
            # Kullanıcı bu sürüme "Daha sonra" dedi: kendiliğinden kurulmaz (tepsi/düğme kalır, elle kurulabilir)
            self.logger.info("Kullanıcı bu güncellemeyi erteledi: otomatik kurulmayacak (düğmeyle elle kurulabilir)")
            self._stop_auto_update_timer()
            return
        if self._install_unsupported_reason():
            self.logger.info("Bu çalışma biçiminde otomatik kurulum desteklenmiyor (kaynaktan / Windows dışı)")
            self._stop_auto_update_timer()
            return
        from src.utils.update_installer import normalize_checksum
        try:
            checksum_ok = normalize_checksum(info.get('checksum')) is not None
        except ValueError:
            checksum_ok = False
        if not checksum_ok:
            # Onaysız kurulumu kimse görmeden yapma: sunucu sağlama toplamı vermediyse yalnızca düğmeyle kurulur.
            self.logger.info("Güncelleme sağlama toplamı içermiyor: otomatik kurulmayacak (düğmeyle elle kurulabilir)")
            self._stop_auto_update_timer()
            return
        if not self._is_idle_for_update():
            return
        self._stop_auto_update_timer()
        self.logger.info("Uygulama kullanılmıyor: güncelleme sessizce kuruluyor")
        self._start_silent_update()

    def _start_silent_update(self):
        info = self._pending_update
        if not info or self._update_in_progress() or self.update_dialog is not None:
            return
        if self._install_unsupported_reason():
            self.logger.info("Sessiz güncelleme atlandı: bu çalışma biçiminde kurulum desteklenmiyor")
            return
        self._silent_update = True
        self._start_update_download(info['version'], info['download_url'], info['file_size'], info['checksum'])

    def _notify_silent_failure(self, error_message: str):
        """Arka plan güncellemesi başarısız: pop-up yok; günlük + tepsi balonu (düğme yeniden denemek için durur)."""
        self.logger.error(f"Sessiz güncelleme başarısız: {error_message}")
        lang = get_active_language(self.config)
        text = t("update_auto_failed", lang)
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon
            if not self.tray_icon.show_message("TransferTCP", text, QSystemTrayIcon.MessageIcon.Warning):
                SystemToast.show("TransferTCP", text)
        except Exception:
            pass

    # ------------------------------------------------------------------ güncelleme penceresi
    def _open_update_dialog(self):
        """Kullanıcı düğmeye/tepsiye tıkladı: sürüm, boyut ve sürüm notlarıyla güncelleme penceresi (doğrudan kurmaz)."""
        from src.gui.update_dialog import UpdateDialog
        info = self._pending_update
        if not info:
            return
        existing = self.update_dialog
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        # Ana pencere gizliyken (tepsiden) pencere ona bağlanmaz: görev çubuğunda kendi düğmesi olur ve öne gelir
        parent = self.window if self._main_window_visible() else None
        dialog = UpdateDialog(
            version=info['version'],
            release_notes=info.get('release_notes', ''),
            is_mandatory=False,
            parent=parent,
            lang=get_active_language(self.config),
            file_size=info.get('file_size'),
        )
        self.update_dialog = dialog
        dialog.update_accepted.connect(self._on_dialog_update_accepted)
        dialog.update_deferred.connect(self._defer_update)
        dialog.update_cancelled.connect(self._cancel_update_download)
        # Süren bir (sessiz) indirme/kurulum varsa pencere doğru durumda açılsın
        phase = getattr(self, '_update_phase', 'idle')
        if phase == "downloading":
            dialog.show_downloading_state()
        elif phase == "installing":
            dialog.show_installing_state()

        def _bring_to_front():
            dialog.raise_()
            dialog.activateWindow()

        QTimer.singleShot(0, _bring_to_front)
        try:
            dialog.exec()
        finally:
            if self.update_dialog is dialog:
                self.update_dialog = None

    def _on_dialog_update_accepted(self):
        """Pencerede "Şimdi Güncelle" / "Tekrar dene": indirmeyi başlat (aktarım/yazma izni/kaynak denetimleri orada)."""
        info = self._pending_update
        if not info:
            return
        self._silent_update = False
        self._start_update_download(info['version'], info['download_url'], info['file_size'], info['checksum'])

    def _blocked_text(self, count: int) -> str:
        return t("update_blocked_inline", get_active_language(self.config)).format(count=count)

    def _start_update_download(self, version: str, download_url: str, file_size: int, checksum: str):
        """Start downloading the update"""
        import os
        lang = get_active_language(self.config)
        silent = bool(getattr(self, '_silent_update', False))
        dialog = self.update_dialog

        if self._update_in_progress():
            # Aynı anda ikinci indirme başlamaz
            self.logger.info("Güncelleme zaten sürüyor: ikinci indirme başlatılmadı")
            phase = getattr(self, '_update_phase', 'idle')
            if dialog is not None:
                if phase == 'downloading':
                    dialog.show_downloading_state()
                elif phase == 'installing':
                    dialog.show_installing_state()
                elif not silent:  # iptal edilen önceki indirmenin iş parçacığı henüz bitmedi
                    dialog.show_notice(t("update_busy_inline", lang))
            return

        # Kaynaktan çalışırken / Windows dışında otomatik kurulum yok: satır içi ileti, hiç indirme yok
        unsupported = self._install_unsupported_reason()
        if unsupported:
            self._update_failed(unsupported, retry=False)
            return

        # Son kez aktarım denetimi: aktarım sürerken indirme/kurulum başlamaz (pencere "indiriliyor"da takılmaz)
        active_transfers = self.transfer_manager.get_active_transfers()
        if active_transfers:
            if silent:
                self._silent_update = False
                self.logger.info("Sessiz güncelleme ertelendi: aktarım sürüyor")
            elif dialog is not None:
                dialog.show_notice(self._blocked_text(len(active_transfers)))
            return

        # Klasör yazılamıyorsa indirme boşa gitmesin
        exe = current_exe()
        try:
            self_update.check_writable(exe)
        except self_update.PackageError as exc:
            self.logger.error(f"Güncelleme için klasör yazılamıyor: {exc}")
            self._update_failed(t("update_no_write", lang).format(folder=os.path.dirname(exe)))
            return

        self.logger.info(f"Starting update download: {version}")
        self._downloading_version = version
        self._update_phase = "downloading"
        if dialog is not None:
            dialog.show_downloading_state()

        # Daha önce indirilip doğrulanmış (ama aktarım yüzünden kurulamamış) paket varsa yeniden indirilmez
        ready = getattr(self, '_ready_update', None)
        if ready and ready.get('version') == version and os.path.exists(ready.get('path') or ''):
            self.update_installer.downloaded_file = ready['path']
            self._on_download_complete(ready['path'])
            return

        # Start download in a separate thread to avoid blocking UI
        self.download_thread = DownloadThread(
            self.update_installer,
            download_url,
            file_size if file_size and file_size > 0 else None,
            checksum if checksum else None,
        )
        self.download_thread.start()

    def _on_download_progress(self, downloaded: int, total: int, speed_mbps: float):
        """Handle download progress update"""
        if self.update_dialog:
            self.update_dialog.update_download_progress(downloaded, total, speed_mbps)

    def _on_download_complete(self, file_path: str):
        """Handle download complete"""
        self.logger.info(f"Download complete: {file_path}")
        if getattr(self, '_update_phase', 'idle') != 'downloading':
            # İndirme biterken kullanıcı iptal etmişti: paket kurulmaz
            self.logger.info("Güncelleme iptal edilmişti: indirilen paket kullanılmıyor")
            self.update_installer.cleanup()
            return
        if not self.update_installer.last_verified:
            self.logger.warning("Güncelleme sunucu sağlama toplamıyla doğrulanamadı (sunucu vermedi)")
        self._ready_update = {'version': getattr(self, '_downloading_version', None), 'path': file_path}

        # Zorunlu güncellemede diyalog yoktur; kurulum yine de başlamalı (eskiden hiç başlamıyordu)
        if self.update_dialog:
            self.update_dialog.show_download_complete()
        QTimer.singleShot(300, self._start_installation)

    def _update_failed(self, message: str, retry: bool = True):
        """Güncelleme hatası (indirme, kurulum, ön denetim): QMessageBox YOK. Pencere açıksa satır içi hata
        ("Tekrar dene" ile) gösterilir; arka plan güncellemesinde günlük + tepsi balonu."""
        silent = bool(getattr(self, '_silent_update', False))
        self._silent_update = False
        dialog = self.update_dialog
        if dialog is not None:
            lang = get_active_language(self.config)
            dialog.show_error(localize_error(message, lang), retry=retry)
        elif silent:
            self._notify_silent_failure(message)

    def _on_download_failed(self, error_message: str):
        """Handle download failure"""
        self._update_phase = "idle"
        if error_message == "cancelled":
            # Kullanıcı iptali hata değildir
            self.logger.info("Update download cancelled by user")
            return
        self.logger.error(f"Download failed: {error_message}")
        self._ready_update = None
        # `_pending_update` SİLİNMEZ: zorunlu güncellemede de tepsi/düğme çalışır kalır, yeniden denenebilir
        self._update_failed(error_message)

    def _postpone_install_for_transfers(self, count: int):
        """Kurmadan hemen önce bir aktarım başlamış: kurma, (hazır paketle) beklemeye dön."""
        self._update_phase = "idle"
        if getattr(self, '_silent_update', False):
            self._silent_update = False
            self.logger.info("Sessiz güncelleme ertelendi: aktarım başladı (paket hazır, aktarımlar bitince kurulacak)")
        elif self.update_dialog is not None:
            self.update_dialog.show_notice(self._blocked_text(count))

    def _start_installation(self):
        """Start installation process"""
        if getattr(self, '_update_phase', 'idle') != 'downloading':
            return  # iptal edildi ya da durum değişti
        active_transfers = self.transfer_manager.get_active_transfers()
        if active_transfers:
            self._postpone_install_for_transfers(len(active_transfers))
            return

        self.logger.info("Starting installation...")
        self._update_phase = "installing"
        if self.update_dialog:
            self.update_dialog.show_installing_state()

        # Kurulum iş parçacığında (paketi aç, exe'yi değiştir, yeni sürümü başlat); sonuç sinyalle gelir
        self.install_thread = InstallThread(
            self.update_installer, self._main_window_visible(), self.update_checker.current_version
        )
        self.install_thread.start()

    def _quit_for_update(self):
        """Kurulum bitti: yeni sürüm bizi `--wait-pid` ile bekliyor; TEMİZ çık (aboutToQuit -> stop(), zorla öldürme yok)."""
        self.logger.info("Closing application for update restart...")
        self._quitting_for_update = True
        if self.update_dialog:
            self.update_dialog.show_install_complete()
        try:
            self.tray_icon.hide()  # eski tepsi simgesi çıkış sırasında hayalet olarak kalmasın
        except Exception:
            pass
        # Görünür pencereyle çıkış, E2E'de (A3) bazı koşularda Qt kapanışında yerel `access violation` (crash.log) verdi.
        # Yalnızca `hide()` yetmedi (FlexiKey'de 16/100 -> 5/100): `finished` sinyali çıkmaz, pencere Python sonlandırmasına kadar
        # yaşar. `hide()` closeEvent'i çağırmaz ("Kuruluyor" penceresi reddedemez); `deleteLater()` `exec()` sonunda işlenir.
        dialog = self.update_dialog
        if dialog is not None:
            self.update_dialog = None
            dialog.hide()
            dialog.deleteLater()
        QApplication.quit()
        # Kurulum sırasında açık "Güncelleme" penceresi kapanmayı reddeder ve Qt 6'da `quit()` görünür pencereleri kapatmayı dener:
        # reddeden olursa çıkış İPTAL olur (E2E'de eski süreç sonsuza dek yaşadı). `exit(0)` pencerelerden bağımsızdır
        # (aboutToQuit yine çalışır); çıkış yine de takılırsa sert çıkış (yeni sürüm bizi bekliyor).
        QCoreApplication.exit(0)
        from src.utils.update_policy import is_frozen
        if is_frozen():
            self_update.arm_exit_watchdog()

    def _on_install_started(self):
        """Handle installation started"""
        self.logger.info("Installation started")

    def _on_install_complete(self):
        """Handle installation complete"""
        self.logger.info("Installation complete")
        self._quit_for_update()

    def _on_install_failed(self, error_message: str):
        """Handle installation failure"""
        self.logger.error(f"Installation failed: {error_message}")
        self._update_phase = "idle"
        self._ready_update = None
        try:
            self.update_installer.cleanup()
        except Exception:
            pass
        self._update_failed(error_message)

    def _defer_update(self):
        """Handle user deferring update"""
        self.logger.info("User deferred update")
        if hasattr(self, '_pending_update') and self._pending_update:
            self.config.set(
                'advanced',
                'declined_update_version',
                self._pending_update['version']
            )
            self.tray_icon.set_update_available(True, self._pending_update['version'])

    def show_pending_update(self):
        """Başlık çubuğundaki düğmeden / tepsiden seçilen güncelleme penceresini aç."""
        if not self._pending_update:
            return
        self._open_update_dialog()

    def _cancel_update_download(self):
        """Handle user cancelling update download (düğme, Esc ya da X)"""
        self.logger.info("User cancelled update download")
        self._update_phase = "idle"
        # İndirme döngüsü bayrağı görüp kendi dosyasını siler (açık dosyayı buradan silmeyi denemeyiz)
        self.update_installer.cancel_download()
        version = getattr(self, '_downloading_version', None)
        if version:
            # İptal de bir "şimdi değil"dir: otomatik kurulum o sürümü arkadan yeniden indirmeye kalkmasın
            self.config.set('advanced', 'declined_update_version', version)

    def _handle_file_received_gui(self, transfer: Transfer):
        """Handle file received - main thread"""
        try:
            # Add to UI first (so user sees incoming transfer)
            if transfer and hasattr(transfer, 'filename') and hasattr(transfer, 'device_name'):
                # Gönderici aynı kimlikle yeniden denedi (önceki deneme başarısız bitmişti): yeni denemenin
                # sonucu da işlenmeli, yoksa başarılı tekrar geçmişe/bildirime/klasör sayacına yansımaz
                self._handled_completion_ids.discard(transfer.transfer_id)
                self.window.add_transfer(transfer)
                self._find_folder_transfer_info(transfer)
                lang = get_active_language(self.config)
                self.window.show_status_message(
                    t("receiving_file", lang).format(
                        filename=transfer.filename, device=transfer.device_name
                    )
                )
        except Exception as e:
            self.logger.exception(f"Error in _handle_file_received_gui: {e}")

    # Window event handlers
    def _show_window(self):
        """Show main window"""
        # Show window first
        self.window.showNormal()
        self.window.show()
        self.window.activateWindow()
        self.window.raise_()

        # Tepsiden dönünce listeyi sıfırlama — boş durum (Cihaz Ekle) anlık görünmesin.
        try:
            if hasattr(self.window, "device_list"):
                self.window.device_list._update_all_widget_styles()
            self.window.update()
            self.window.repaint()
            self.logger.debug("Window restored from tray - UI refreshed")
        except Exception as e:
            self.logger.error(f"Error refreshing UI on window restore: {e}")

    def _quit_application(self):
        """Quit application"""
        self.stop()
        QApplication.quit()
