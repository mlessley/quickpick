import os

import pywintypes
import win32api
import win32con
import win32gui
import win32process


def foreground_window() -> int:
    return win32gui.GetForegroundWindow()


def window_title(hwnd: int) -> str:
    return win32gui.GetWindowText(hwnd) if hwnd else ""


def is_own_window(hwnd: int) -> bool:
    """True for any window of this process, e.g. the popup, even while it's hidden."""
    if not hwnd:
        return False
    _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
    return process_id == os.getpid()


def activate_window(hwnd: int) -> None:
    """Best effort: Windows may refuse if we no longer own the foreground."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return
    try:
        win32gui.SetForegroundWindow(hwnd)
    except pywintypes.error:
        pass


def work_area_at_cursor() -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the monitor under the mouse pointer, minus the taskbar."""
    monitor = win32api.MonitorFromPoint(win32api.GetCursorPos(), win32con.MONITOR_DEFAULTTONEAREST)
    return win32api.GetMonitorInfo(monitor)["Work"]
