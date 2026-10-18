"""A small notice in the bottom-right corner of the screen, styled like the popup."""

import tkinter as tk
import winsound

from quickpick.theme import Palette
from quickpick.windows import work_area_at_cursor

TOAST_MS = 30_000
MARGIN = 16


def show_toast(root: tk.Tk, colors: Palette, title: str, body: str) -> tk.Toplevel:
    """Shown on the monitor under the mouse, with a sound; gone when clicked or after 30s."""
    toast = tk.Toplevel(root, background=colors.field, padx=16, pady=12)
    toast.overrideredirect(True)
    toast.attributes("-topmost", True)
    tk.Label(
        toast, text=title, background=colors.field, fg=colors.accent, font=("Segoe UI", 11, "bold")
    ).pack(anchor="w")
    tk.Label(toast, text=body, background=colors.field, fg=colors.text).pack(anchor="w")
    tk.Label(toast, text="Click to dismiss", background=colors.field, fg=colors.muted).pack(
        anchor="w", pady=(6, 0)
    )
    toast.update_idletasks()
    _left, _top, right, bottom = work_area_at_cursor()
    x = right - toast.winfo_reqwidth() - MARGIN
    y = bottom - toast.winfo_reqheight() - MARGIN
    toast.geometry(f"+{x}+{y}")
    for widget in (toast, *toast.winfo_children()):
        widget.bind("<ButtonRelease-1>", lambda _event: toast.destroy())
    toast.after(TOAST_MS, toast.destroy)
    winsound.MessageBeep(winsound.MB_ICONASTERISK)
    return toast
