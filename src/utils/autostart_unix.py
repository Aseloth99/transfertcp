"""Açılışta Başlat (macOS/Linux): LaunchAgent plist'i ve XDG autostart .desktop dosyası (saf fonksiyonlar).

* macOS : ~/Library/LaunchAgents/com.macik.<uygulama>.plist  (RunAtLoad, yalnızca grafik oturumda: Aqua;
          plistlib ile üretilir, XML kaçışı doğru)
* Linux : $XDG_CONFIG_HOME/autostart/<uygulama>.desktop (XDG_CONFIG_HOME yoksa ~/.config/autostart/);
          Exec satırı XDG kurallarıyla tırnaklanır/kaçırılır
* Windows (platform == "win32"): HİÇBİR ŞEY YAPMAZ, False döner; uygulamaların mevcut HKCU Run kodu aynen kalır.
Yol güvenliği: yalnızca home (ya da XDG kökü) altına yazılır, altındaki hiçbir dizin/dosya sembolik bağ olamaz (bağ
takip edilmez, reddedilir), yazma geçici dosya + os.replace ile atomiktir, uygulama adı dosya adına güvenli biçimde
indirgenir. `launchctl` çağrılmaz: LaunchAgent bir sonraki oturum açışında devreye girer.
FlexiKey, MediaCompressor ve TransferTCP bu dosyanın birebir kopyasını kullanır.
"""

from __future__ import annotations

import os
import plistlib
import re
import sys
import tempfile
from pathlib import Path

LABEL_PREFIX = "com.macik."
_UNSAFE_EXEC_CHARS = set(' \t\n"\'\\><~|&;$*?#()`')


def _kind(platform: str | None) -> str | None:
    platform = platform or sys.platform
    if platform == "darwin":
        return "darwin"
    if platform.startswith("linux"):
        return "linux"
    return None  # win32 ve bilinmeyenler: bu modül dokunmaz


def _slug(app) -> str:
    """Uygulama adı -> dosya adı parçası: küçük harf, [a-z0-9._-]; yol ayırıcı/".." mümkün değil."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(app).strip().lower()).strip(".-_")
    if not slug:
        raise ValueError("geçersiz uygulama adı")
    return slug


def _home(home) -> Path:
    return Path(home) if home is not None else Path(os.path.expanduser("~"))


def _xdg_base(home, config_home, env) -> Path | None:
    """Linux'ta yapılandırma kökü: açıkça verilen `config_home`, ya da (gerçek home'da) mutlak bir `$XDG_CONFIG_HOME`;
    yoksa None (= ~/.config). Enjekte edilmiş bir home (testler) ortamdaki XDG'ye asla kaçmaz."""
    if config_home is not None:
        return Path(config_home)
    if home is not None or _home(None) != Path(os.path.expanduser("~")):
        return None
    value = ((os.environ if env is None else env).get("XDG_CONFIG_HOME") or "").strip()
    return Path(value) if value and os.path.isabs(value) else None


def plist_label(app_id: str) -> str:
    return LABEL_PREFIX + _slug(app_id)


def plist_path(app_id: str, home=None) -> Path:
    return _home(home) / "Library" / "LaunchAgents" / f"{plist_label(app_id)}.plist"


def desktop_path(app_id: str, home=None, *, config_home=None, env=None) -> Path:
    xdg = _xdg_base(home, config_home, env)
    if xdg is not None:
        return xdg / "autostart" / f"{_slug(app_id)}.desktop"
    return _home(home) / ".config" / "autostart" / f"{_slug(app_id)}.desktop"


# ---------------------------------------------------------------------------------------------------------------
# Üretim (saf)
# ---------------------------------------------------------------------------------------------------------------
def render_plist(label: str, program_args) -> str:
    """LaunchAgent plist XML metni (RunAtLoad; yalnızca grafik oturumda başlar). plistlib `& < > "` gibi karakterleri
    doğru kaçırır."""
    data = {
        "Label": str(label),
        "ProgramArguments": [str(a) for a in program_args],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",  # SSH gibi grafiksiz oturumlarda pencereli uygulama başlatılmaz
    }
    return plistlib.dumps(data, fmt=plistlib.FMT_XML, sort_keys=True).decode("utf-8")


def desktop_escape(value) -> str:
    """.desktop "string" değeri: `\\` -> `\\\\`, satır sonu/sekme kaçırılır, diğer denetim karakterleri atılır."""
    out = []
    for ch in str(value):
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32 or ord(ch) == 0x7F:
            continue
        else:
            out.append(ch)
    return "".join(out)


def quote_exec_arg(arg) -> str:
    """Exec bağımsız değişkeni (XDG kuralı): özel karakter varsa çift tırnakla, içte `" ` $ \\` ters eğik çizgiyle
    kaçırılır; alan kodu karışmasın diye `%` her zaman `%%`. (Satır değeri kaçışı `render_desktop`'ta ayrıca yapılır.)"""
    text = str(arg).replace("%", "%%")
    if text and not (set(text) & _UNSAFE_EXEC_CHARS):
        return text
    escaped = "".join("\\" + ch if ch in '"`$\\' else ch for ch in text)
    return f'"{escaped}"'


def build_exec_line(exe_path, args=()) -> str:
    return " ".join(quote_exec_arg(part) for part in [exe_path, *args])


def render_desktop(name: str, exec_line: str, comment: str = "") -> str:
    """XDG autostart girdisi. `exec_line`: `build_exec_line` çıktısı (tırnaklanmış); satır kaçışı burada uygulanır."""
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={desktop_escape(name)}",
    ]
    if comment:
        lines.append(f"Comment={desktop_escape(comment)}")
    lines += [
        f"Exec={desktop_escape(exec_line)}",
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
        "",
    ]
    return "\n".join(lines)


def _render(kind: str, app_name, exe_path, args, display_name, comment) -> str:
    args = [str(a) for a in args]
    if kind == "darwin":
        return render_plist(plist_label(app_name), [str(exe_path), *args])
    return render_desktop(display_name or str(app_name), build_exec_line(exe_path, args), comment)


# ---------------------------------------------------------------------------------------------------------------
# Disk işlemleri (güvenli)
# ---------------------------------------------------------------------------------------------------------------
def _safe_dir(home: Path, parts: tuple[str, ...], create: bool) -> Path | None:
    """home/<parts…> dizinini döndürür; yol üzerinde sembolik bağ varsa ya da home dışına çıkıyorsa None."""
    try:
        real_home = home.resolve()
        cur = home
        for part in parts:
            cur = cur / part
            if cur.is_symlink():
                return None
            if not cur.exists():
                if not create:
                    return home.joinpath(*parts)  # henüz yok (var olan kısım güvenli)
                cur.mkdir(mode=0o755)
            elif not cur.is_dir():
                return None
        real = cur.resolve()
        if real != real_home and real_home not in real.parents:
            return None
        return cur
    except OSError:
        return None


def _write(path: Path, text: str) -> bool:
    if path.is_symlink() or path.is_dir():
        return False
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return True  # idempotent: aynı içerik, yeniden yazma
    except (OSError, UnicodeDecodeError):
        pass
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(tmp, 0o644)  # launchd, grup/herkes tarafından yazılabilir plist'i reddeder
        os.replace(tmp, path)
        return True
    except OSError:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def _remove(path: Path) -> bool:
    """Yoksa True; sembolik bağ/dizin ise dokunmaz ve False; normal dosyayı siler."""
    if path.is_symlink():
        return False
    if not path.exists():
        return True
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _locations(app_name: str, kind: str, base: Path, legacy_plist_labels, legacy_desktop_names, xdg=None):
    """(kök, kökten klasör parçaları, asıl dosya adı, eski dosya adları)."""
    if kind == "darwin":
        main = f"{plist_label(app_name)}.plist"
        legacy = [f"{label}.plist" for label in legacy_plist_labels]
        return base, ("Library", "LaunchAgents"), main, legacy
    main = f"{_slug(app_name)}.desktop"
    legacy = [f"{name}.desktop" for name in legacy_desktop_names]
    if xdg is not None:
        return xdg, ("autostart",), main, legacy
    return base, (".config", "autostart"), main, legacy


def _safe_name(name: str) -> bool:
    return bool(name) and name == os.path.basename(name) and ".." not in name and "/" not in name and "\\" not in name


def _where(app_name, kind, home, config_home, env, legacy_plist_labels, legacy_desktop_names):
    xdg = _xdg_base(home, config_home, env) if kind == "linux" else None
    return xdg, _locations(app_name, kind, _home(home), legacy_plist_labels, legacy_desktop_names, xdg)


def set_enabled(app_name, exe_path, args=(), enabled=True, platform=None, home=None, *, display_name=None,
                comment="", legacy_plist_labels=(), legacy_desktop_names=(), config_home=None, env=None) -> bool:
    """Açılışta Başlat'ı açar/kapatır. Son durum istenenle aynıysa True (idempotent); desteklenmeyen platform
    (Windows dahil), güvensiz yol ya da yazma hatasında False. `legacy_*`: eski sürümlerin bıraktığı dosya adları;
    açarken/kapatırken (yalnızca normal dosyalarsa) kaldırılır, çift başlatma olmasın. `config_home`: Linux'ta
    yapılandırma kökünü açıkça verir (yoksa gerçek home'da $XDG_CONFIG_HOME, o da yoksa ~/.config)."""
    kind = _kind(platform)
    if kind is None:
        return False
    try:
        xdg, (root, parts, main, legacy) = _where(app_name, kind, home, config_home, env,
                                                  legacy_plist_labels, legacy_desktop_names)
        if enabled and xdg is not None:
            xdg.mkdir(parents=True, exist_ok=True)  # XDG kökü henüz yoksa oluştur (kapatırken hiçbir şey oluşturulmaz)
        directory = _safe_dir(root, parts, create=bool(enabled))
        if directory is None:
            return False
        if not directory.exists():  # kapatırken klasör hiç yok: yapılacak bir şey yok
            return True
        target = directory / main
        ok = True
        for name in legacy:
            if _safe_name(name) and name != main:
                ok = _remove(directory / name) and ok
        if not enabled:
            return _remove(target) and ok
        return _write(target, _render(kind, app_name, exe_path, args, display_name, comment)) and ok
    except (ValueError, OSError):
        return False


def is_enabled(app_name, platform=None, home=None, *, legacy_plist_labels=(), legacy_desktop_names=(),
               config_home=None, env=None) -> bool:
    """Açılışta Başlat dosyası var ve geçerli mi? (Linux'ta Hidden=true / X-GNOME-Autostart-enabled=false kapalı sayılır.)"""
    kind = _kind(platform)
    if kind is None:
        return False
    try:
        _, (root, parts, main, legacy) = _where(app_name, kind, home, config_home, env,
                                                legacy_plist_labels, legacy_desktop_names)
        directory = _safe_dir(root, parts, create=False)
        if directory is None or not directory.is_dir():
            return False
        for name in [main, *[n for n in legacy if _safe_name(n)]]:
            path = directory / name
            if path.is_symlink() or not path.is_file():
                continue
            if _valid(kind, path):
                return True
    except (ValueError, OSError):
        return False
    return False


def is_current(app_name, exe_path, args=(), platform=None, home=None, *, display_name=None, comment="",
               legacy_plist_labels=(), legacy_desktop_names=(), config_home=None, env=None) -> bool:
    """Kayıt tam olarak `set_enabled`'ın şimdi yazacağı içerikte mi (ve eski adlı artık dosya kalmamış mı)? Hayırsa
    (program taşındı, bayrak değişti, eski etiket kaldı...) `set_enabled` ile yenilenmelidir. Kayıt yoksa False."""
    kind = _kind(platform)
    if kind is None:
        return False
    try:
        _, (root, parts, main, legacy) = _where(app_name, kind, home, config_home, env,
                                                legacy_plist_labels, legacy_desktop_names)
        directory = _safe_dir(root, parts, create=False)
        if directory is None or not directory.is_dir():
            return False
        target = directory / main
        if target.is_symlink() or not target.is_file():
            return False
        if target.read_text(encoding="utf-8") != _render(kind, app_name, exe_path, args, display_name, comment):
            return False
        for name in legacy:
            if _safe_name(name) and name != main:
                leftover = directory / name
                if leftover.is_symlink() or leftover.exists():
                    return False
        return True
    except (ValueError, OSError, UnicodeDecodeError):
        return False


def _valid(kind: str, path: Path) -> bool:
    try:
        if kind == "darwin":
            data = plistlib.loads(path.read_bytes())
            return bool(data.get("RunAtLoad")) and not data.get("Disabled") and bool(data.get("ProgramArguments"))
        has_exec = False
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.lower() == "hidden=true" or line.lower() == "x-gnome-autostart-enabled=false":
                return False
            if line.startswith("Exec="):
                has_exec = True
        return has_exec
    except (OSError, ValueError, UnicodeDecodeError, plistlib.InvalidFileException):
        return False
