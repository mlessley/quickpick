"""Tags such as #project-x, switched on in notes mode and applied to every new digest entry,
and the labels (`idea: ...`) that notes are written with."""

import re
from difflib import get_close_matches
from pathlib import Path

from quickpick.digest import LABEL, TODO_MARK, list_days, read_day

TAG_QUERY = re.compile(r"#([\w-]*)")
# How far back the tag menu and the label badge look for tags and labels already used
RECENT_DAYS = 60
# How alike a new label must be to a known one to be suggested as the intended one
LABEL_LIKENESS = 0.6


def normalize_tag(name: str) -> str:
    return name.strip().lstrip("#").lower()


def parse_tag_query(query: str) -> str | None:
    """The tag typed so far when the query is a lone `#word` (or just `#`), else None."""
    match = TAG_QUERY.fullmatch(query.strip())
    return match[1].lower() if match else None


class ActiveTags:
    """The tags that are on: they label every new entry until switched off or the popup
    closes."""

    def __init__(self) -> None:
        self.active: list[str] = []

    def toggle(self, name: str) -> None:
        tag = normalize_tag(name)
        if not tag:
            return
        if tag in self.active:
            self.active.remove(tag)
        else:
            self.active.append(tag)

    def clear(self) -> None:
        self.active.clear()

    def snapshot(self) -> tuple[str, ...]:
        return tuple(self.active)


def recent_tags(digest_dir: Path) -> list[str]:
    """Tags used in the digest's recent days, most recently used first."""
    seen: list[str] = []
    for day in reversed(list_days(digest_dir)[-RECENT_DAYS:]):
        for entry in reversed(read_day(digest_dir, day)):
            for tag in entry.tags:
                if tag not in seen:
                    seen.append(tag)
    return seen


def recent_labels(digest_dir: Path) -> list[str]:
    """Labels used in the digest's recent days, most recently used first."""
    seen: list[str] = []
    for day in reversed(list_days(digest_dir)[-RECENT_DAYS:]):
        for entry in reversed(read_day(digest_dir, day)):
            for label in entry.labels:
                if label not in seen:
                    seen.append(label)
    return seen


def typed_label(query: str) -> str | None:
    """The label the note being typed will have (after any todo mark), once its colon and
    space are there."""
    # Trimmed as the note will be when saved, except at the end, where "idea: " is complete
    text = query.lstrip()
    if text.startswith(TODO_MARK):
        text = text.removeprefix(TODO_MARK).lstrip()
    match = LABEL.match(text)
    return match[1].lower() if match else None


def label_status(label: str, known: list[str]) -> tuple[bool, str | None]:
    """(already used?, the known label it's probably a typo of, if new and close to one)."""
    if label in known:
        return True, None
    close = get_close_matches(label, known, n=1, cutoff=LABEL_LIKENESS)
    return False, close[0] if close else None
