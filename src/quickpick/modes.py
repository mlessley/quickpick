import sqlite3
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

import pyperclip

from quickpick.browser import Browser, choose_browser, open_in_new_window
from quickpick.digest import (
    TODO_MARK,
    DigestEntry,
    append_entry,
    list_days,
    open_todos,
    read_day,
)
from quickpick.edge import Link, filter_links, parse_bookmarks, read_history
from quickpick.quick_copy import QuickCopyEntry, filter_entries, parse_store
from quickpick.tags import ActiveTags, parse_tag_query, recent_labels, recent_tags

HISTORY_LOAD_LIMIT = 5000
HISTORY_SHOW_LIMIT = 100

NOTES_EMPTY_HINT = "No notes yet today. Type and press Enter to add one."

# (pane, index) of the selected match
Selection = tuple[int, int]


@dataclass(frozen=True)
class Muted:
    """A list row shown greyed: context around the matches, such as an earlier day in notes."""

    text: str


Row = str | Muted


class Mode(Protocol):
    name: str
    panes: tuple[str, ...]  # one listbox per pane; titles are shown when there is more than one
    # True: the last pane is a log, scrolled to the newest item with nothing selected; any
    # panes above it are short lists sized to their rows, and hidden while empty
    shows_tail: bool
    accepts_prefixes: bool  # whether special-launcher prefixes apply (not for free-text input)

    def reload(self) -> None:
        """Re-read the mode's data sources; called whenever the mode is shown."""

    def search(self, query: str) -> Sequence[Sequence[Row]]:
        """Filter by query and return, per pane, the display text of each match in order."""

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str | None:
        """Act on Enter (alternate: Ctrl+Enter), given the selected match if any.
        Returns the query to keep the popup open with, or None to hide it."""

    def edit(self) -> bool:
        """Open the mode's data source for editing; False if the mode has none."""


class QuickCopyMode:
    name = "Quick copy"
    panes = ("",)
    shows_tail = False
    accepts_prefixes = True

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.entries: list[QuickCopyEntry] = []
        self.matches: list[QuickCopyEntry] = []

    def reload(self) -> None:
        try:
            self.entries = parse_store(self.store_path.read_text())
        except FileNotFoundError:
            self.entries = []

    def search(self, query: str) -> list[list[str]]:
        self.matches = filter_entries(self.entries, query)
        return [[entry.display_text for entry in self.matches]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        if selection is not None:
            pyperclip.copy(self.matches[selection[1]].value)

    def edit(self) -> bool:
        subprocess.Popen(["notepad.exe", str(self.store_path)])
        return True


class EdgeLauncherMode:
    name = "Edge"
    panes = ("Bookmarks", "History")
    shows_tail = False
    accepts_prefixes = True

    def __init__(self, profile_dir: Path, browser: Browser = "edge") -> None:
        self.profile_dir = profile_dir
        self.browser = browser
        self.bookmarks: list[Link] = []
        self.history: list[Link] = []
        self.matches: list[list[Link]] = [[], []]

    def reload(self) -> None:
        try:
            text = (self.profile_dir / "Bookmarks").read_text(encoding="utf-8")
            self.bookmarks = parse_bookmarks(text)
        except (OSError, ValueError, KeyError):
            self.bookmarks = []
        try:
            self.history = read_history(self.profile_dir / "History", HISTORY_LOAD_LIMIT)
        except (OSError, sqlite3.Error):
            self.history = []

    def search(self, query: str) -> list[list[str]]:
        self.matches = [
            filter_links(self.bookmarks, query),
            filter_links(self.history, query)[:HISTORY_SHOW_LIMIT],
        ]
        return [[f"{link.name}  ({link.url})" for link in pane] for pane in self.matches]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        if selection is not None:
            pane, index = selection
            url = self.matches[pane][index].url
            open_in_new_window(url, choose_browser(self.browser, alternate))

    def edit(self) -> bool:
        return False


class NotesMode:
    name = "Notes"
    panes = ("Open todos", "Notes")
    shows_tail = True
    accepts_prefixes = False

    def __init__(
        self,
        digest_dir: Path,
        today: Callable[[], date] = date.today,
        open_viewer: Callable[[], None] | None = None,
        tags: ActiveTags | None = None,
    ) -> None:
        self.digest_dir = digest_dir
        self.today = today
        self.open_viewer = open_viewer
        self.tags = tags or ActiveTags()
        self.entries: list[DigestEntry] = []
        # The last earlier day with entries, shown greyed above today as context
        self.previous_day: date | None = None
        self.previous_entries: list[DigestEntry] = []
        self.todos: list[tuple[str, DigestEntry]] = []
        # Labels already used, so the popup can flag a new one as a possible typo
        self.known_labels: list[str] = []

    def reload(self) -> None:
        today = self.today()
        earlier = [day for day in list_days(self.digest_dir) if day < today]
        self.previous_day = earlier[-1] if earlier else None
        self.previous_entries = read_day(self.digest_dir, earlier[-1]) if earlier else []
        self.entries = read_day(self.digest_dir, today)
        self.todos = open_todos(self.digest_dir)
        self.known_labels = recent_labels(self.digest_dir)

    def search(self, query: str) -> list[list[Row]]:
        rows: list[Row] = []
        if self.previous_day:
            day = self.previous_day
            rows.append(Muted(f"── {day:%A} {day.isoformat()} ──"))
            rows += [Muted(entry.display_text) for entry in self.previous_entries]
            rows.append("── Today ──")
        rows += [entry.display_text for entry in self.entries]
        if not self.entries:
            rows.append(Muted(NOTES_EMPTY_HINT))
        return [[self._todo_row(todo) for _id, todo in self.todos], rows]

    def _todo_row(self, todo: DigestEntry) -> str:
        tags = "".join(f"#{tag} " for tag in todo.tags)
        day = todo.time.date()
        since = f"   · {day:%a %m-%d}" if day != self.today() else ""
        return f"☐ {tags}{todo.text}{since}"

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str:
        text = query.strip()
        kind = "note"
        if text.startswith(TODO_MARK):
            kind, text = "todo", text.removeprefix(TODO_MARK).strip()
        if text:
            entry = DigestEntry(
                time=datetime.now(), kind=kind, text=text, tags=self.tags.snapshot()
            )
            append_entry(self.digest_dir, entry)
            self.reload()
        return ""

    def complete(self, selection: Selection | None) -> None:
        """Ctrl+D: tick off the selected open todo with a done entry pointing at it."""
        if selection is None or selection[0] != 0 or selection[1] >= len(self.todos):
            return
        todo_id, todo = self.todos[selection[1]]
        done = DigestEntry(
            time=datetime.now(), kind="done", text=todo.text, tags=todo.tags, ref=todo_id
        )
        append_entry(self.digest_dir, done)
        self.reload()

    def edit(self) -> bool:
        # The full digest, with its screenshots, lives in the viewer
        if self.open_viewer is None:
            return False
        self.open_viewer()
        return True


class TagMenu:
    """What notes mode shows while the query is a lone `#word`: Enter switches the typed
    or selected tag on or off."""

    name = "Tags: Enter turns one on or off"
    panes = ("",)
    shows_tail = False
    accepts_prefixes = False

    def __init__(self, tags: ActiveTags, digest_dir: Path) -> None:
        self.tags = tags
        self.digest_dir = digest_dir
        self.recent: list[str] = []
        self.matches: list[str] = []

    def reload(self) -> None:
        self.recent = recent_tags(self.digest_dir)

    def search(self, query: str) -> list[list[str]]:
        typed = parse_tag_query(query) or ""
        known = [*self.tags.active, *(tag for tag in self.recent if tag not in self.tags.active)]
        others = [tag for tag in known if typed in tag and tag != typed]
        self.matches = [typed, *others] if typed else others
        return [[self._row(tag, typed) for tag in self.matches]]

    def _row(self, tag: str, typed: str) -> str:
        if tag in self.tags.active:
            return f"#{tag}   on"
        if tag == typed and tag not in self.recent:
            return f"#{tag}   new tag"
        return f"#{tag}"

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str:
        tag = self.matches[selection[1]] if selection else parse_tag_query(query)
        if tag:
            self.tags.toggle(tag)
        return ""

    def edit(self) -> bool:
        return False
