"""Switching to a running app's window from the popup (Ctrl+O Outlook, Ctrl+T Teams)."""

import ntpath
import re
from dataclasses import dataclass

import pywintypes
import win32api
import win32con
import win32gui
import win32process

from quickpick.windows import activate_window

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

APP_KEY_MODIFIERS = {"ctrl": "Control", "alt": "Alt"}
# Popup keys an app can't take (Ctrl+Tab / Ctrl+Enter are already unsupported app keys)
RESERVED_APP_KEYS = {
    "ctrl+n", "ctrl+s", "ctrl+b", "ctrl+h", "ctrl+p", "ctrl+d", "ctrl+q",
    "ctrl+l", "ctrl+e", "ctrl+f", "ctrl+u", "ctrl+i",
    "ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "f2",
}  # fmt: skip
FUNCTION_KEY = re.compile(r"f([1-9]|1[0-9]|2[0-4])")


@dataclass(frozen=True)
class Window:
    hwnd: int
    program: str  # the executable's file name, e.g. "OUTLOOK.EXE"
    title: str
    visible: bool  # minimized windows are still visible; closed-to-tray ones aren't
    minimized: bool
    owned: bool  # dialogs and pop-outs owned by another window
    tool: bool  # tool windows, which the taskbar doesn't show either


def normalize_app_key(spec: str) -> str:
    """The canonical spelling of an app key ("Ctrl+O" -> "ctrl+o"); ValueError if invalid.

    Ctrl and/or Alt plus a letter or digit, or an F-key with or without them.
    """
    *modifiers, key = [part.strip() for part in spec.lower().split("+")]
    unknown = [name for name in modifiers if name not in APP_KEY_MODIFIERS]
    if unknown:
        raise ValueError(f"app key {spec!r}: only ctrl and alt modifiers are supported")
    is_function_key = FUNCTION_KEY.fullmatch(key) is not None
    if not is_function_key and not (len(key) == 1 and key.isascii() and key.isalnum()):
        raise ValueError(f"app key {spec!r}: key must be a letter, digit or F1-F24")
    if not is_function_key and not modifiers:
        raise ValueError(f"app key {spec!r}: a letter or digit needs ctrl or alt")
    ordered = [name for name in APP_KEY_MODIFIERS if name in modifiers]
    return "+".join([*ordered, key])


def app_key_sequences(spec: str) -> list[str]:
    """The Tk event sequences for an app key; letters also bind their Caps Lock form."""
    *modifiers, key = normalize_app_key(spec).split("+")
    prefix = "".join(f"{APP_KEY_MODIFIERS[name]}-" for name in modifiers)
    if FUNCTION_KEY.fullmatch(key):
        return [f"<{prefix}{key.upper()}>"]
    if key.isdigit():
        # "<Control-1>" would mean mouse button 1
        return [f"<{prefix}Key-{key}>"]
    return [f"<{prefix}{key}>", f"<{prefix}{key.upper()}>"]


def is_app_window(window: Window) -> bool:
    """A window the taskbar would show: visible (minimized counts), titled, not owned by
    another window, not a tool window."""
    return window.visible and not window.owned and not window.tool and bool(window.title)


def pick_window(windows: list[Window], program: str, title: str | None) -> Window | None:
    """The first (most recently used) app window of program, optionally with title in it."""
    for window in windows:
        if not is_app_window(window):
            continue
        if window.program.lower() != program.lower():
            continue
        if title is not None and title.lower() not in window.title.lower():
            continue
        return window
    return None


def _program(process_id: int) -> str:
    try:
        process = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    except pywintypes.error:
        return ""
    try:
        return ntpath.basename(win32process.GetModuleFileNameEx(process, 0))
    except pywintypes.error:
        return ""
    finally:
        process.Close()


def list_windows() -> list[Window]:
    """Top-level windows, most recently active first (EnumWindows walks the Z order)."""
    programs: dict[int, str] = {}
    windows: list[Window] = []

    def visit(hwnd: int, _extra: object) -> bool:
        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id not in programs:
            programs[process_id] = _program(process_id)
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        windows.append(
            Window(
                hwnd=hwnd,
                program=programs[process_id],
                title=win32gui.GetWindowText(hwnd),
                visible=bool(win32gui.IsWindowVisible(hwnd)),
                minimized=bool(win32gui.IsIconic(hwnd)),
                owned=bool(win32gui.GetWindow(hwnd, win32con.GW_OWNER)),
                tool=bool(ex_style & win32con.WS_EX_TOOLWINDOW),
            )
        )
        return True

    win32gui.EnumWindows(visit, None)
    return windows


def bring_to_front(window: Window) -> None:
    """Restore window if minimized and activate it; call while the popup has the foreground,
    since Windows only lets the foreground process hand it on."""
    if window.minimized:
        win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
    activate_window(window.hwnd)
