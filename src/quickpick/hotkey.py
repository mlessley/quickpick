import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}

NAMED_KEYS = {
    "space": 0x20,
    "printscreen": 0x2C,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "backspace": 0x08,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int


def _virtual_key(name: str) -> int | None:
    if name in NAMED_KEYS:
        return NAMED_KEYS[name]
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1
    return None


def parse_hotkey(spec: str, require_modifier: bool = True) -> Hotkey:
    *modifier_names, key_name = [part.strip() for part in spec.lower().split("+")]
    if require_modifier and not modifier_names:
        raise ValueError(f"hotkey {spec!r} needs at least one modifier")
    modifiers = 0
    for name in modifier_names:
        if name not in MODIFIERS:
            raise ValueError(f"hotkey {spec!r} has unknown modifier {name!r}")
        modifiers |= MODIFIERS[name]
    vk = _virtual_key(key_name)
    if vk is None:
        raise ValueError(f"hotkey {spec!r} has unknown key {key_name!r}")
    return Hotkey(modifiers=modifiers, vk=vk)


class HotkeyRegistrationError(Exception):
    pass


class HotkeyListener:
    """Registers a global hotkey via RegisterHotKey (ADR 0001) on a dedicated thread.

    on_press runs on the listener thread, not the caller's, so UI work must be marshalled
    back to the UI thread.
    """

    _ID = 1

    def __init__(self, spec: str, on_press: Callable[[], None]) -> None:
        self.spec = spec
        self.hotkey = parse_hotkey(spec)
        self.on_press = on_press
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: HotkeyRegistrationError | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._error:
            raise self._error

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join()

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._thread_id = ctypes.WinDLL("kernel32").GetCurrentThreadId()
        modifiers = self.hotkey.modifiers | MOD_NOREPEAT
        if not user32.RegisterHotKey(None, self._ID, modifiers, self.hotkey.vk):
            reason = ctypes.FormatError(ctypes.get_last_error()).strip()
            self._error = HotkeyRegistrationError(
                f"Could not register hotkey {self.spec!r}: {reason}"
            )
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.on_press()
        finally:
            user32.UnregisterHotKey(None, self._ID)
