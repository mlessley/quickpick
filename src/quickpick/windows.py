import os
import re
from typing import Literal

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


Rect = tuple[int, int, int, int]  # (left, top, right, bottom)

# Tk's "WxH+X+Y"; a position left of or above the primary monitor reads "+-X"
TK_GEOMETRY = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")


def work_areas() -> list[Rect]:
    """Every monitor's work area (minus the taskbar), as connected right now."""
    return [
        win32api.GetMonitorInfo(monitor)["Work"]
        for monitor, _dc, _rect in win32api.EnumDisplayMonitors()
    ]


def is_mostly_on_screen(window: Rect, areas: list[Rect]) -> bool:
    """True if at least half of window lies within the work areas (which never overlap)."""
    left, top, right, bottom = window
    visible = 0
    for area_left, area_top, area_right, area_bottom in areas:
        width = min(right, area_right) - max(left, area_left)
        height = min(bottom, area_bottom) - max(top, area_top)
        if width > 0 and height > 0:
            visible += width * height
    return visible * 2 >= (right - left) * (bottom - top)


def centred_in(area: Rect, width: int, height: int) -> tuple[int, int]:
    """The top-left corner that centres a width x height window in area."""
    left, top, right, bottom = area
    return (left + right - width) // 2, (top + bottom - height) // 2


def geometry_rect(geometry: str) -> Rect:
    """The rectangle a Tk geometry string describes. Unlike winfo_x and friends, a
    withdrawn window's geometry reflects moves made while it was hidden."""
    match = TK_GEOMETRY.fullmatch(geometry)
    if match is None:
        raise ValueError(f"not a Tk geometry: {geometry!r}")
    width, height, x, y = map(int, match.groups())
    return x, y, x + width, y + height


Placement = Literal["top-left", "top-right", "bottom-right", "bottom-left", "center"]
# Space kept between a window placed in a corner and the edges of the work area
EDGE_GAP = 12


def placed_in(area: Rect, width: int, height: int, where: Placement) -> tuple[int, int]:
    """The top-left corner that puts a width x height window in a corner of area, a little
    in from its edges, or in its middle."""
    if where == "center":
        return centred_in(area, width, height)
    left, top, right, bottom = area
    x = left + EDGE_GAP if where.endswith("left") else right - EDGE_GAP - width
    y = top + EDGE_GAP if where.startswith("top") else bottom - EDGE_GAP - height
    return x, y


def work_area_of(window: Rect) -> Rect:
    """The work area of the monitor window is mostly on (the nearest, if it's on none)."""
    monitor = win32api.MonitorFromRect(window, win32con.MONITOR_DEFAULTTONEAREST)
    return win32api.GetMonitorInfo(monitor)["Work"]
