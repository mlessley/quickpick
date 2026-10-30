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
    KIND_MARKS,
    TODO_MARK,
    DigestEntry,
    LineLabel,
    append_entry,
    carried_label,
    line_labels,
    list_days,
    log_path,
    one_line,
    open_todos,
    read_day,
)
from quickpick.edge import Link, filter_links, parse_bookmarks, read_history, visit_label
from quickpick.markup import first_url
from quickpick.scratch import ScratchEntry, ScratchList, parse_addition
from quickpick.screenshot import move_capture, newest_png
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
SEARCH_HINT = "Type to search every day's notes. Every word must match, in any order."
# Kinds a notes search looks through: what was written or captured, not bookkeeping
SEARCHED_KINDS = {"note", "todo", "screenshot"}
# The most matches a notes search lists, the newest
SEARCH_LIMIT = 200

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
    hint = "Enter copy · Ctrl+U open link · Ctrl+Enter stash · F2 edit · Ctrl+Del remove"
    notice: str | None = None

    def __init__(self, store_path: Path, scratch: ScratchList, browser: Browser = "edge") -> None:
        self.store_path = store_path
        self.scratch = scratch
        self.browser = browser
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

    def open_url(self, selection: Selection | None) -> bool:
        """Ctrl+U: open the web address in the selected entry's value, instead of copying."""
        entry = self._selected(selection)
        opened, self.notice = _open_url(entry.value if entry else "", self.browser)
        return opened

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


def _link_row(link: Link, when: str = "") -> str:
    row = f"{link.name}  ({link.url})"
    return f"{when}  {row}" if when else row


class BookmarksMode:
    name = "Bookmarks"
    panes = ("Bookmarks", "History")
    shows_tail = False
    hint = "Enter open · Ctrl+Enter other browser · Tab other list"
    notice: str | None = None

    def __init__(
        self,
        profile_dir: Path,
        browser: Browser = "edge",
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.profile_dir = profile_dir
        self.browser = browser
        self.now = now
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
        bookmarks, history = self.matches
        now = self.now()
        return [
            [_link_row(link) for link in bookmarks],
            [_link_row(link, visit_label(link.visited, now)) for link in history],
        ]

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
    hint = "Enter save · Shift+Enter lines · : labels · Ctrl+F search · Ctrl+L clear · F2 viewer"
    notice: str | None = None

    def __init__(
        self,
        digest_dir: Path,
        today: Callable[[], date] = date.today,
        open_viewer: Callable[[], None] | None = None,
        tags: ActiveTags | None = None,
        browser: Browser = "edge",
        image_folder: Path | None = None,
        downloads: Path | None = None,
    ) -> None:
        self.digest_dir = digest_dir
        self.today = today
        self.open_viewer = open_viewer
        self.browser = browser
        # Where screenshots go, and where Ctrl+I takes a downloaded image from
        self.image_folder = image_folder
        self.downloads = downloads
        self.tags = tags or ActiveTags()
        self.entries: list[DigestEntry] = []
        # The last week's earlier days with entries, shown greyed above today as context
        self.earlier: list[tuple[date, list[DigestEntry]]] = []
        # Ctrl+L: when the list was last cleared, and the row of its marker in the log
        self.cleared_at: datetime | None = None
        self.clear_row: int | None = None
        self.todos: list[tuple[str, DigestEntry]] = []
        # The entry behind each row of the log pane; None for headings and markers
        self.log_entries: list[DigestEntry | None] = []
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
        self.log_entries = []
        for day, entries in self.earlier:
            rows.append(Muted(f"── {day:%A} {day.isoformat()} ──"))
            self.log_entries.append(None)
            rows += [row if isinstance(row, Muted) else Muted(row) for row in _log_rows(entries)]
            self.log_entries += self._shown(entries)
        if self.earlier:
            rows.append("── Today ──")
            self.log_entries.append(None)
        cleared = (
            self.cleared_at if self.cleared_at and self.cleared_at.date() == self.today() else None
        )
        self.clear_row = None
        for entry, row in zip(self._shown(self.entries), _log_rows(self.entries), strict=True):
            if cleared and self.clear_row is None and entry.time > cleared:
                self.clear_row = len(rows)
                rows.append(Muted(f"── cleared {cleared:%H:%M} · PageUp shows earlier ──"))
                self.log_entries.append(None)
            rows.append(row)
            self.log_entries.append(entry)
        if cleared and self.clear_row is None:
            self.clear_row = len(rows)
            rows.append(Muted(f"── cleared {cleared:%H:%M} · PageUp shows earlier ──"))
        if not self._shown(self.entries):
            rows.append(Muted(NOTES_EMPTY_HINT))
        return [[self._todo_row(todo) for _id, todo in self.todos], rows]

    def add_download(self, now: datetime) -> bool:
        """Ctrl+I: move the PNG just downloaded (e.g. from Copilot) into the screenshot
        folder and log it like a screenshot, with the tags that are on."""
        if self.image_folder is None:
            self.notice = "No screenshot folder set (GreenShot's, or screenshot_dir)"
            return False
        image = newest_png(self.downloads, now) if self.downloads else None
        if image is None:
            self.notice = "No new PNG in Downloads"
            return False
        try:
            moved = move_capture(image, self.image_folder, now, image.stem)
        except OSError:
            self.notice = f"Couldn't move {image.name}; is it still downloading?"
            return False
        entry = DigestEntry(
            time=now, kind="screenshot", text=image.name, path=str(moved), tags=self.tags.snapshot()
        )
        append_entry(self.digest_dir, entry)
        self.reload()
        self.notice = f"Added {image.name}"
        return True

    def open_url(self, selection: Selection | None) -> bool:
        """Ctrl+U or a double-click: open the first web address in the selected todo or
        log entry, whichever of its lines it's on."""
        entry = None
        if selection is not None:
            pane, index = selection
            entries = [todo for _id, todo in self.todos] if pane == 0 else self.log_entries
            entry = entries[index] if index < len(entries) else None
        opened, self.notice = _open_url(entry.text if entry else "", self.browser)
        return opened

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


def _open_url(text: str, browser: Browser) -> tuple[bool, str]:
    """Open the first web address in text: whether there was one, and what happened, for
    the status bar."""
    url = first_url(text)
    if url is None:
        return False, "No link in that line"
    open_in_new_window(url, browser)
    return True, f"Opened {url} in {browser.title()}"


def _uses(count: int) -> str:
    return "used once" if count == 1 else f"used {count} times"


class NoteSearch:
    """Notes mode's search (Ctrl+F): every day's notes, todos and screenshots that contain
    every word typed, in log order, newest at the bottom."""

    name = "Search notes"
    panes = ("",)
    shows_tail = False
    hint = "Enter open in viewer · Ctrl+Enter copy · Esc back to writing"
    notice: str | None = None

    def __init__(self, digest_dir: Path, open_viewer: Callable[[str], None] | None = None) -> None:
        self.digest_dir = digest_dir
        self.open_viewer = open_viewer
        # (day, position in the day, entry, the label of each of its lines)
        self.entries: list[tuple[date, int, DigestEntry, list[LineLabel]]] = []
        self.matches: list[tuple[date, int, DigestEntry]] = []

    def reload(self) -> None:
        self.entries = []
        for day in list_days(self.digest_dir):
            entries = read_day(self.digest_dir, day)
            for index, (entry, labels) in enumerate(
                zip(entries, line_labels(entries), strict=True)
            ):
                if entry.kind in SEARCHED_KINDS:
                    self.entries.append((day, index, entry, labels))

    def search(self, query: str) -> list[list[Row]]:
        words = query.lower().split()
        if not words:
            self.matches = []
            return [[Muted(SEARCH_HINT)]]
        rows: list[Row] = []
        self.matches = []
        for day, index, entry, labels in self.entries:
            lines = _searchable_lines(entry, labels)
            everything = " ".join(lines)
            if all(word in everything for word in words):
                self.matches.append((day, index, entry))
                rows.append(_search_row(day, entry, lines, words))
        # The newest, as the list ends with them
        self.matches = self.matches[-SEARCH_LIMIT:]
        return [rows[-SEARCH_LIMIT:]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str | None:
        if selection is None or selection[1] >= len(self.matches):
            return query
        day, index, entry = self.matches[selection[1]]
        if alternate:
            pyperclip.copy(entry.text)
            self.notice = "Copied the note"
            return query
        if self.open_viewer is None:
            return query
        self.open_viewer(f"?days=all#e-{day.isoformat()}-{index}")
        self.notice = "Opened in the viewer"
        return None

    def edit(self) -> bool:
        return False


def _searchable_lines(entry: DigestEntry, labels: list[LineLabel]) -> list[str]:
    """Each line of the entry as a search looks at it: lowercased, with the label it
    carries (continued ones too) and the entry's tags."""
    tags = " ".join(f"#{tag}" for tag in entry.tags)
    lines = entry.text.split("\n")
    # A screenshot's lines carry no labels
    carried = [label for label, _continued in labels] if labels else [None] * len(lines)
    return [
        f"{line} {label or ''} {tags}".lower() for line, label in zip(lines, carried, strict=True)
    ]


def _search_row(day: date, entry: DigestEntry, lines: list[str], words: list[str]) -> str:
    """The match as a row: its day and time, and the line most of the words are on."""
    text_lines = entry.text.split("\n")
    best = max(
        range(len(lines)), key=lambda number: (sum(w in lines[number] for w in words), -number)
    )
    line = text_lines[best] if best == 0 else f"… {text_lines[best]}"
    more = len(text_lines) - 1
    if more:
        line += f"  (+{more} line{'s' if more > 1 else ''})"
    tags = "".join(f"#{tag} " for tag in entry.tags)
    mark = KIND_MARKS.get(entry.kind, "")
    return f"{day:%m-%d}  {entry.time:%H:%M}  {tags}{mark}{line}"
