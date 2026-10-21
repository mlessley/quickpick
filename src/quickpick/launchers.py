"""Slash commands: queries starting `/g`, `/j`, ... handled ahead of the current mode."""

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
    """Handles queries starting with `/<command>` ahead of the current mode, given the text
    after the command. Its name is "/<command> <description>", shown in the mode bar."""

    command: str


# "/g home": the command, then optionally a space and its text (which may span lines)
COMMAND = re.compile(r"/(\S+)(?:\s(.*))?", re.DOTALL)


def command_text(query: str) -> str:
    """What a launcher reads: the query after its command (`/g home` -> `home`)."""
    match = COMMAND.fullmatch(query)
    return (match[2] or "") if match else query


def route[L: Launcher](
    query: str, launchers: Sequence[L], menu: "CommandMenu"
) -> "L | CommandMenu | None":
    """What handles query ahead of the current mode, or None to leave it to the mode.

    In every mode a leading `/` is a command: `/g home` goes to that launcher, and a
    partly typed one shows the command menu, as long as the menu matches it; otherwise the
    line is the mode's (`/etc/hosts fixed` in notes is a note, and the notes stay in view).
    """
    match = COMMAND.fullmatch(query)
    if match:
        name = match[1].lower()
        launcher = next((launcher for launcher in launchers if launcher.command == name), None)
        if launcher:
            return launcher
    return menu if menu.has_match(query) else None


class StoreLauncher:
    """Opens URLs from a `key~!~url` store, e.g. the launcher store behind `/g`."""

    panes = ("",)
    shows_tail = False
    hint = "Enter open · Ctrl+Enter other browser · F2 edit"
    notice: str | None = None

    def __init__(self, command: str, description: str, store_path: Path, browser: Browser = "edge"):
        self.command = command
        self.name = f"/{command} {description}"
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
        self.matches = filter_entries(self.entries, query)
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


class CommandMenu:
    """Shown while a `/` command is partly typed (`/`, `/re`): lists the commands it could
    be, and Enter fills one in."""

    name = "/ commands"
    panes = ("",)
    shows_tail = False
    hint = "Enter picks the command"
    notice: str | None = None

    def __init__(self, launchers: Sequence[Launcher]) -> None:
        self.launchers = launchers
        self.matches: list[Launcher] = []

    def reload(self) -> None:
        pass

    def _matching(self, query: str) -> list[Launcher]:
        # Only while the command is being typed: a space ends it
        if not query.startswith("/") or any(char.isspace() for char in query):
            return []
        needle = query[1:].lower()
        return [launcher for launcher in self.launchers if needle in launcher.name.lower()]

    def has_match(self, query: str) -> bool:
        return bool(self._matching(query))

    def search(self, query: str) -> list[list[str]]:
        self.matches = self._matching(query)
        return [[self._row(launcher) for launcher in self.matches]]

    @staticmethod
    def _row(launcher: Launcher) -> str:
        command, _, description = launcher.name.partition(" ")
        return f"{command}  {description}"

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str:
        if selection is None:
            return query
        return f"/{self.matches[selection[1]].command} "

    def edit(self) -> bool:
        return False


ISSUE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*-\d+")


def jira_target(rest: str, base_url: str, default_project: str) -> tuple[str, str]:
    """The synthetic entry for `/j <rest>`: its label and the URL it opens."""
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
    """`/j` opens a Jira issue: digits in the default project, a full key, or a text search."""

    panes = ("",)
    shows_tail = False
    hint = "Enter open · Ctrl+Enter other browser"
    notice: str | None = None

    def __init__(
        self, command: str, base_url: str, default_project: str, browser: Browser = "edge"
    ) -> None:
        self.command = command
        self.name = f"/{command} Jira issue"
        self.base_url = base_url
        self.default_project = default_project
        self.browser = browser
        self.url = ""

    def reload(self) -> None:
        pass

    def search(self, query: str) -> list[list[str]]:
        label, self.url = jira_target(query, self.base_url, self.default_project)
        return [[label]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        if selection is not None:
            browser = choose_browser(self.browser, alternate)
            open_in_new_window(self.url, browser)
            self.notice = f"Opened Jira in {browser.title()}"

    def edit(self) -> bool:
        return False
