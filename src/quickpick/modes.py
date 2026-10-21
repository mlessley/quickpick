import sqlite3
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import pyperclip

from quickpick.browser import Browser, choose_browser, open_in_new_window
from quickpick.digest import (
    TODO_MARK,
    DigestEntry,
    append_entry,
    carried_label,
    list_days,
    log_path,
    one_line,
    open_todos,
    read_day,
)
from quickpick.edge import Link, filter_links, parse_bookmarks, read_history
from quickpick.scratch import ScratchEntry, ScratchList, parse_addition
from quickpick.store import StoreEntry, filter_entries, parse_store
from quickpick.tags import (
    ActiveTags,
    label_counts,
    parse_label_query,
    parse_tag_query,
    recent_labels,
    recent_tags,
)

HISTORY_LOAD_LIMIT = 5000
HISTORY_SHOW_LIMIT = 100
# How many earlier days notes mode shows, greyed, above today
HISTORY_DAYS = 7

NOTES_EMPTY_HINT = "No notes yet today. Type and press Enter to add one."
SAVED_EMPTY_HINT = "Nothing saved yet. F2 edits them in Notepad, one key~!~value per line."
SCRATCH_EMPTY_HINT = "Type or paste text and press Ctrl+Enter to stash it here."

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
    hint: str  # the keys that work here, for the status bar
    # What the last activate did, for the status bar (e.g. `Copied "vpn"`); None if nothing
    # worth saying. The popup reads it once and clears it
    notice: str | None

    def reload(self) -> None:
        """Re-read the mode's data sources; called whenever the mode is shown."""

    def search(self, query: str) -> Sequence[Sequence[Row]]:
        """Filter by query and return, per pane, the display text of each match in order."""

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str | None:
        """Act on Enter (alternate: Ctrl+Enter), given the selected match if any.
        Returns the query to keep the popup open with, or None to hide it."""

    def edit(self) -> bool:
        """Open the mode's data source for editing; False if the mode has none."""


class StashMode:
    """Strings to copy: the saved list, edited by hand, and below it the scratch list,
    filled from the popup with Ctrl+Enter."""

    name = "Stash"
    panes = ("Saved", "Scratch")
    shows_tail = False
    hint = "Enter copy · Ctrl+Enter stash · F2 edit · Ctrl+Del remove"
    notice: str | None = None

    def __init__(self, store_path: Path, scratch: ScratchList) -> None:
        self.store_path = store_path
        self.scratch = scratch
        self.entries: list[StoreEntry] = []
        self.matches: list[StoreEntry] = []
        self.scratch_matches: list[ScratchEntry] = []
        # A query whose label is already in use, stashed anyway on a second Ctrl+Enter
        self.confirming: str | None = None

    def reload(self) -> None:
        try:
            self.entries = parse_store(self.store_path.read_text())
        except FileNotFoundError:
            self.entries = []
        self.scratch.reload()

    def search(self, query: str) -> list[list[Row]]:
        self.matches = filter_entries(self.entries, query)
        self.scratch_matches = ScratchList.filter(self.scratch.entries, query)
        saved: list[Row] = [entry.display_text for entry in self.matches]
        scratch: list[Row] = [entry.display_text for entry in self.scratch_matches]
        return [
            saved or ([Muted(SAVED_EMPTY_HINT)] if not self.entries else []),
            scratch or ([Muted(SCRATCH_EMPTY_HINT)] if not self.scratch.entries else []),
        ]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str | None:
        self.notice = None
        if alternate:
            return self._add(query)
        entry = self._selected(selection)
        if entry is None:
            return query
        pyperclip.copy(entry.value)
        name = entry.key if isinstance(entry, StoreEntry) else entry.label
        self.notice = f'Copied "{name}"' if name else "Copied"
        return None

    def _selected(self, selection: Selection | None) -> StoreEntry | ScratchEntry | None:
        if selection is None:
            return None
        pane, index = selection
        matches = self.matches if pane == 0 else self.scratch_matches
        return matches[index] if index < len(matches) else None

    def _add(self, query: str) -> str:
        addition = parse_addition(query)
        if addition is None:
            self.notice = "Type or paste something to stash first"
            return query
        label, value, masked = addition
        in_use = {entry.key for entry in self.entries} | {
            entry.label for entry in self.scratch.entries if entry.label
        }
        if label in in_use and self.confirming != query:
            self.confirming = query
            self.notice = f'"{label}" exists: Ctrl+Enter again adds it'
            return query
        self.confirming = None
        self.scratch.add(ScratchEntry(datetime.now(), label, value, masked))
        self.notice = f'Stashed "{label}"' if label else "Stashed, at the top of Scratch"
        return ""

    def remove(self, selection: Selection | None) -> bool:
        """Ctrl+Delete: drop the selected scratch entry; saved entries are edited with F2."""
        entry = self._selected(selection)
        if not isinstance(entry, ScratchEntry):
            return False
        self.scratch.remove(entry)
        return True

    def edit(self, selection: Selection | None = None) -> bool:
        """F2: open the file of the list the selection is in."""
        on_scratch = selection is not None and selection[0] == 1
        subprocess.Popen(["notepad.exe", str(self.scratch.path if on_scratch else self.store_path)])
        return True


class BookmarksMode:
    name = "Bookmarks"
    panes = ("Bookmarks", "History")
    shows_tail = False
    hint = "Enter open · Ctrl+Enter other browser · Tab other list"
    notice: str | None = None

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
            link = self.matches[pane][index]
            browser = choose_browser(self.browser, alternate)
            open_in_new_window(link.url, browser)
            self.notice = f"Opened {link.name} in {browser.title()}"

    def edit(self) -> bool:
        return False


class NotesMode:
    name = "Notes"
    panes = ("Open todos", "Notes")
    shows_tail = True
    hint = "Enter save · Shift+Enter lines · : labels · Ctrl+L clear · Ctrl+E edit · F2 viewer"
    notice: str | None = None

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
        # The last week's earlier days with entries, shown greyed above today as context
        self.earlier: list[tuple[date, list[DigestEntry]]] = []
        # Ctrl+L: when the list was last cleared, and the row of its marker in the log
        self.cleared_at: datetime | None = None
        self.clear_row: int | None = None
        self.todos: list[tuple[str, DigestEntry]] = []
        # Labels already used, so the popup can flag a new one as a possible typo
        self.known_labels: list[str] = []
        # The label a `...` note written now would continue
        self.carried_label: str | None = None

    def reload(self) -> None:
        today = self.today()
        since = today - timedelta(days=HISTORY_DAYS)
        self.earlier = [
            (day, read_day(self.digest_dir, day))
            for day in list_days(self.digest_dir)
            if since <= day < today
        ]
        self.entries = read_day(self.digest_dir, today)
        self.todos = open_todos(self.digest_dir)
        self.known_labels = recent_labels(self.digest_dir)
        self.carried_label = carried_label(self.entries)

    def search(self, query: str) -> list[list[Row]]:
        rows: list[Row] = []
        for day, entries in self.earlier:
            rows.append(Muted(f"── {day:%A} {day.isoformat()} ──"))
            rows += [row if isinstance(row, Muted) else Muted(row) for row in _log_rows(entries)]
        if self.earlier:
            rows.append("── Today ──")
        cleared = (
            self.cleared_at if self.cleared_at and self.cleared_at.date() == self.today() else None
        )
        self.clear_row = None
        for entry, row in zip(self._shown(self.entries), _log_rows(self.entries), strict=True):
            if cleared and self.clear_row is None and entry.time > cleared:
                self.clear_row = len(rows)
                rows.append(Muted(f"── cleared {cleared:%H:%M} · PageUp shows earlier ──"))
            rows.append(row)
        if cleared and self.clear_row is None:
            self.clear_row = len(rows)
            rows.append(Muted(f"── cleared {cleared:%H:%M} · PageUp shows earlier ──"))
        if not self._shown(self.entries):
            rows.append(Muted(NOTES_EMPTY_HINT))
        return [[self._todo_row(todo) for _id, todo in self.todos], rows]

    @staticmethod
    def _shown(entries: list[DigestEntry]) -> list[DigestEntry]:
        return [entry for entry in entries if entry.kind != "deleted"]

    def edit_today(self) -> None:
        """Ctrl+E: open today's digest file in Notepad, creating it if nothing's logged yet."""
        path = log_path(self.digest_dir, self.today())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        subprocess.Popen(["notepad.exe", str(path)])

    def clear(self, now: datetime) -> None:
        """Ctrl+L: put everything so far above a marker, for the rest of the day."""
        self.cleared_at = now

    def _todo_row(self, todo: DigestEntry) -> str:
        tags = "".join(f"#{tag} " for tag in todo.tags)
        day = todo.time.date()
        since = f"   · {day:%a %m-%d}" if day != self.today() else ""
        return f"☐ {tags}{one_line(todo.text)}{since}"

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
            self.notice = "Todo added" if kind == "todo" else "Note saved"
        return ""

    def complete(self, selection: Selection | None) -> bool:
        """Ctrl+D: tick off the selected open todo with a done entry pointing at it; False
        if no todo is selected."""
        if selection is None or selection[0] != 0 or selection[1] >= len(self.todos):
            return False
        todo_id, todo = self.todos[selection[1]]
        done = DigestEntry(
            time=datetime.now(), kind="done", text=todo.text, tags=todo.tags, ref=todo_id
        )
        append_entry(self.digest_dir, done)
        self.reload()
        return True

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
    hint = "Enter turns the tag on or off"
    notice: str | None = None

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
            self.notice = f"#{tag} {'on' if tag in self.tags.active else 'off'}"
        return ""

    def edit(self) -> bool:
        return False


class LabelMenu:
    """What notes mode shows while a line is `:` and the start of a label: every label
    used, most recent first, and Enter starts the line with the chosen one."""

    name = "Labels: Enter starts the line with one"
    panes = ("",)
    shows_tail = False
    hint = "Enter uses the label · Up/Down choose"
    notice: str | None = None

    def __init__(self, digest_dir: Path) -> None:
        self.digest_dir = digest_dir
        self.counts: list[tuple[str, int]] = []
        self.matches: list[str] = []

    def reload(self) -> None:
        self.counts = label_counts(self.digest_dir)

    def search(self, query: str) -> list[list[str]]:
        typed = parse_label_query(query) or ""
        # Labels starting with what's typed first, then those with it further in
        found = [(label, count) for label, count in self.counts if label.startswith(typed)]
        found += [
            (label, count)
            for label, count in self.counts
            if typed in label and not label.startswith(typed)
        ]
        self.matches = [label for label, _count in found]
        return [[f"{label}:   {_uses(count)}" for label, count in found]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str:
        label = self.matches[selection[1]] if selection else parse_label_query(query)
        return f"{label}: " if label else query

    def edit(self) -> bool:
        return False


def _log_rows(entries: list[DigestEntry]) -> list[Row]:
    """A day's entries as log rows: deleted ones left out, unreadable ones flagged."""
    rows: list[Row] = []
    for entry in entries:
        if entry.kind == "deleted":
            continue
        rows.append(Muted(f"⚠ {entry.text}") if entry.kind == "unreadable" else entry.display_text)
    return rows


def _uses(count: int) -> str:
    return "used once" if count == 1 else f"used {count} times"
