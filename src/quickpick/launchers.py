"""The special launcher: prefixed queries (`g:...`) handled ahead of the current mode."""

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from quickpick.browser import Browser, choose_browser, open_in_new_window
from quickpick.modes import Mode, Selection
from quickpick.store import StoreEntry, filter_entries, parse_store


class Launcher(Mode, Protocol):
    """Handles queries starting with `<prefix>:` ahead of the current mode.
    Its name is "<prefix>: <description>", shown in the mode label and the prefix menu."""

    prefix: str


def split_prefix(query: str) -> tuple[str, str] | None:
    """A special-launcher query: a one-character prefix then `:`, e.g. `g:quick`."""
    if len(query) >= 2 and query[1] == ":":
        return query[0].lower(), query[2:]
    return None


def strip_colon_form(query: str) -> str:
    """A launcher's query without the colon form's leading `:` (`:g:home` -> `g:home`)."""
    if query.startswith(":") and split_prefix(query[1:]):
        return query[1:]
    return query


def route[L: Launcher](
    query: str, launchers: Sequence[L], menu: "PrefixMenu", accepts_prefixes: bool
) -> "L | PrefixMenu | None":
    """What handles query ahead of the current mode, or None to leave it to the mode.

    In every mode a leading `:` is a command: `:g:home` goes to that launcher, and
    anything else after the `:` shows the prefix menu, as long as the menu matches it;
    otherwise the line is the mode's (`:x note` in notes is a note, and the notes stay in
    view). The plain form, `g:home`, only works where the mode accepts prefixes (not in
    notes, where it's a labelled note).
    """
    if query.startswith(":"):
        special = split_prefix(query[1:])
        launcher = special and next(
            (launcher for launcher in launchers if launcher.prefix == special[0]), None
        )
        if launcher:
            return launcher
        return menu if menu.has_match(query) else None
    if not accepts_prefixes:
        return None
    special = split_prefix(query)
    if special is None:
        return None
    return next((launcher for launcher in launchers if launcher.prefix == special[0]), None)


class StoreLauncher:
    """Opens URLs from a `key~!~url` store, e.g. the launcher store behind `g:`."""

    panes = ("",)
    shows_tail = False
    accepts_prefixes = False
    hint = "Enter open · Ctrl+Enter other browser · F2 edit"
    notice: str | None = None

    def __init__(self, prefix: str, description: str, store_path: Path, browser: Browser = "edge"):
        self.prefix = prefix
        self.name = f"{prefix}: {description}"
        self.store_path = store_path
        self.browser = browser
        self.entries: list[StoreEntry] = []
        self.matches: list[StoreEntry] = []

    def reload(self) -> None:
        try:
            self.entries = parse_store(self.store_path.read_text())
        except FileNotFoundError:
            self.entries = []

    def search(self, query: str) -> list[list[str]]:
        self.matches = filter_entries(self.entries, query[len(self.prefix) + 1 :])
        return [[f"{entry.key}  ({entry.value})" for entry in self.matches]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        if selection is not None:
            entry = self.matches[selection[1]]
            browser = choose_browser(self.browser, alternate)
            open_in_new_window(entry.value, browser)
            self.notice = f"Opened {entry.key} in {browser.title()}"

    def edit(self) -> bool:
        subprocess.Popen(["notepad.exe", str(self.store_path)])
        return True


class PrefixMenu:
    """Shown for a query starting with `:`: lists the prefixes, Enter fills one in."""

    name = ": prefixes"
    panes = ("",)
    shows_tail = False
    accepts_prefixes = False
    hint = "Enter picks the prefix"
    notice: str | None = None

    def __init__(self, launchers: Sequence[Launcher]) -> None:
        self.launchers = launchers
        self.matches: list[Launcher] = []

    def reload(self) -> None:
        pass

    def _matching(self, query: str) -> list[Launcher]:
        needle = query[1:].lower()
        return [launcher for launcher in self.launchers if needle in launcher.name.lower()]

    def has_match(self, query: str) -> bool:
        return bool(self._matching(query))

    def search(self, query: str) -> list[list[str]]:
        self.matches = self._matching(query)
        return [[launcher.name for launcher in self.matches]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str:
        if selection is None:
            return query
        # The colon form, which works in every mode, notes included
        return f":{self.matches[selection[1]].prefix}:"

    def edit(self) -> bool:
        return False


ISSUE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*-\d+")


def jira_target(rest: str, base_url: str, default_project: str) -> tuple[str, str]:
    """The synthetic entry for `j:<rest>`: its label and the URL it opens."""
    base = base_url.rstrip("/")
    text = rest.strip()
    if not text:
        return f"Open {default_project} (default project)", f"{base}/browse/{default_project}"
    if text.isdigit():
        key = f"{default_project}-{text}"
        return f"{key} (default project)", f"{base}/browse/{key}"
    if ISSUE_KEY.fullmatch(text):
        key = text.upper()
        return key, f"{base}/browse/{key}"
    jql = quote(f'text ~ "{text}"', safe="")
    return f'Search Jira for "{text}"', f"{base}/issues/?jql={jql}"


class JiraLauncher:
    """`j:` opens a Jira issue: digits in the default project, a full key, or a text search."""

    panes = ("",)
    shows_tail = False
    accepts_prefixes = False
    hint = "Enter open · Ctrl+Enter other browser"
    notice: str | None = None

    def __init__(
        self, prefix: str, base_url: str, default_project: str, browser: Browser = "edge"
    ) -> None:
        self.prefix = prefix
        self.name = f"{prefix}: Jira issue"
        self.base_url = base_url
        self.default_project = default_project
        self.browser = browser
        self.url = ""

    def reload(self) -> None:
        pass

    def search(self, query: str) -> list[list[str]]:
        label, self.url = jira_target(query[2:], self.base_url, self.default_project)
        return [[label]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        if selection is not None:
            browser = choose_browser(self.browser, alternate)
            open_in_new_window(self.url, browser)
            self.notice = f"Opened Jira in {browser.title()}"

    def edit(self) -> bool:
        return False
