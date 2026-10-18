"""The stash's added list: entries added from the popup with Ctrl+Enter, newest first.

Unlike the saved stash file, which is edited by hand, this file is Quickpick's own, so it's
rewritten freely; values may span several lines, so it's JSON Lines."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quickpick.store import SEPARATOR

# How much of a value, with no label typed, stands in as its label
LABEL_CHARS = 40
LINE_BREAK_MARK = " ⏎ "


@dataclass(frozen=True)
class AddedEntry:
    time: datetime
    label: str | None  # as typed (`label ~!~ value`), or None to show the value itself
    value: str
    masked: bool

    @property
    def display_text(self) -> str:
        if self.masked:
            # Never a label made from the value, which would show the secret; its size and
            # when it was added tell masked entries apart
            size = f"{len(self.value)} chars"
            lines = self.value.count("\n") + 1
            if lines > 1:
                size += f" · {lines} lines"
            details = f"masked · {size} · {self.time:%H:%M}"
            return f"{self.label} · {details}" if self.label else details
        preview = _preview(self.value)
        return f"{self.label}: {preview}" if self.label else preview


def _preview(value: str) -> str:
    """The value's start, line breaks marked, with its size when it's cut short."""
    if len(value) <= LABEL_CHARS:
        return value.replace("\n", LINE_BREAK_MARK)
    start = value[:LABEL_CHARS].rstrip().replace("\n", LINE_BREAK_MARK)
    size = f"+{len(value) - LABEL_CHARS} chars"
    lines = value.count("\n") + 1
    if lines > 1:
        size += f" · {lines} lines"
    return f"{start}…  {size}"


def parse_addition(query: str) -> tuple[str | None, str, bool] | None:
    """(label, value, masked) from what was typed or pasted, or None if there's no value.

    A leading `*` masks the value; `label ~!~ value` gives it a label."""
    masked = query.startswith("*")
    text = query.removeprefix("*")
    label: str | None = None
    if SEPARATOR in text:
        typed, _, text = text.partition(SEPARATOR)
        label = typed.strip() or None
        text = text.strip()
    else:
        # Leading spaces may be the value's own indentation; trailing ones never matter
        text = text.rstrip()
    if not text.strip():
        return None
    return label, text, masked


class AddedList:
    def __init__(self, path: Path, limit: int) -> None:
        self.path = path
        self.limit = limit
        self.entries: list[AddedEntry] = []

    def reload(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        self.entries = []
        for line in lines:
            if not line:
                continue
            # F2 opens this file in Notepad, so skip a line spoiled by hand rather than
            # break the stash
            try:
                record = json.loads(line)
                entry = AddedEntry(
                    time=datetime.fromisoformat(record["time"]),
                    label=record.get("label"),
                    value=record["value"],
                    masked=record.get("masked", False),
                )
            except (ValueError, KeyError, TypeError):
                continue
            self.entries.append(entry)

    def add(self, entry: AddedEntry) -> None:
        """Add entry at the top; the same value added before moves up instead."""
        others = [old for old in self.entries if old.value != entry.value]
        self.entries = [entry, *others][: self.limit]
        self._save()

    def remove(self, entry: AddedEntry) -> None:
        self.entries = [old for old in self.entries if old is not entry]
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for entry in self.entries:
            record = {"time": entry.time.isoformat(timespec="seconds"), "value": entry.value}
            if entry.label:
                record["label"] = entry.label
            if entry.masked:
                record["masked"] = True
            lines.append(json.dumps(record) + "\n")
        self.path.write_text("".join(lines), encoding="utf-8")

    @staticmethod
    def filter(entries: list[AddedEntry], query: str) -> list[AddedEntry]:
        needle = query.lower()
        return [
            entry
            for entry in entries
            if needle in (entry.label or "").lower()
            or (not entry.masked and needle in entry.value.lower())
        ]
