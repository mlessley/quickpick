"""Slash commands: queries starting `/g`, `/j`, ... handled ahead of the current mode."""

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from quickpick.browser import Browser, choose_browser, open_in_new_window
from quickpick.jira_list import (
    JiraLink,
    filter_jira_links,
    forget,
    format_jira_list,
    parse_jira_list,
    remember,
)
from quickpick.modes import Mode, Muted, Row, Selection
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


class SearchLauncher:
    """A web search from the config (`/p jane`): opens its URL with the text in place of
    {query}."""

    panes = ("",)
    shows_tail = False
    hint = "Enter search · Ctrl+Enter other browser"
    notice: str | None = None

    def __init__(self, command: str, title: str, url: str, browser: Browser = "edge") -> None:
        self.command = command
        self.name = f"/{command} {title}"
        self.title = title
        self.url = url
        self.browser = browser

    def reload(self) -> None:
        pass

    def search(self, query: str) -> list[list[Row]]:
        text = query.strip()
        if not text:
            return [[Muted(f"Type what to search {self.title} for")]]
        return [[f'Search {self.title} for "{text}"']]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        text = query.strip()
        if selection is None or not text:
            return
        browser = choose_browser(self.browser, alternate)
        open_in_new_window(self.url.replace("{query}", quote(text, safe="")), browser)
        self.notice = f'Searched {self.title} for "{text}" in {browser.title()}'

    def edit(self) -> bool:
        return False


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
# What `/j` reads: digits or an issue key, or a pasted address, each optionally followed by
# a title; anything else is a text search
NUMBER_TITLED = re.compile(r"(\d+)(?:\s+(.*))?", re.DOTALL)
KEY_TITLED = re.compile(rf"({ISSUE_KEY.pattern})(?:\s+(.*))?", re.DOTALL)
URL_TITLED = re.compile(r"(https?://\S+)(?:\s+(.*))?", re.DOTALL)
BROWSE_KEY = re.compile(rf"/browse/({ISSUE_KEY.pattern})")


@dataclass(frozen=True)
class JiraTarget:
    """The synthetic entry for `/j <rest>`: its label and the URL it opens; and, if opening
    it is remembered in the list, the title typed for it (None if none) and the title it
    gets without one (None: not remembered, e.g. a text search)."""

    label: str
    url: str
    title: str | None = None
    fallback: str | None = None


def jira_target(rest: str, base_url: str, default_project: str) -> JiraTarget:
    base = base_url.rstrip("/")
    text = rest.strip()
    if not text:
        return JiraTarget(
            f"Open {default_project} (default project)", f"{base}/browse/{default_project}"
        )
    number = NUMBER_TITLED.fullmatch(text)
    if number:
        key = f"{default_project}-{number[1]}"
        title = f"{key} {number[2]}" if number[2] else None
        return JiraTarget(f"{title or key} (default project)", f"{base}/browse/{key}", title, key)
    issue = KEY_TITLED.fullmatch(text)
    if issue:
        key = issue[1].upper()
        title = f"{key} {issue[2]}" if issue[2] else None
        return JiraTarget(title or key, f"{base}/browse/{key}", title, key)
    address = URL_TITLED.fullmatch(text)
    if address:
        url, title = address[1], address[2] or None
        browse = BROWSE_KEY.search(url)
        fallback = browse[1].upper() if browse else url
        return JiraTarget(f"Open {title or fallback}", url, title, fallback)
    jql = quote(f'text ~ "{text}"', safe="")
    return JiraTarget(f'Search Jira for "{text}"', f"{base}/issues/?jql={jql}")


class JiraLauncher:
    """`/j` opens a Jira issue (digits in the default project, a full key, or a pasted
    address) or a text search; below that, the list of pinned and recently opened links."""

    panes = ("",)
    shows_tail = False
    hint = "Enter open · Ctrl+Enter other browser · Ctrl+Del remove · F2 edit list"
    notice: str | None = None

    def __init__(
        self,
        command: str,
        base_url: str,
        default_project: str,
        list_path: Path,
        browser: Browser = "edge",
    ) -> None:
        self.command = command
        self.name = f"/{command} Jira issue"
        self.base_url = base_url
        self.default_project = default_project
        self.list_path = list_path
        self.browser = browser
        self.links: list[JiraLink] = []
        self.target = JiraTarget("", "")
        self.matches: list[JiraLink] = []

    def reload(self) -> None:
        try:
            self.links = parse_jira_list(self.list_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.links = []

    def search(self, query: str) -> list[list[str]]:
        self.target = jira_target(query, self.base_url, self.default_project)
        # "1234 a title" narrows the list to that issue, not to the title being typed
        self.matches = filter_jira_links(self.links, self.target.fallback or query)
        rows = [f"📌 {link.title}" if link.pinned else link.title for link in self.matches]
        return [[self.target.label, *rows]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> None:
        if selection is None:
            return
        index = selection[1]
        if index == 0:
            url, title, fallback = self.target.url, self.target.title, self.target.fallback
        else:
            link = self.matches[index - 1]
            url, title, fallback = link.url, None, link.title
        browser = choose_browser(self.browser, alternate)
        open_in_new_window(url, browser)
        self.notice = f"Opened {title or fallback or 'Jira'} in {browser.title()}"
        if fallback is not None:
            self._save(remember(self.links, url, title, fallback))

    def remove(self, selection: Selection | None) -> bool:
        """Ctrl+Delete or Ctrl+D: drop the selected link from the list."""
        if selection is None or not 0 < selection[1] <= len(self.matches):
            return False
        self._save(forget(self.links, self.matches[selection[1] - 1]))
        return True

    def edit(self) -> bool:
        """F2: the list in Notepad, to add titles and `!` pins."""
        if not self.list_path.exists():
            self._save(self.links)
        subprocess.Popen(["notepad.exe", str(self.list_path)])
        return True

    def _save(self, links: list[JiraLink]) -> None:
        self.links = links
        self.list_path.parent.mkdir(parents=True, exist_ok=True)
        self.list_path.write_text(format_jira_list(links), encoding="utf-8")
