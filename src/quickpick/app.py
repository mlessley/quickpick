import queue
import subprocess
import sys
import time
import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from tkinter import ttk

from pydantic import ValidationError

from quickpick.app_switch import app_key_sequences, bring_to_front, list_windows, pick_window
from quickpick.config import CONFIG_PATH, DATA_DIR, AppShortcut, ensure_config, load_config
from quickpick.digest import (
    CONTINUATION,
    DigestEntry,
    append_entry,
    note_line_labels,
    open_todos,
    read_day,
)
from quickpick.edge import profile_dir
from quickpick.hotkey import Hotkey, HotkeyListener, HotkeyRegistrationError, parse_hotkey
from quickpick.launchers import (
    CommandMenu,
    JiraLauncher,
    Launcher,
    SearchLauncher,
    StoreLauncher,
    command_text,
    route,
)
from quickpick.modes import (
    BookmarksMode,
    LabelMenu,
    Mode,
    Muted,
    NoteSearch,
    NotesMode,
    Selection,
    StashMode,
    TagMenu,
)
from quickpick.scratch import ScratchList
from quickpick.screenshot import (
    capture_name,
    downloads_folder,
    find_new_image,
    list_files,
    modifiers_held,
    press_hotkey,
    read_greenshot_settings,
    rename_capture,
)
from quickpick.splash import (
    SplashContent,
    SplashView,
    hotkey_groups,
    today_line,
    todos_line,
)
from quickpick.tags import (
    ActiveTags,
    label_status,
    parse_label_query,
    parse_tag_query,
    typed_label,
)
from quickpick.theme import PALETTES, Theme
from quickpick.timer import FocusTimer, TimerLauncher
from quickpick.toast import show_toast
from quickpick.viewer import BackgroundViewer
from quickpick.windows import (
    activate_window,
    centred_in,
    foreground_window,
    geometry_rect,
    is_mostly_on_screen,
    is_own_window,
    window_title,
    work_area_at_cursor,
    work_areas,
)

UI_POLL_MS = 50
# Let Windows finish hiding the popup and repainting what was under it before capturing
HIDE_SETTLE_MS = 250
MODIFIER_RELEASE_TIMEOUT_S = 2
MODIFIER_POLL_MS = 20
CAPTURE_TIMEOUT_S = 60
CAPTURE_POLL_MS = 250
# Tries at renaming a capture (one per poll) before keeping GreenShot's own file name
RENAME_ATTEMPTS = 20

FONT = ("Segoe UI", 10)
BOLD_FONT = ("Segoe UI", 10, "bold")
QUERY_FONT = ("Segoe UI", 12)
SCROLLBAR = "Thin.Vertical.TScrollbar"
WIDTH, HEIGHT = 600, 460
# Most rows a pane above a log (notes' open todos) shows before it scrolls
FITTED_PANE_ROWS = 5
TIMER_TICK_MS = 1000
# The coloured edge showing the popup has focus (accent) or is pinned (amber)
BORDER = 2
# Focus events arrive in pairs as focus moves between the popup's own widgets; act once
# they've settled
FOCUS_SETTLE_MS = 50
# Pointer travel, in pixels, that turns a press on a mode name into a drag
DRAG_THRESHOLD = 4
# Rows of the multiline draft
DRAFT_LINES = 6
# How long the status bar shows what just happened before going back to the keys
SAY_MS = 4000
# Keys that don't dismiss the splash on their own (Ctrl+H toggles it; Esc hides the popup)
SPLASH_KEEP_KEYS = {
    "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
    "Win_L", "Win_R", "Caps_Lock", "Escape",
}  # fmt: skip
CONTROL_MASK = 0x4
# Keys that scroll the splash rather than leave it: (rows or pages, how far)
SPLASH_SCROLL_KEYS = {"Up": (False, -1), "Down": (False, 1), "Prior": (True, -1), "Next": (True, 1)}

UiCall = Callable[[], None]


class Popup:
    def __init__(
        self,
        modes: list[Mode],
        launchers: list[Launcher] | None = None,
        apps: list[AppShortcut] | None = None,
        theme: Theme = "dark",
        splash: SplashContent | None = None,
        tag_menu: TagMenu | None = None,
        timer: FocusTimer | None = None,
        label_menu: LabelMenu | None = None,
        note_search: NoteSearch | None = None,
    ) -> None:
        self.modes = modes
        # Notes mode's `#tag` menu, and the tags it switches on (shared with notes mode)
        self.tag_menu = tag_menu
        # Notes mode's `:` menu of every label used
        self.label_menu = label_menu
        # Notes mode's search (Ctrl+F), and whether the query box is searching with it
        self.note_search = note_search
        self.searching = False
        self.tags = tag_menu.tags if tag_menu else ActiveTags()
        self.timer = timer
        self.colors = PALETTES[theme]
        self.mode_index = 0
        self.launchers = launchers or []
        self.command_menu = CommandMenu(self.launchers)
        # What handles the current query: the mode, or a launcher / the command menu
        self.view: Mode = modes[0]
        self.listboxes: list[tk.Listbox] = []
        # Per pane: its title label (None when untitled) and the frame holding its list
        self.pane_widgets: list[tuple[tk.Label | None, tk.Frame]] = []
        self.match_counts: list[int] = []
        self.active_pane = 0
        self.panes_built_for: Mode | None = None
        # Titles of the panes above a log (e.g. "Open todos") collapsed to their heading by
        # a click on it; kept until Quickpick restarts
        self.collapsed: set[str] = set()
        # The window the user was in before summoning, to return focus to on hide
        self.previous_window = 0
        # Pointer position within the window when a drag of the mode bar started
        self.drag_offset = (0, 0)
        # Pinned: nothing but Esc hides the popup, so it can stay up while taking notes
        self.pinned = False
        # After one Ctrl+Q: a second one quits, any other key stays
        self.quit_armed = False
        # Whether the query is open as the multiline draft (Shift+Enter)
        self.draft_open = False

        # Where a press on a mode name started, to tell a click (switch mode) from a drag
        self.press_at = (0, 0)
        self.dragged = False

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.geometry(f"{WIDTH}x{HEIGHT}+200+200")
        self.root.option_add("*Font", FONT)
        self._apply_colors()
        # The root's own background, showing through this padding, is the focus border
        self.root.configure(padx=BORDER, pady=BORDER)
        self.root.bind("<Escape>", self._on_escape)
        self.root.bind("<FocusIn>", lambda _event: self.root.after(FOCUS_SETTLE_MS, self._on_focus))
        self.root.bind(
            "<FocusOut>", lambda _event: self.root.after(FOCUS_SETTLE_MS, self._on_focus)
        )
        self._style_scrollbars()

        # The window has no title bar, so the mode bar is where it's dragged from; a click
        # on a mode's name switches to it
        self.mode_bar = tk.Frame(self.root, padx=6, pady=3, cursor="fleur")
        self.mode_bar.pack(fill="x")
        self.mode_names = [
            tk.Label(self.mode_bar, text=mode.name, cursor="hand2") for mode in modes
        ]
        for index, label in enumerate(self.mode_names):
            label.pack(side="left", padx=(0, 12))
            label.bind("<ButtonPress-1>", self._press_mode_name)
            label.bind("<B1-Motion>", self._drag)
            label.bind("<ButtonRelease-1>", lambda _event, index=index: self._click_mode(index))
        # Where the query is going when it isn't the mode, e.g. "· → g: Repo shortcuts"
        self.mode_hint = tk.Label(self.mode_bar)
        self.mode_hint.pack(side="left")
        self.pin_button = tk.Label(self.mode_bar, text="📌", cursor="hand2", fg=self.colors.muted)
        self.pin_button.pack(side="right")
        self.pin_button.bind("<ButtonRelease-1>", self._toggle_pin)
        self.timer_label = tk.Label(self.mode_bar, fg=self.colors.accent)
        self.timer_label.pack(side="right", padx=(0, 8))
        # A chip per active tag, left of the timer
        self.tag_chips = tk.Frame(self.mode_bar)
        self.tag_chips.pack(side="right", padx=(0, 8))
        for widget in (self.mode_bar, self.mode_hint):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", lambda _event: self.entry.focus_set())

        self.query_var = tk.StringVar()
        self.query_var.trace_add("write", self._on_query_changed)

        # The query box, with room at its right end for the label badge
        entry_row = tk.Frame(self.root, background=self.colors.field)
        entry_row.pack(fill="x")
        # Shown at the left of the query box while it's searching notes
        self.search_mark = tk.Label(entry_row, text="🔍", background=self.colors.field)
        self.entry = tk.Entry(entry_row, textvariable=self.query_var, font=QUERY_FONT)
        self.entry.pack(side="left", fill="x", expand=True)
        self.label_badge = tk.Label(entry_row, background=self.colors.field)
        # The same query opened up to several lines (Shift+Enter, in notes and the stash)
        self.draft = tk.Text(
            entry_row,
            height=DRAFT_LINES,
            font=QUERY_FONT,
            wrap="word",
            undo=True,
            relief="flat",
            highlightthickness=1,
            background=self.colors.field,
        )
        self.draft.bind("<KeyRelease>", self._on_draft_changed)
        self.draft.bind("<<Paste>>", lambda _event: self.root.after_idle(self._on_draft_changed))
        self.draft.bind("<Control-Return>", self._save_draft)
        # While the label menu is up, Enter and Up/Down work it instead of the text
        self.draft.bind("<Return>", self._on_draft_menu_key(self._on_activate))
        self.draft.bind("<Up>", self._on_draft_menu_key(self._on_arrow_up))
        self.draft.bind("<Down>", self._on_draft_menu_key(self._on_arrow_down))
        self.draft.bind("<Escape>", self._close_draft)
        self.draft.bind("<Control-p>", self._toggle_pin)
        self.draft.bind("<Control-P>", self._toggle_pin)  # with Caps Lock on
        self.entry.bind("<Shift-Return>", self._open_draft)
        self.entry.bind("<Up>", self._on_arrow_up)
        self.entry.bind("<Down>", self._on_arrow_down)
        self.entry.bind("<Return>", self._on_activate)
        self.entry.bind("<Control-Return>", lambda event: self._on_activate(event, alternate=True))
        self.entry.bind("<F2>", self._on_edit)
        self.entry.bind("<Tab>", lambda _event: self._switch_pane(1))
        self.entry.bind("<Shift-Tab>", lambda _event: self._switch_pane(-1))
        self.entry.bind("<Control-Tab>", lambda _event: self._switch_mode(1))
        self.entry.bind("<Control-Shift-Tab>", lambda _event: self._switch_mode(-1))
        self.entry.bind("<Control-n>", self._on_notes_key)
        self.entry.bind("<Control-N>", self._on_notes_key)  # with Caps Lock on
        for key, mode_type in (("s", StashMode), ("b", BookmarksMode)):
            for sequence in (f"<Control-{key}>", f"<Control-{key.upper()}>"):
                self.entry.bind(sequence, lambda _event, kind=mode_type: self._go_to(kind))
        self.entry.bind("<Control-Delete>", self._on_remove)
        self.entry.bind("<Control-Up>", lambda _event: self._collapse_panes(True))
        self.entry.bind("<Control-Down>", lambda _event: self._collapse_panes(False))
        self.entry.bind("<Control-comma>", self._on_open_config)
        for key, handler in (
            ("l", self._on_clear),
            ("e", self._on_edit_today),
            ("f", self._on_search_key),
            ("u", self._on_open_url),
            ("i", self._on_add_download),
        ):
            for sequence in (f"<Control-{key}>", f"<Control-{key.upper()}>"):
                self.entry.bind(sequence, handler)
        for app in apps or []:
            for sequence in app_key_sequences(app.key):
                self.entry.bind(sequence, lambda _event, app=app: self._switch_to_app(app))
        self.entry.bind("<Control-h>", self._toggle_splash)
        self.entry.bind("<Control-H>", self._toggle_splash)  # with Caps Lock on
        self.entry.bind("<Control-d>", self._on_complete)
        self.entry.bind("<Control-D>", self._on_complete)  # with Caps Lock on
        self.entry.bind("<Prior>", lambda _event: self._scroll_log(-1))
        self.entry.bind("<Next>", lambda _event: self._scroll_log(1))
        self.entry.bind("<Control-p>", self._toggle_pin)
        self.entry.bind("<Control-P>", self._toggle_pin)  # with Caps Lock on
        self.entry.bind("<Control-q>", self._on_quit_key)
        self.entry.bind("<Control-Q>", self._on_quit_key)  # with Caps Lock on
        # Runs ahead of the entry's own bindings, so any other key leaves the splash and
        # then does its usual job
        self.entry.bindtags(("SplashDismiss", *self.entry.bindtags()))
        self.root.bind_class("SplashDismiss", "<KeyPress>", self._before_key)

        # Along the bottom: the keys that work here, or for a moment what just happened
        self.footer = tk.Label(self.root, anchor="w", padx=6, pady=2)
        self.footer.pack(side="bottom", fill="x")
        self.saying: str | None = None
        self.say_timer: str | None = None

        self.panes_frame = tk.Frame(self.root)
        self.panes_frame.pack(fill="both", expand=True)
        self.splash = SplashView(self.root, self.colors, splash) if splash else None
        self.splash_shown = False
        self.root.after(TIMER_TICK_MS, self._tick)

    @property
    def mode(self) -> Mode:
        return self.modes[self.mode_index]

    @property
    def visible(self) -> bool:
        return self.root.state() != "withdrawn"

    def run(self, ui_calls: queue.Queue[UiCall]) -> None:
        """Run the Tk loop, also running calls queued from other threads (e.g. hotkeys)."""
        self._poll_ui_calls(ui_calls)
        self.root.mainloop()

    def toggle(self) -> None:
        """The summon hotkey: open the popup, bring it forward if it's pinned and another
        window has focus, and close it if it already has focus (but never while pinned)."""
        if not self.visible:
            self.show()
        elif not is_own_window(foreground_window()):
            self.previous_window = foreground_window()
            self._take_focus()
        elif not self.pinned:
            self.hide()

    def start(self) -> None:
        """The first appearance: centred on the monitor under the mouse, on the splash."""
        x, y = centred_in(work_area_at_cursor(), WIDTH, HEIGHT)
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
        self.show()
        self.show_splash(animate=True)

    def show_splash(self, animate: bool = False) -> None:
        if self.splash is None:
            return
        self.panes_frame.pack_forget()
        self.splash.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.splash.draw(animate)
        self.splash_shown = True

    def hide_splash(self) -> None:
        if self.splash is None or not self.splash_shown:
            return
        self.splash.stop()
        self.splash.canvas.pack_forget()
        self.panes_frame.pack(fill="both", expand=True)
        self.splash_shown = False
        # The lists were filled while hidden; redo it so tail views scroll to the end
        self._refresh_matches()

    def _toggle_splash(self, _event: object) -> str:
        if self.splash_shown:
            self.hide_splash()
        else:
            self.show_splash()
        return "break"

    def _before_key(self, event: tk.Event) -> str | None:
        """Ahead of every key's own handling: any key but Ctrl+Q takes back a pending quit,
        the arrows and PageUp/Down scroll the splash, and any other key but Ctrl+H (or a
        lone modifier, or Esc) leaves it."""
        if event.keysym in SPLASH_KEEP_KEYS:
            return None
        control = event.state & CONTROL_MASK
        if self.quit_armed and not (control and event.keysym.lower() == "q"):
            self.quit_armed = False
            self._update_mode_bar()
        scroll = SPLASH_SCROLL_KEYS.get(event.keysym)
        if self.splash_shown and self.splash and scroll and not control:
            pages, delta = scroll
            self.splash.scroll(delta, pages)
            return "break"
        if self.splash_shown and not (control and event.keysym.lower() == "h"):
            self.hide_splash()
        return None

    def _on_open_config(self, _event: object) -> str:
        """Ctrl+,: the config in Notepad, created from a sample if there's none yet. It's
        read at startup, so changes need a restart."""
        ensure_config(CONFIG_PATH)
        subprocess.Popen(["notepad.exe", str(CONFIG_PATH)])
        self._say("Opened config.json · restart Quickpick to apply (Ctrl+Q twice)")
        return "break"

    def _on_quit_key(self, _event: object) -> str:
        """Ctrl+Q asks first, in the mode bar; a second Ctrl+Q ends Quickpick."""
        if self.quit_armed:
            self.root.quit()
        else:
            self.quit_armed = True
            self._say("Quit Quickpick? Ctrl+Q again to quit")
        return "break"

    def show(self, reset: bool = True) -> None:
        """reset=False brings the popup back as it was, e.g. after a screenshot. In notes
        mode it always does: an unsent note survives the popup closing."""
        window = foreground_window()
        if not is_own_window(window):
            self.previous_window = window
        self.mode.reload()
        for launcher in self.launchers:
            launcher.reload()
        if self.tag_menu:
            self.tag_menu.reload()
        if self.label_menu:
            self.label_menu.reload()
        self._bring_on_screen()
        if reset and not isinstance(self.mode, NotesMode):
            self.query_var.set("")
        else:
            self._refresh_matches()
        self.root.deiconify()
        self._take_focus()

    def _bring_on_screen(self) -> None:
        """Centre the popup on the monitor under the mouse if it's mostly off screen, e.g.
        left where a since-disconnected monitor was."""
        left, top, right, bottom = geometry_rect(self.root.geometry())
        if not is_mostly_on_screen((left, top, right, bottom), work_areas()):
            x, y = centred_in(work_area_at_cursor(), right - left, bottom - top)
            self.root.geometry(f"+{x}+{y}")

    def _take_focus(self) -> None:
        self.root.lift()
        self.root.focus_force()
        self.entry.focus_set()

    def _toggle_pin(self, _event: object = None) -> str:
        """Pinned: stays open and on top of other windows. Unpinned, it closes when it
        loses focus, so it's never left open behind them."""
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.pin_button.config(fg=self.colors.accent if self.pinned else self.colors.muted)
        (self.draft if self.draft_open else self.entry).focus_set()
        self._update_border()
        self._say("Pinned: stays open and on top" if self.pinned else "Unpinned")
        return "break"

    def _has_focus(self) -> bool:
        return self.visible and is_own_window(foreground_window())

    def _on_focus(self) -> None:
        if self.visible and not self.pinned and not self._has_focus():
            self.hide()
        self._update_border()

    def _update_border(self) -> None:
        colors = self.colors
        if not self._has_focus():
            color = colors.border
        else:
            color = colors.warning if self.pinned else colors.accent
        self.root.configure(background=color)

    def _after_action(self) -> None:
        """An action is done (copied, opened, switched): close, unless pinned."""
        self.query_var.set("")
        if not self.pinned:
            self.hide()

    def hide(self, for_capture: bool = False) -> None:
        """for_capture: only stepping aside for a screenshot, which isn't closing, so the
        tags stay on."""
        had_focus = self._has_focus()
        self._close_draft()
        if not for_capture and self.searching:
            # A search isn't a note to keep for next time
            self._stop_searching()
            self.query_var.set("")
        self.root.withdraw()
        # The splash is for startup and Ctrl+H; the next summon opens on the lists
        self.hide_splash()
        if not for_capture:
            self.tags.clear()
            self.quit_armed = False
        if had_focus:
            # Otherwise Windows can leave keyboard focus on the hidden popup. Only when
            # the popup had it: if the user clicked into another window, leave them there
            activate_window(self.previous_window)

    def _poll_ui_calls(self, ui_calls: queue.Queue[UiCall]) -> None:
        try:
            while True:
                ui_calls.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(UI_POLL_MS, self._poll_ui_calls, ui_calls)

    def _switch_mode(self, delta: int) -> str:
        self._stop_searching()
        self.mode_index = (self.mode_index + delta) % len(self.modes)
        if not isinstance(self.mode, (NotesMode, StashMode)):
            self._close_draft()
        self.mode.reload()
        self._refresh_matches()
        return "break"

    def _apply_colors(self) -> None:
        # Option-database defaults for every widget created from here on. The select and
        # insert colours are set by name, since their option class is Foreground
        colors = self.colors
        self.root.configure(background=colors.background)
        for pattern, value in (
            ("*Background", colors.background),
            ("*Foreground", colors.text),
            ("*Entry.Background", colors.field),
            ("*Listbox.Background", colors.field),
            ("*selectBackground", colors.selection),
            ("*selectForeground", colors.selection_text),
            ("*insertBackground", colors.text),
            ("*highlightBackground", colors.border),
            ("*highlightColor", colors.border),
            ("*highlightThickness", 0),
            ("*Entry.highlightThickness", 1),
            ("*Listbox.highlightThickness", 1),
            ("*Entry.relief", "flat"),
            ("*Listbox.relief", "flat"),
        ):
            self.root.option_add(pattern, value)

    def _style_scrollbars(self) -> None:
        # Only the scrollbars are ttk widgets; unlike the native theme's, clam's can be thin
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.layout(
            SCROLLBAR,
            [
                (
                    "Vertical.Scrollbar.trough",
                    {
                        "sticky": "ns",
                        "children": [("Vertical.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"})],
                    },
                )
            ],
        )
        colors = self.colors
        style.configure(
            SCROLLBAR,
            arrowsize=8,
            gripcount=0,
            borderwidth=0,
            troughcolor=colors.field,
            bordercolor=colors.field,
            background=colors.thumb,
            lightcolor=colors.thumb,
            darkcolor=colors.thumb,
        )
        style.map(SCROLLBAR, background=[("active", colors.thumb_active)])

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self.press_at = (event.x_root, event.y_root)
        self.dragged = False

    def _press_mode_name(self, event: tk.Event) -> str:
        self._start_drag(event)
        # Not on to the mode bar's own binding, which would start the drag again
        return "break"

    def _drag(self, event: tk.Event) -> None:
        if not self.dragged:
            press_x, press_y = self.press_at
            moved = max(abs(event.x_root - press_x), abs(event.y_root - press_y))
            if moved < DRAG_THRESHOLD:
                return
            self.dragged = True
        x, y = self.drag_offset
        self.root.geometry(f"+{event.x_root - x}+{event.y_root - y}")

    def _click_mode(self, index: int) -> str:
        if not self.dragged:
            self._switch_mode(index - self.mode_index)
        self.entry.focus_set()
        return "break"

    def _go_to(self, mode_type: type) -> str:
        """Ctrl+S / Ctrl+B (and Ctrl+N's first press): to the mode of that type."""
        for index, mode in enumerate(self.modes):
            if isinstance(mode, mode_type):
                self._switch_mode(index - self.mode_index)
        return "break"

    def _open_draft(self, _event: object) -> str:
        """Shift+Enter: open the query up to several lines, starting a new one at the cursor."""
        if self.draft_open or not isinstance(self.view, (NotesMode, StashMode)):
            return "break"
        query = self.query_var.get()
        cursor = self.entry.index(tk.INSERT)
        self.draft.delete("1.0", tk.END)
        self.draft.insert("1.0", f"{query[:cursor]}\n{query[cursor:]}")
        self.draft.mark_set(tk.INSERT, f"1.0 + {cursor + 1} chars")
        self.draft.edit_reset()
        self.entry.pack_forget()
        self.draft.pack(side="left", fill="x", expand=True)
        self.draft_open = True
        self.draft.focus_set()
        self._on_draft_changed()
        self._update_footer()
        return "break"

    def _on_draft_changed(self, _event: object = None) -> None:
        text = self.draft.get("1.0", "end-1c")
        if text != self.query_var.get():
            self.query_var.set(text)
        else:
            # Only the cursor moved: the badge follows its line
            self._update_label_badge(text)

    def _on_draft_menu_key(
        self, handler: Callable[[object], str]
    ) -> Callable[[object], str | None]:
        def on_key(event: object) -> str | None:
            return handler(event) if self.view is self.label_menu else None

        return on_key

    def _save_draft(self, event: object) -> str:
        """Ctrl+Enter in the draft: as Ctrl+Enter in the query box (save a note, stash)."""
        self._on_draft_changed()
        return self._on_activate(event, alternate=True)

    def _close_draft(self, _event: object = None) -> str:
        """Back to the one-line query box, keeping what was typed, line breaks and all."""
        if self.draft_open:
            self.draft.pack_forget()
            self.entry.pack(side="left", fill="x", expand=True)
            self.draft_open = False
            self.entry.focus_set()
            self.entry.icursor(tk.END)
            self._update_footer()
        return "break"

    def _update_mode_bar(self) -> None:
        colors = self.colors
        for mode, label in zip(self.modes, self.mode_names, strict=True):
            current = mode is self.mode
            label.config(
                font=BOLD_FONT if current else FONT, fg=colors.text if current else colors.muted
            )
        going_to = f"·   → {self.view.name}" if self.view is not self.mode else ""
        self.mode_hint.config(text=going_to, fg=colors.text)
        self._update_footer()

    def _update_footer(self) -> None:
        if self.saying is not None:
            self.footer.config(text=self.saying, fg=self.colors.text)
            return
        keys = self.view.hint
        if self.draft_open:
            keys = "Ctrl+Enter save · Enter new line · Esc one line"
        elif isinstance(self.view, NotesMode) and self._selection() is not None:
            keys = "Ctrl+U open link · Ctrl+D tick off the todo · " + keys
        self.footer.config(text=f"{keys} · Ctrl+H help", fg=self.colors.muted)

    def _say(self, message: str) -> None:
        """Show what just happened in the status bar for a moment, then the keys again."""
        self.saying = message
        if self.say_timer is not None:
            self.root.after_cancel(self.say_timer)
        self.say_timer = self.root.after(SAY_MS, self._stop_saying)
        self._update_footer()

    def _stop_saying(self) -> None:
        self.saying = None
        self.say_timer = None
        self._update_footer()

    def _tick(self) -> None:
        """Every second: count the timer down in the mode bar, and announce its end."""
        if self.timer:
            label = self.timer.label
            if self.timer.check():
                show_toast(self.root, self.colors, "Time's up", label)
            self.timer_label.config(text=self.timer.status() or "")
        self.root.after(TIMER_TICK_MS, self._tick)

    def _update_label_badge(self, query: str) -> None:
        """While a note's label is typed: green if it's been used before, amber if it's
        new, with the known label it's probably a typo of."""
        if not isinstance(self.view, NotesMode):
            self.label_badge.pack_forget()
            return
        # Any line of a note can carry a label: in the draft, the one the cursor is on
        line = self._current_line(query)
        label = typed_label(line)
        continued = self._continued_label(line)
        if label is None and continued is None:
            self.label_badge.pack_forget()
            return
        known, suggestion = label_status(label, self.view.known_labels) if label else (True, None)
        if continued:
            text, color = f"● {continued} (continued)", self.colors.label
        elif known:
            text, color = f"● {label}", self.colors.label
        else:
            text, color = f"○ new label: {label}", self.colors.warning
            if suggestion:
                text += f" · {suggestion}?"
        self.label_badge.config(text=text, fg=color)
        # Ahead of the query box, which would otherwise take all the room
        query_box = self.draft if self.draft_open else self.entry
        self.label_badge.pack(side="right", padx=(8, 6), before=query_box)

    def _continued_label(self, line: str) -> str | None:
        """For a `...` line in notes, the label it continues: from the draft's lines above
        it, or else from today's notes."""
        if not isinstance(self.view, NotesMode) or not line.startswith(CONTINUATION):
            return None
        carried = self.view.carried_label
        if self.draft_open:
            above = self.draft.get("1.0", "insert linestart").split("\n")[:-1]
            _labels, carried = note_line_labels(above, carried)
        return carried

    def _update_tag_chips(self) -> None:
        """Redraw the right of the mode bar: a chip per active tag (click to switch off)."""
        for child in self.tag_chips.winfo_children():
            child.destroy()
        for tag in self.tags.active:
            chip = tk.Label(self.tag_chips, text=f"#{tag} ×", fg=self.colors.accent, cursor="hand2")
            chip.pack(side="left", padx=(6, 0))
            chip.bind("<ButtonRelease-1>", lambda _event, tag=tag: self._switch_off_tag(tag))

    def _switch_off_tag(self, tag: str) -> None:
        self.tags.toggle(tag)
        self._refresh_matches()
        self.entry.focus_set()

    def _switch_to_app(self, app: AppShortcut) -> str:
        window = pick_window(list_windows(), app.program, app.title)
        if window is None:
            # Until the next query change or mode switch redraws the bar
            self._say(f"{app.name} has no open window")
            return "break"
        # While the popup still has the foreground, which Windows requires to hand it on
        bring_to_front(window)
        self._after_action()
        return "break"

    def _on_notes_key(self, _event: object) -> str:
        """Ctrl+N: to notes mode from any other mode; in notes mode, on to the viewer."""
        if isinstance(self.mode, NotesMode):
            return self._on_edit(_event)
        return self._go_to(NotesMode)

    def _build_panes(self) -> None:
        if self.panes_built_for is self.view:
            return
        for child in self.panes_frame.winfo_children():
            child.destroy()
        self.listboxes = []
        self.pane_widgets = []
        titled = len(self.view.panes) > 1
        for pane, title in enumerate(self.view.panes):
            label = None
            if titled:
                label = tk.Label(self.panes_frame, text=title, anchor="w", font=BOLD_FONT)
                label.pack(fill="x")
                if self.view.shows_tail and pane < len(self.view.panes) - 1:
                    label.config(cursor="hand2")
                    label.bind("<ButtonRelease-1>", lambda _event, t=title: self._toggle_pane(t))
            frame = tk.Frame(self.panes_frame)
            frame.pack(fill="both", expand=True)
            self.pane_widgets.append((label, frame))
            listbox = tk.Listbox(frame, takefocus=0, exportselection=False)
            scrollbar = ttk.Scrollbar(frame, orient="vertical", style=SCROLLBAR)
            scrollbar.config(command=listbox.yview)
            listbox.config(yscrollcommand=_autohiding(scrollbar, listbox))
            listbox.pack(side="left", fill="both", expand=True)
            listbox.bind("<Double-Button-1>", self._on_double_click)
            listbox.bind("<ButtonRelease-1>", lambda _event, pane=pane: self._on_click(pane))
            self.listboxes.append(listbox)
        self.active_pane = 0
        self.panes_built_for = self.view

    def _refresh_matches(self) -> None:
        query = self.query_var.get()
        handler = route(query, self.launchers, self.command_menu)
        if (
            self.tag_menu
            and isinstance(self.mode, NotesMode)
            and parse_tag_query(query) is not None
        ):
            handler = self.tag_menu
        if (
            self.label_menu
            and isinstance(self.mode, NotesMode)
            and parse_label_query(self._current_line(query)) is not None
        ):
            handler = self.label_menu
        if self.searching and self.note_search:
            handler = self.note_search
        self.view = handler or self.mode
        self._update_mode_bar()
        self._update_tag_chips()
        self._update_label_badge(query)
        self._build_panes()
        results = self.view.search(self._view_query(query))
        # Greyed rows (hints, earlier days) are context, not matches to pick from
        self.match_counts = [sum(not isinstance(row, Muted) for row in rows) for rows in results]
        for listbox, rows in zip(self.listboxes, results, strict=True):
            listbox.delete(0, tk.END)
            for row in rows:
                if isinstance(row, Muted):
                    listbox.insert(tk.END, row.text)
                    listbox.itemconfig(tk.END, foreground=self.colors.muted)
                else:
                    listbox.insert(tk.END, row)
        if self.view.shows_tail:
            self._fit_panes_above_log()
            self._scroll_log_to_newest()
            return
        if not self.match_counts[self.active_pane]:
            self.active_pane = next(
                (pane for pane, count in enumerate(self.match_counts) if count), self.active_pane
            )
        # A notes search lists matches in log order, so it starts at the newest, the last
        newest = self.match_counts[self.active_pane] - 1
        self._select(self.active_pane, max(newest, 0) if self.searching else 0)

    def _view_query(self, query: str) -> str:
        """The query as the current view reads it: launchers get `/g home` as `home`."""
        if self.view is self.label_menu:
            return self._current_line(query)
        return command_text(query) if self.view in self.launchers else query

    def _current_line(self, query: str) -> str:
        """The line being written: the whole query, or in the draft the cursor's line."""
        if self.draft_open:
            return self.draft.get("insert linestart", "insert lineend")
        return query

    def _fit_panes_above_log(self) -> None:
        """In a tail view, size the panes above the log to their rows, hiding empty ones."""
        _log_label, log_frame = self.pane_widgets[-1]
        log_top = _log_label or log_frame
        for pane, (label, frame) in enumerate(self.pane_widgets[:-1]):
            count = self.match_counts[pane]
            for widget in (label, frame):
                if widget is not None:
                    widget.pack_forget()
            if not count:
                continue
            title = self.view.panes[pane]
            collapsed = title in self.collapsed
            if label is not None:
                label.config(text=f"{'▸' if collapsed else '▾'} {title} ({count})")
                label.pack(fill="x", before=log_top)
            if collapsed:
                self.listboxes[pane].selection_clear(0, tk.END)
                continue
            self.listboxes[pane].config(height=min(count, FITTED_PANE_ROWS))
            frame.pack(fill="x", before=log_top)

    def _collapse_panes(self, collapse: bool) -> str:
        """Ctrl+Up / Ctrl+Down in a log view: collapse or expand the panes above the log,
        e.g. the open todos."""
        if self.view.shows_tail:
            above = set(self.view.panes[:-1])
            self.collapsed = self.collapsed | above if collapse else self.collapsed - above
            self._refresh_matches()
        return "break"

    def _toggle_pane(self, title: str) -> None:
        """A click on the heading of a pane above the log collapses it or expands it."""
        self.collapsed ^= {title}
        self._refresh_matches()
        self.entry.focus_set()

    def _select(self, pane: int, index: int) -> None:
        for listbox in self.listboxes:
            listbox.selection_clear(0, tk.END)
        if not self.match_counts[pane]:
            return
        listbox = self.listboxes[pane]
        listbox.selection_set(index)
        listbox.activate(index)
        listbox.see(index)
        self._update_footer()

    def _selection(self) -> Selection | None:
        if self.active_pane >= len(self.listboxes):
            # Not built yet, or rebuilt for a view with fewer panes
            return None
        selected = self.listboxes[self.active_pane].curselection()
        return (self.active_pane, selected[0]) if selected else None

    def _on_query_changed(self, *_args: object) -> None:
        self._refresh_matches()

    def _on_arrow_up(self, _event: object) -> str:
        self._move_selection(-1)
        return "break"

    def _on_arrow_down(self, _event: object) -> str:
        self._move_selection(1)
        return "break"

    def _move_selection(self, delta: int) -> None:
        if self.view.shows_tail and not self._has_rows_above_log():
            self.listboxes[-1].yview_scroll(delta, "units")
            return
        count = self.match_counts[self.active_pane]
        if not count:
            return
        selection = self._selection()
        index = selection[1] + delta if selection else 0
        self._select(self.active_pane, max(0, min(index, count - 1)))

    def _has_rows_above_log(self) -> bool:
        """Rows to pick from above the log: in a pane that isn't collapsed."""
        return any(
            count and title not in self.collapsed
            for title, count in zip(self.view.panes[:-1], self.match_counts[:-1], strict=True)
        )

    def _scroll_log_to_newest(self) -> None:
        """Show the end of the log; after Ctrl+L, with the cleared marker at the top while
        what's below it fits, as a terminal's clear leaves the cursor at the top."""
        log = self.listboxes[-1]
        clear_row = self.view.clear_row if isinstance(self.view, NotesMode) else None
        if clear_row is None:
            log.see(tk.END)
            return
        self.root.update_idletasks()
        first, second = log.bbox(0), log.bbox(1)
        row_height = (second[1] - first[1]) if first and second else 20
        visible = max(1, log.winfo_height() // row_height)
        below = log.size() - clear_row
        if below >= visible:
            log.see(tk.END)
            return
        # Blank rows under the newest, so the list can scroll the marker up to the top
        for _ in range(visible - below):
            log.insert(tk.END, "")
        log.yview(clear_row)

    def _on_clear(self, _event: object) -> str:
        """Ctrl+L in notes: everything so far goes above a marker, like a terminal's clear."""
        if isinstance(self.mode, NotesMode):
            self.mode.clear(datetime.now())
            self._refresh_matches()
            self._say("Cleared · PageUp shows earlier")
        return "break"

    def _on_add_download(self, _event: object) -> str:
        """Ctrl+I in notes: log the PNG just downloaded, e.g. one Copilot made."""
        if isinstance(self.mode, NotesMode) and self.view is self.mode:
            self.mode.add_download(datetime.now().replace(microsecond=0))
            self._say(self.mode.notice or "")
            self.mode.notice = None
            self._refresh_matches()
        return "break"

    def _on_edit_today(self, _event: object) -> str:
        """Ctrl+E in notes: today's digest file in Notepad, to correct it by hand."""
        if isinstance(self.mode, NotesMode):
            self.mode.edit_today()
            self._after_action()
        return "break"

    def _scroll_log(self, pages: int) -> str:
        if self.view.shows_tail:
            self.listboxes[-1].yview_scroll(pages, "pages")
        return "break"

    def _on_complete(self, _event: object) -> str:
        """Ctrl+D in notes: tick off the selected todo. In the `/j` list: remove the link."""
        if isinstance(self.view, JiraLauncher):
            return self._on_remove(_event)
        if isinstance(self.view, NotesMode):
            if self.view.complete(self._selection()):
                self._say("Todo ticked off")
            self._refresh_matches()
        return "break"

    def _switch_pane(self, delta: int) -> str:
        if self.view.shows_tail:
            # A log is read, not picked from
            return "break"
        pane_count = len(self.listboxes)
        for step in range(1, pane_count):
            pane = (self.active_pane + delta * step) % pane_count
            if self.match_counts[pane]:
                self.active_pane = pane
                self._select(pane, 0)
                break
        return "break"

    def _on_click(self, pane: int) -> None:
        selected = self.listboxes[pane].curselection()
        if selected:
            self.active_pane = pane
            self._select(pane, selected[0])
        self.entry.focus_set()

    def _on_activate(self, _event: object, alternate: bool = False) -> str:
        query = self._view_query(self.query_var.get())
        view = self.view
        next_query = view.activate(query, self._selection(), alternate)
        if view is self.label_menu and self.draft_open and next_query is not None:
            # Only the cursor's line becomes "label: "; the rest of the draft stays
            self.draft.delete("insert linestart", "insert lineend")
            self.draft.insert("insert linestart", next_query)
            self._on_draft_changed()
            return "break"
        if view.notice:
            # Said even if the popup then closes, so it's there if it's pinned
            self._say(view.notice)
            view.notice = None
        if next_query == query:
            # Handed back unchanged: keep it as typed, leading colon and all
            next_query = self.query_var.get()
        if next_query is None:
            self._after_action()
            return "break"
        if next_query != self.query_var.get():
            # Done with what was typed, e.g. a note saved: back to one line for the next
            self._close_draft()
        self.query_var.set(next_query)
        self.entry.icursor(tk.END)
        return "break"

    def _on_escape(self, _event: object) -> str:
        if self.searching:
            # Back to writing first; the next Esc closes the popup
            self._stop_searching()
            self.query_var.set("")
            return "break"
        self.hide()
        return "break"

    def _on_search_key(self, _event: object) -> str:
        """Ctrl+F in notes: the query box searches every day's notes, or writes again."""
        if self.searching:
            return self._on_escape(_event)
        if self.note_search is None or not isinstance(self.mode, NotesMode) or self.draft_open:
            return "break"
        self.searching = True
        self.note_search.reload()
        self.search_mark.pack(side="left", padx=(6, 0), before=self.entry)
        self.query_var.set("")
        return "break"

    def _stop_searching(self) -> None:
        if self.searching:
            self.searching = False
            self.search_mark.pack_forget()

    def _on_edit(self, _event: object) -> str:
        if isinstance(self.view, StashMode):
            edited = self.view.edit(self._selection())
        else:
            edited = self.view.edit()
        if edited:
            self._after_action()
        return "break"

    def _on_open_url(self, _event: object) -> str:
        """Ctrl+U in notes or the stash: open the web address in the selected row. Closes
        the popup, unless pinned, without clearing it, so an unsent note is kept."""
        if not isinstance(self.view, (NotesMode, StashMode)):
            return "break"
        opened = self.view.open_url(self._selection())
        self._say(self.view.notice or "")
        self.view.notice = None
        if opened and not self.pinned:
            self.hide()
        return "break"

    def _on_double_click(self, event: object) -> str:
        """A notes row has nothing to do on Enter, so a double-click opens its link."""
        if isinstance(self.view, NotesMode):
            return self._on_open_url(event)
        return self._on_activate(event)

    def _on_remove(self, _event: object) -> str:
        """Ctrl+Delete in the stash: drop the selected scratch entry. In the `/j` list (also
        Ctrl+D): drop the selected link, keeping the selection where it was."""
        selection = self._selection()
        if isinstance(self.view, StashMode) and self.view.remove(selection):
            self._say("Removed from the stash")
            self._refresh_matches()
        elif isinstance(self.view, JiraLauncher) and self.view.remove(selection):
            self._say("Removed from the list")
            self._refresh_matches()
            if selection is not None:
                pane, index = selection
                self._select(pane, min(index, self.match_counts[pane] - 1))
        return "break"


def _autohiding(scrollbar: ttk.Scrollbar, listbox: tk.Listbox) -> Callable[[str, str], None]:
    """A listbox yscrollcommand that shows the scrollbar only while the list overflows."""

    def update(first: str, last: str) -> None:
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.pack_forget()
        elif not scrollbar.winfo_manager():
            scrollbar.pack(side="right", fill="y", before=listbox)
        scrollbar.set(first, last)

    return update


class ScreenshotCapture:
    """Wraps a GreenShot capture (ADR 0002) so the popup stays out of the shot and the
    capture gets a digest entry linking the saved image."""

    def __init__(
        self, popup: Popup, greenshot_hotkey: Hotkey, folder: Path | None, digest_dir: Path
    ) -> None:
        self.popup = popup
        self.root = popup.root
        self.greenshot_hotkey = greenshot_hotkey
        self.folder = folder
        self.digest_dir = digest_dir
        self.claimed: set[str] = set()
        self.reshow = False
        self.shot_tags: tuple[str, ...] = ()

    def trigger(self) -> None:
        # The window the user is in now, unless that's our own popup (shown, or hidden
        # but still holding focus), in which case the window they summoned it from
        window = foreground_window()
        if is_own_window(window):
            window = self.popup.previous_window
        context = window_title(window)
        # A pinned popup steps aside for the shot and comes back when it's taken
        self.reshow = self.popup.visible and self.popup.pinned
        # The tags on now, while the popup steps aside, label the screenshot
        self.shot_tags = self.popup.tags.snapshot()
        self.popup.hide(for_capture=True)
        before = list_files(self.folder) if self.folder else set()
        deadline = time.monotonic() + HIDE_SETTLE_MS / 1000 + MODIFIER_RELEASE_TIMEOUT_S
        self.root.after(
            HIDE_SETTLE_MS, self._press_when_released, datetime.now(), context, before, deadline
        )

    def _press_when_released(
        self, started: datetime, context: str, before: set[str], deadline: float
    ) -> None:
        # GreenShot would see our own still-held Ctrl/Alt as part of its hotkey
        if modifiers_held() and time.monotonic() < deadline:
            self.root.after(
                MODIFIER_POLL_MS, self._press_when_released, started, context, before, deadline
            )
            return
        press_hotkey(self.greenshot_hotkey)
        self._watch(started, context, before, time.monotonic() + CAPTURE_TIMEOUT_S)

    def _watch(self, started: datetime, context: str, before: set[str], deadline: float) -> None:
        image = find_new_image(self.folder, before | self.claimed) if self.folder else None
        if image is None and self.folder and time.monotonic() < deadline:
            self.root.after(CAPTURE_POLL_MS, self._watch, started, context, before, deadline)
            return
        if image is None:
            self._log(started, context, None)
        else:
            self._rename(image, started, context, RENAME_ATTEMPTS)

    def _rename(self, image: Path, started: datetime, context: str, attempts: int) -> None:
        # Claimed while retrying too, so a second capture's watch doesn't take it
        self.claimed.add(image.name)
        renamed = rename_capture(image, started, context)
        # GreenShot may still be writing the file, which locks it; try again shortly
        if renamed == image and image.name != capture_name(started, context, image.suffix):
            if attempts > 1:
                self.root.after(
                    CAPTURE_POLL_MS, self._rename, image, started, context, attempts - 1
                )
                return
        self.claimed.add(renamed.name)
        self._log(started, context, renamed)

    def _log(self, started: datetime, context: str, image: Path | None) -> None:
        entry = DigestEntry(
            time=started,
            kind="screenshot",
            text=context,
            path=str(image) if image else None,
            tags=self.shot_tags,
        )
        append_entry(self.digest_dir, entry)
        if self.reshow and not self.popup.visible:
            self.popup.show(reset=False)


def splash_status(digest_dir: Path, timer: FocusTimer) -> list[str]:
    lines = [today_line(read_day(digest_dir, date.today()))]
    for extra in (todos_line(open_todos(digest_dir)), timer.status()):
        if extra:
            lines.append(extra)
    return lines


def main() -> None:
    try:
        config = load_config(CONFIG_PATH)
    except ValidationError as error:
        sys.exit(f"Invalid config {CONFIG_PATH}:\n{error}")

    store_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR / "quick-copy.txt"
    scratch_path = DATA_DIR / "stash-scratch.jsonl"
    # The scratch list's file before it was renamed from "added"
    earlier_scratch_path = DATA_DIR / "stash-added.jsonl"
    if earlier_scratch_path.exists() and not scratch_path.exists():
        earlier_scratch_path.rename(scratch_path)
    viewer = BackgroundViewer(config, DATA_DIR / "digest")
    greenshot = read_greenshot_settings()
    screenshot_folder = config.screenshot_dir or greenshot.output_dir
    tags = ActiveTags()
    timer = FocusTimer(DATA_DIR / "digest", tags)
    launchers: list[Launcher] = [
        StoreLauncher("g", "Repo shortcuts", DATA_DIR / "launcher.txt", config.browser),
        JiraLauncher(
            "j",
            config.jira_base_url,
            config.jira_default_project,
            DATA_DIR / "jira.txt",
            config.browser,
        ),
        TimerLauncher(timer),
        *(
            SearchLauncher(search.command, search.name, search.url, config.browser)
            for search in config.searches
        ),
    ]
    splash = SplashContent(
        hotkey_groups(config, launchers),
        lambda: splash_status(DATA_DIR / "digest", timer),
    )
    popup = Popup(
        [
            NotesMode(
                DATA_DIR / "digest",
                open_viewer=viewer.open,
                tags=tags,
                browser=config.browser,
                image_folder=screenshot_folder,
                downloads=downloads_folder(),
            ),
            StashMode(
                store_path,
                ScratchList(scratch_path, config.stash_scratch_limit),
                browser=config.browser,
            ),
            BookmarksMode(profile_dir(config.edge_profile), config.browser),
        ],
        launchers,
        config.apps,
        config.theme,
        splash,
        TagMenu(tags, DATA_DIR / "digest"),
        timer,
        LabelMenu(DATA_DIR / "digest"),
        NoteSearch(DATA_DIR / "digest", open_viewer=viewer.open),
    )

    capture = ScreenshotCapture(
        popup,
        greenshot_hotkey=parse_hotkey(
            config.greenshot_hotkey or greenshot.region_hotkey or "printscreen",
            require_modifier=False,
        ),
        folder=screenshot_folder,
        digest_dir=DATA_DIR / "digest",
    )

    ui_calls: queue.Queue[UiCall] = queue.Queue()
    listeners = [
        HotkeyListener(config.summon_hotkey, lambda: ui_calls.put(popup.toggle)),
        HotkeyListener(config.screenshot_hotkey, lambda: ui_calls.put(capture.trigger)),
    ]
    try:
        for listener in listeners:
            listener.start()
    except HotkeyRegistrationError as error:
        for listener in listeners:
            listener.stop()
        sys.exit(f"{error}\nIs Quickpick already running?")

    print(
        f"quickpick running; {config.summon_hotkey} to summon, "
        f"{config.screenshot_hotkey} to screenshot, Ctrl+C (or Ctrl+Q twice in the popup) to quit"
    )
    popup.start()
    try:
        popup.run(ui_calls)
    except KeyboardInterrupt:
        pass
    finally:
        for listener in listeners:
            listener.stop()
        viewer.close()


if __name__ == "__main__":
    main()
