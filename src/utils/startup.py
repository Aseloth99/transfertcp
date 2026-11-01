"""Başlangıçta otomatik çalıştırma (autostart) — Windows, macOS ve Linux.

* Windows : HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run değeri (eski davranış AYNEN korunur).
* macOS   : ~/Library/LaunchAgents/com.macik.transfertcp.plist (RunAtLoad). `launchctl` çağrılmaz:
            LaunchAgents oturum açılışında yüklenir.
* Linux   : $XDG_CONFIG_HOME/autostart/transfertcp.desktop (XDG Autostart).
macOS ve Linux dosyalarını FlexiKey ve MediaCompressor ile ORTAK `autostart_unix` modülü yazar; burada yalnızca
hangi komutun yazılacağı (`launch_argv`: paketli exe, AppImage, kaynaktan çalışma) ve Windows kaydı kalır.

Her platform bir "backend" nesnesidir; modül düzeyindeki `add_to_startup` / `remove_from_startup` /
`is_in_startup` / `update_startup_path_if_needed` işlevleri geçerli platformun backend'ini kullanır.
Testlerde backend (veya `winreg` benzeri sahte modül / geçici HOME) enjekte edilir; gerçek kayıt
defterine hiç dokunulmaz. Windows'a özgü `winreg` yalnızca Windows backend'i içinde, tembel içe aktarılır.
"""

from __future__ import annotations

import os
import sys
from os.path import abspath, isfile, join
from typing import List, Optional

from . import autostart_unix
from .logger import get_logger
from .paths import APP_ID, BUNDLE_ID
from .platform_utils import current_platform

MINIMIZED_FLAG = "--minimized"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Eski sürümlerin bıraktığı LaunchAgent'lar: bundle kimlikli etiket ve ilk sürümün etiketi (yenisi yazılırken silinir).
_LEGACY = {"legacy_plist_labels": (BUNDLE_ID, "com.transfertcp"), "legacy_desktop_names": ()}
_COMMENT = "LAN dosya aktarımı / LAN file transfer"


# --------------------------------------------------------------------------- ortak yardımcılar

def _parse_run_value_path(registry_value: str) -> str:
    """Run anahtarındaki EXE yolunu ayıkla (tırnak ve --minimized dahil)"""
    value = (registry_value or '').strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        if end > 0:
            return value[1:end]
    return value.split(' --')[0].strip().strip('"')


def _pythonw_executable() -> str:
    """GUI uygulaması için konsolsuz Python yorumlayıcısı."""
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        candidate = exe[:-10] + "pythonw.exe"
        if isfile(candidate):
            return candidate
    return exe


def _entry_path() -> str:
    """Başlangıç kaydına yazılacak program yolu."""
    if getattr(sys, "frozen", False):
        return abspath(sys.executable)
    from .paths import get_application_path

    return abspath(join(get_application_path(), "main.py"))


def build_startup_command(minimized: bool = True, app_path: Optional[str] = None) -> str:
    """Windows Run kaydı için başlatma komutu oluştur."""
    if app_path is not None:
        cmd = app_path if app_path.startswith('"') else f'"{app_path}"'
    elif getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        cmd = f'"{_pythonw_executable()}" "{_entry_path()}"'

    if minimized and MINIMIZED_FLAG not in cmd:
        cmd = f"{cmd} {MINIMIZED_FLAG}"
    return cmd


def _registry_uses_console_python(registry_value: str) -> bool:
    return "python.exe" in (registry_value or "").lower()


def launch_argv(minimized: bool = True, app_path: Optional[str] = None, *,
                frozen: Optional[bool] = None, executable: Optional[str] = None,
                entry: Optional[str] = None, env=None) -> List[str]:
    """macOS/Linux için başlatma argv'si: [yürütülebilir, (main.py,) --minimized].

    * `app_path` verilirse yalnızca o (tek yürütülebilir).
    * Paketlenmiş uygulama (PyInstaller): kendi yürütülebilir dosyası (macOS: .app içindeki
      Contents/MacOS/TransferTCP; Linux AppImage: `$APPIMAGE`, çünkü sys.executable geçici bağlama noktasıdır).
    * Kaynaktan çalışma: yorumlayıcı + main.py.
    """
    env = os.environ if env is None else env
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = executable if executable is not None else abspath(sys.executable)
    if app_path is not None:
        argv = [app_path]
    elif is_frozen:
        appimage = env.get("APPIMAGE")
        argv = [appimage if appimage and isfile(appimage) else exe]
    else:
        argv = [exe, entry if entry is not None else _entry_path()]
    if minimized and MINIMIZED_FLAG not in argv:
        argv.append(MINIMIZED_FLAG)
    return argv


# --------------------------------------------------------------------------- backend'ler

class StartupBackend:
    """Arayüz: her platform kendi kalıcı kaydını yönetir. Tüm yöntemler başarısızlıkta False döner."""

    name = "none"

    def is_enabled(self, app_name: str) -> bool:
        return False

    def enable(self, app_name: str, app_path: Optional[str], minimized: bool) -> bool:
        return False

    def disable(self, app_name: str) -> bool:
        return False

    def update_if_needed(self, app_name: str, minimized: bool) -> bool:
        return False


class WindowsRunKeyBackend(StartupBackend):
    """HKCU Run anahtarı. `winreg` benzeri bir modül enjekte edilebilir (testler gerçek kayıt defterine dokunmaz)."""

    name = "windows-run-key"

    def __init__(self, winreg_module=None):
        self._winreg = winreg_module

    def _reg(self):
        if self._winreg is None:
            import winreg  # yalnızca Windows'ta ve yalnızca kullanılırken
            self._winreg = winreg
        return self._winreg

    def is_enabled(self, app_name: str) -> bool:
        try:
            reg = self._reg()
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_READ)
            reg.QueryValueEx(key, app_name)
            reg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def enable(self, app_name: str, app_path: Optional[str], minimized: bool) -> bool:
        try:
            reg = self._reg()
            launch_cmd = build_startup_command(minimized=minimized, app_path=app_path)
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_SET_VALUE)
            reg.SetValueEx(key, app_name, 0, reg.REG_SZ, launch_cmd)
            reg.CloseKey(key)
            return True
        except Exception as e:
            get_logger().warning(f"Failed to add to Windows startup: {e}")
            return False

    def disable(self, app_name: str) -> bool:
        try:
            reg = self._reg()
            key = reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_SET_VALUE)
            reg.DeleteValue(key, app_name)
            reg.CloseKey(key)
            return True
        except FileNotFoundError:
            return True
        except Exception as e:
            get_logger().warning(f"Failed to remove from Windows startup: {e}")
            return False

    def update_if_needed(self, app_name: str, minimized: bool) -> bool:
        """Kayıtlı yol/bayrak güncel değilse (program taşındı, konsollu python.exe...) kaydı yeniler."""
        try:
            if not self.is_enabled(app_name):
                return False
            reg = self._reg()
            from os.path import normpath

            current_path = build_startup_command(minimized=minimized)
            current_exe = _entry_path()

            key = reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_READ)
            registry_path, _ = reg.QueryValueEx(key, app_name)
            reg.CloseKey(key)

            registry_exe = _parse_run_value_path(registry_path)
            path_changed = normpath(registry_exe).lower() != normpath(current_exe).lower()

            registry_has_minimized = MINIMIZED_FLAG in (registry_path or "")
            flag_changed = registry_has_minimized != bool(minimized)
            console_python = _registry_uses_console_python(registry_path)
            command_changed = (registry_path or "").strip() != current_path.strip()

            if path_changed or flag_changed or console_python or command_changed:
                key = reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_SET_VALUE)
                reg.SetValueEx(key, app_name, 0, reg.REG_SZ, current_path)
                reg.CloseKey(key)
                return True
            return False
        except Exception as e:
            get_logger().warning(f"Failed to update startup path: {e}")
            return False


class _UnixBackend(StartupBackend):
    """macOS/Linux: ortak `autostart_unix` modülüne ince köprü (FlexiKey ve MediaCompressor aynı modülü kullanır).
    Dosya içeriği, yol güvenliği, atomik yazma ve eski kayıt temizliği orada; burada yalnızca hangi komutun yazılacağı seçilir."""

    _platform = ""

    def __init__(self, home: Optional[str] = None, argv_factory=None, env=None, config_home: Optional[str] = None):
        self._home = home
        self._argv_factory = argv_factory or launch_argv
        self._env = env
        self._config_home = config_home

    def _where(self) -> dict:
        return {"platform": self._platform, "home": self._home, "config_home": self._config_home,
                "env": self._env, **_LEGACY}

    def _launch(self, app_path: Optional[str], minimized: bool):
        argv = self._argv_factory(minimized, app_path)
        return argv[0], argv[1:]

    def is_enabled(self, app_name: str) -> bool:
        return autostart_unix.is_enabled(app_name, **self._where())

    def enable(self, app_name: str, app_path: Optional[str], minimized: bool) -> bool:
        try:
            exe, args = self._launch(app_path, minimized)
            ok = autostart_unix.set_enabled(app_name, exe, args, True, display_name=app_name, comment=_COMMENT,
                                            **self._where())
        except Exception as e:
            get_logger().warning(f"Failed to add to {self.name}: {e}")
            return False
        if not ok:
            get_logger().warning(f"Failed to add to {self.name}")
        return ok

    def disable(self, app_name: str) -> bool:
        try:
            ok = autostart_unix.set_enabled(app_name, "", (), False, **self._where())
        except Exception as e:
            get_logger().warning(f"Failed to remove from {self.name}: {e}")
            return False
        if not ok:
            get_logger().warning(f"Failed to remove from {self.name}")
        return ok

    def update_if_needed(self, app_name: str, minimized: bool) -> bool:
        """Kayıt açıksa ve içeriği bu çalıştırmayla uyuşmuyorsa (program taşındı, bayrak değişti, eski etiket kaldı)
        yeniler; kapalı/bozuk kayda dokunmaz. Döner: yenilendiyse True."""
        try:
            if not autostart_unix.is_enabled(app_name, **self._where()):
                return False
            exe, args = self._launch(None, minimized)
            if autostart_unix.is_current(app_name, exe, args, display_name=app_name, comment=_COMMENT, **self._where()):
                return False
            return autostart_unix.set_enabled(app_name, exe, args, True, display_name=app_name, comment=_COMMENT,
                                              **self._where())
        except Exception as e:
            get_logger().warning(f"Failed to update startup path: {e}")
            return False


class MacLaunchAgentBackend(_UnixBackend):
    """~/Library/LaunchAgents/com.macik.<ad>.plist (RunAtLoad). `home` enjekte edilebilir (testlerde geçici HOME)."""

    name = "macos-launchagent"
    _platform = "darwin"

    def __init__(self, home: Optional[str] = None, argv_factory=None):
        super().__init__(home=home, argv_factory=argv_factory)

    def plist_path(self, app_name: str) -> str:
        return str(autostart_unix.plist_path(app_name, self._home))


class LinuxAutostartBackend(_UnixBackend):
    """$XDG_CONFIG_HOME/autostart/<ad>.desktop. `config_home` / `env` enjekte edilebilir (testlerde geçici dizin)."""

    name = "linux-xdg-autostart"
    _platform = "linux"

    def __init__(self, config_home: Optional[str] = None, argv_factory=None, env=None):
        super().__init__(argv_factory=argv_factory, env=env, config_home=config_home)

    def desktop_path(self, app_name: str) -> str:
        return str(autostart_unix.desktop_path(app_name, self._home, config_home=self._config_home, env=self._env))


def get_backend(platform: Optional[str] = None) -> Optional[StartupBackend]:
    """Geçerli platformun backend'i (desteklenmeyen platformda None)."""
    kind = current_platform(platform)
    if kind == "windows":
        return WindowsRunKeyBackend()
    if kind == "macos":
        return MacLaunchAgentBackend()
    if kind == "linux":
        return LinuxAutostartBackend()
    return None


# --------------------------------------------------------------------------- genel API

def add_to_startup(app_name: str = APP_ID, app_path: Optional[str] = None, minimized: bool = True,
                   *, backend: Optional[StartupBackend] = None) -> bool:
    """Uygulamayı sistem başlangıcına ekle (Windows, macOS, Linux)."""
    backend = backend if backend is not None else get_backend()
    if backend is None:
        return False
    return backend.enable(app_name, app_path, minimized)


def remove_from_startup(app_name: str = APP_ID, *, backend: Optional[StartupBackend] = None) -> bool:
    """Uygulamayı sistem başlangıcından kaldır (kayıt yoksa da başarılı sayılır)."""
    backend = backend if backend is not None else get_backend()
    if backend is None:
        return False
    return backend.disable(app_name)


def is_in_startup(app_name: str = APP_ID, *, backend: Optional[StartupBackend] = None) -> bool:
    """Uygulama sistem başlangıcında kayıtlı mı?"""
    backend = backend if backend is not None else get_backend()
    if backend is None:
        return False
    return backend.is_enabled(app_name)


def update_startup_path_if_needed(app_name: str = APP_ID, minimized: bool = True,
                                  *, backend: Optional[StartupBackend] = None) -> bool:
    """Kayıtlı başlatma komutu bu çalıştırmayla uyuşmuyorsa (program taşındı, bayraklar değişti) yeniler.

    Döner: güncelleme gerekti ve yapıldıysa True.
    """
    backend = backend if backend is not None else get_backend()
    if backend is None:
        return False
    return backend.update_if_needed(app_name, minimized)
