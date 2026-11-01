"""TransferTCP crash logger — yakalanmamış hataları ve native çökmeleri kaydeder."""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from pathlib import Path

_log_handle = None


def crash_log_path() -> Path:
    import tempfile

    from .paths import get_user_log_dir

    try:
        folder = Path(get_user_log_dir())
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "TransferTCP" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
    return folder / "crash.log"


def install_crash_log() -> Path:
    global _log_handle
    path = crash_log_path()
    if _log_handle is not None:
        return path
    try:
        _log_handle = path.open("a", encoding="utf-8", errors="replace")
        faulthandler.enable(_log_handle, all_threads=True)
    except Exception:
        pass

    def _hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            if _log_handle is not None:
                _log_handle.write(text + "\n")
                _log_handle.flush()
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
    return path
