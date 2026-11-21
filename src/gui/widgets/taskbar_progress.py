"""Windows görev çubuğu düğmesinde aktarım ilerlemesi (ITaskbarList3) — ek bağımlılık yok, saf ctypes COM.

Yalnızca Windows'ta çalışır; başka platformda ya da COM nesnesi alınamazsa her çağrı sessizce hiçbir şey yapmaz.
Aynı değer yeniden gönderilmez (ilerleme sinyali saniyede onlarca kez gelir).
"""

from __future__ import annotations

import sys

# TBPFLAG
TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8

_SCALE = 1000  # binde bir çözünürlük: daha sık güncellemek görünür fark yaratmaz


class _ComTaskbar:
    """ITaskbarList3'ün kullandığımız iki yöntemi (vtable 9: SetProgressValue, 10: SetProgressState)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        ole32 = ctypes.windll.ole32

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        def guid(text: str) -> GUID:
            value = GUID()
            ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
            return value

        clsid = guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")  # CLSID_TaskbarList
        iid = guid("{ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf}")    # IID_ITaskbarList3
        ole32.CoInitialize(None)  # Qt GUI iş parçacığı zaten OLE başlatmıştır; ikinci çağrı zararsızdır (S_FALSE)
        ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr))  # CLSCTX_INPROC_SERVER
        if hr != 0 or not ptr.value:
            raise OSError(f"ITaskbarList3 alınamadı (0x{hr & 0xFFFFFFFF:08X})")
        self._ptr = ptr
        vtable = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        proto = ctypes.WINFUNCTYPE
        self._hr_init = proto(ctypes.c_long, ctypes.c_void_p)(vtable[3])
        self._set_value = proto(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_ulonglong,
                                ctypes.c_ulonglong)(vtable[9])
        self._set_state = proto(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_int)(vtable[10])
        self._hr_init(ptr)

    def set_value(self, hwnd: int, done: int, total: int) -> None:
        self._set_value(self._ptr, hwnd, done, total)

    def set_state(self, hwnd: int, flag: int) -> None:
        self._set_state(self._ptr, hwnd, flag)


class TaskbarProgress:
    """`update(fraction, paused)` / `clear()`; `hwnd_provider()` pencerenin yerel tutamacını verir.

    `backend`: testlerde sahte nesne (set_value/set_state); verilmezse Windows'ta COM nesnesi ilk kullanımda yaratılır."""

    def __init__(self, hwnd_provider, backend=None) -> None:
        self._hwnd_provider = hwnd_provider
        self._backend = backend
        self._failed = False
        self._last: tuple[int, int] | None = None  # (durum, binde değer)

    def _com(self):
        if self._backend is None and not self._failed:
            if sys.platform != "win32":
                self._failed = True
                return None
            try:
                self._backend = _ComTaskbar()
            except Exception:
                self._failed = True
        return self._backend

    def _send(self, state: int, value: int) -> None:
        if self._last == (state, value):
            return
        backend = self._com()
        if backend is None:
            return
        try:
            hwnd = int(self._hwnd_provider() or 0)
        except Exception:
            hwnd = 0
        if not hwnd:
            return
        try:
            backend.set_state(hwnd, state)
            if state in (TBPF_NORMAL, TBPF_PAUSED, TBPF_ERROR):
                backend.set_value(hwnd, value, _SCALE)
            self._last = (state, value)
        except Exception:
            pass

    def update(self, fraction: float, paused: bool = False) -> None:
        value = max(0, min(_SCALE, int(round(float(fraction) * _SCALE))))
        self._send(TBPF_PAUSED if paused else TBPF_NORMAL, value)

    def clear(self) -> None:
        self._send(TBPF_NOPROGRESS, 0)

    def forget(self) -> None:
        """Pencere yeniden gösterildi (görev çubuğu düğmesi yeniden yaratıldı): sonraki değer yeniden gönderilsin."""
        self._last = None

    def state(self) -> tuple[int, int] | None:
        """Son gönderilen (durum, binde değer); testler ve tanı için."""
        return self._last
