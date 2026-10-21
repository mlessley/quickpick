"""The splash: shown in the popup at startup and on Ctrl+H, with the hotkeys and today's digest."""

import time
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from tkinter import font as tkfont

from quickpick.config import Config
from quickpick.digest import DigestEntry
from quickpick.launchers import Launcher
from quickpick.theme import Palette

LAST_NOTE_CHARS = 40
SPLASH_TODOS = 3
TITLE = "Quickpick"
# Title animation: each letter rises and fades in, a little after the one before it
LETTER_MS = 280
LETTER_STAGGER_MS = 35
LETTER_RISE = 10
FRAME_MS = 15
PAD = 20
ROW = 18
# Space between one group of keys and the next
GROUP_GAP = 6

# (key as pressed, what it does)
Hotkey = tuple[str, str]
HotkeyGroup = tuple[str, list[Hotkey]]


@dataclass(frozen=True)
class SplashContent:
    groups: list[HotkeyGroup]
    # Status lines (today's digest, open todos, the timer), read when the splash is
    # drawn so they're current on Ctrl+H
    status: Callable[[], list[str]]


def format_key(spec: str) -> str:
    """A config key spec as it's pressed: "ctrl+alt+space" -> "Ctrl+Alt+Space"."""
    return "+".join(part.strip().capitalize() for part in spec.split("+"))


def hotkey_groups(config: Config, launchers: Sequence[Launcher]) -> list[HotkeyGroup]:
    groups: list[HotkeyGroup] = [
        (
            "Anywhere",
            [
                (format_key(config.summon_hotkey), "Show or hide the popup"),
                (format_key(config.screenshot_hotkey), "Screenshot to the digest"),
            ],
        ),
        (
            "In the popup",
            [
                ("Ctrl+Tab", "Next mode"),
                ("Ctrl+N", "Notes, then the viewer"),
                ("Ctrl+S / B", "Stash / Bookmarks"),
                ("F2", "Edit store / viewer"),
                ("Ctrl+Enter", "Other browser / stash it"),
                ("Shift+Enter", "Write several lines"),
                ("Ctrl+P", "Pin open"),
                ("Ctrl+H", "This help"),
                ("Ctrl+Q", "Quit Quickpick"),
            ],
        ),
        (
            "In notes",
            [
                ("[] text", "Add a todo"),
                ("Ctrl+D", "Tick off a todo"),
                ("#tag", "Tag on / off"),
                ("name: text", "Label a line"),
                (": / ...", "List / continue labels"),
                ("Ctrl+L / E", "Clear / edit the file"),
            ],
        ),
    ]
    if config.apps:
        groups.append(("Apps", [(format_key(app.key), app.name) for app in config.apps]))
    commands = [tuple(launcher.name.split(" ", 1)) for launcher in launchers]
    groups.append(("Commands · / lists them", commands))
    return groups


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def today_line(entries: list[DigestEntry]) -> str:
    """One line summing up today's digest for the splash."""
    notes = [entry for entry in entries if entry.kind == "note"]
    screenshots = sum(entry.kind == "screenshot" for entry in entries)
    if not notes and not screenshots:
        return "Nothing logged yet today"
    parts = []
    if notes:
        parts.append(_count(len(notes), "note"))
    if screenshots:
        parts.append(_count(screenshots, "screenshot"))
    if notes:
        last = notes[-1]
        text = last.text.split("\n")[0]
        if len(text) > LAST_NOTE_CHARS:
            text = text[: LAST_NOTE_CHARS - 1] + "…"
        parts.append(f'last note {last.time:%H:%M} "{text}"')
    return "Today: " + " · ".join(parts)


def todos_line(todos: list[tuple[str, DigestEntry]]) -> str | None:
    """The open todos for the splash: how many, and the first few."""
    if not todos:
        return None
    texts = [todo.text for _id, todo in todos[:SPLASH_TODOS]]
    if len(todos) > SPLASH_TODOS:
        texts.append("…")
    noun = "todo" if len(todos) == 1 else "todos"
    return f"{len(todos)} open {noun}: " + " · ".join(texts)


def _mix(start: str, end: str, amount: float) -> str:
    """The colour amount (0-1) of the way from start to end, both "#rrggbb"."""
    channels = [
        round(int(start[i : i + 2], 16) * (1 - amount) + int(end[i : i + 2], 16) * amount)
        for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


class SplashView:
    """The splash drawn on a canvas that takes the place of the popup's lists."""

    def __init__(self, parent: tk.Misc, colors: Palette, content: SplashContent) -> None:
        self.colors = colors
        self.content = content
        self.canvas = tk.Canvas(parent, background=colors.field, highlightthickness=0)
        self.title_font = tkfont.Font(family="Segoe UI", size=24, weight="bold")
        self.header_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.key_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.text_font = tkfont.Font(family="Segoe UI", size=10)
        self.letters: list[tuple[int, int]] = []  # (canvas item, resting y)
        self.title_width = 0
        self.underline = 0
        self.animation: str | None = None

    def draw(self, animate: bool) -> None:
        self.stop()
        canvas, colors = self.canvas, self.colors
        canvas.delete("all")
        self.letters = []
        x, title_top = PAD, 14
        for letter in TITLE:
            item = canvas.create_text(
                x, title_top, text=letter, anchor="nw", font=self.title_font, fill=colors.text
            )
            self.letters.append((item, title_top))
            x += self.title_font.measure(letter)
        self.title_width = x - PAD
        underline_y = title_top + self.title_font.metrics("linespace") + 2
        self.underline = canvas.create_line(
            PAD, underline_y, PAD + self.title_width, underline_y, fill=colors.accent, width=3
        )
        y = underline_y + 12
        for line in self.content.status():
            canvas.create_text(
                PAD, y, text=line, anchor="nw", font=self.text_font, fill=colors.text
            )
            y += ROW
        top = y + 12
        groups = self.content.groups
        self._draw_column(groups[:2], PAD, top)
        self._draw_column(groups[2:], 310, top)
        if animate:
            self._animate(time.monotonic())

    def _draw_column(self, groups: list[HotkeyGroup], x: int, y: int) -> None:
        canvas, colors = self.canvas, self.colors
        keys = [key for _title, hotkeys in groups for key, _action in hotkeys]
        action_x = x + max((self.key_font.measure(key) for key in keys), default=0) + 14
        for title, hotkeys in groups:
            canvas.create_text(
                x, y, text=title.upper(), anchor="nw", font=self.header_font, fill=colors.muted
            )
            y += ROW
            for key, action in hotkeys:
                canvas.create_text(
                    x, y, text=key, anchor="nw", font=self.key_font, fill=colors.accent
                )
                canvas.create_text(
                    action_x, y, text=action, anchor="nw", font=self.text_font, fill=colors.text
                )
                y += ROW
            y += GROUP_GAP

    def _animate(self, started: float) -> None:
        elapsed_ms = (time.monotonic() - started) * 1000
        total_ms = LETTER_MS + LETTER_STAGGER_MS * (len(self.letters) - 1)
        for index, (item, rest_y) in enumerate(self.letters):
            progress = min(max((elapsed_ms - index * LETTER_STAGGER_MS) / LETTER_MS, 0), 1)
            eased = 1 - (1 - progress) ** 3
            x, _y = self.canvas.coords(item)
            self.canvas.coords(item, x, rest_y + LETTER_RISE * (1 - eased))
            self.canvas.itemconfig(item, fill=_mix(self.colors.field, self.colors.text, eased))
        x1, y1, _x2, y2 = self.canvas.coords(self.underline)
        grown = min(elapsed_ms / total_ms, 1)
        self.canvas.coords(self.underline, x1, y1, x1 + self.title_width * grown, y2)
        if elapsed_ms < total_ms:
            self.animation = self.canvas.after(FRAME_MS, self._animate, started)
        else:
            self.animation = None

    def stop(self) -> None:
        if self.animation is not None:
            self.canvas.after_cancel(self.animation)
            self.animation = None
