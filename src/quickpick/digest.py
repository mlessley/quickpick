import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

# "idea: weekly summary" is labelled idea: a word starting with a letter, a colon, a space
LABEL = re.compile(r"([A-Za-z][\w-]*): ")
# A note starting with this is a todo, e.g. "[] call Jane"
TODO_MARK = "[]"
# Kinds whose text the user wrote, so it can carry a label (a screenshot's is a window title)
LABELLED_KINDS = {"note", "todo", "done"}
KIND_MARKS = {"screenshot": "[screenshot] ", "todo": "☐ ", "done": "☑ ", "timer": "⏱ "}


@dataclass(frozen=True)
class DigestEntry:
    time: datetime
    # "note", "screenshot", "todo", "done" (a todo ticked off) or "timer"; and, holding the
    # place of a line edited by hand, "deleted" or "unreadable"
    kind: str
    text: str  # the note itself, a screenshot's capture context, or the todo it's about
    path: str | None = None  # the screenshot file, for screenshot entries
    tags: tuple[str, ...] = ()  # the tags that were on when the entry was made
    ref: str | None = None  # for "done": the entry_id of the todo it ticks off

    @property
    def label(self) -> str | None:
        """Who or what the entry is about, from its opening `word: `, e.g. "idea"."""
        if self.kind not in LABELLED_KINDS:
            return None
        match = LABEL.match(self.text)
        return match[1].lower() if match else None

    @property
    def labels(self) -> tuple[str, ...]:
        """Every label the entry carries: in a note, each line's opening `word: `
        (e.g. one per speaker in meeting notes); in a todo or done entry, the first line's."""
        if self.kind not in LABELLED_KINDS:
            return ()
        lines = self.text.split("\n") if self.kind == "note" else self.text.split("\n")[:1]
        found: list[str] = []
        for line in lines:
            match = LABEL.match(line)
            if match and match[1].lower() not in found:
                found.append(match[1].lower())
        return tuple(found)

    @property
    def display_text(self) -> str:
        tags = "".join(f"#{tag} " for tag in self.tags)
        return f"{self.time:%H:%M}  {tags}{KIND_MARKS.get(self.kind, '')}{one_line(self.text)}"


# A line starting with one of these continues the label of the line before it
CONTINUATION = ("...", "…")

# Per line: the label it carries, and whether that's continued from the line before
LineLabel = tuple[str | None, bool]


def note_line_labels(lines: list[str], carried: str | None) -> tuple[list[LineLabel], str | None]:
    """The label each line of a note carries, given the label carried in from before it;
    and the label carried on after it."""
    labels: list[LineLabel] = []
    for line in lines:
        match = LABEL.match(line)
        if match:
            carried = match[1].lower()
            labels.append((carried, False))
        elif line.startswith(CONTINUATION) and carried:
            labels.append((carried, True))
        else:
            carried = None
            labels.append((None, False))
    return labels, carried


def line_labels(entries: list[DigestEntry]) -> list[list[LineLabel]]:
    """Per entry of a day, the label of each of its lines. A note's `...` line takes the
    label of the line before it, across notes too: only a note's line without one ends
    the run, not a screenshot, timer or todo in between."""
    result: list[list[LineLabel]] = []
    carried: str | None = None
    for entry in entries:
        lines = entry.text.split("\n")
        if entry.kind == "note":
            labels, carried = note_line_labels(lines, carried)
        elif entry.kind in LABELLED_KINDS:
            first = entry.label
            labels = [(first, False)] + [(None, False)] * (len(lines) - 1)
        else:
            labels = []
        result.append(labels)
    return result


def day_labels(entries: list[DigestEntry]) -> list[tuple[str, ...]]:
    """Per entry of a day, every label it carries, continued ones included."""
    return [
        tuple(dict.fromkeys(label for label, _continued in lines if label))
        for lines in line_labels(entries)
    ]


def carried_label(entries: list[DigestEntry]) -> str | None:
    """The label a `...` note written after these entries would continue."""
    carried: str | None = None
    for entry in entries:
        if entry.kind == "note":
            _labels, carried = note_line_labels(entry.text.split("\n"), carried)
    return carried


def one_line(text: str) -> str:
    """A note's first line, for one-line lists, with how many more there are."""
    first, *more = text.split("\n")
    if not more:
        return first
    return f"{first}  (+{len(more)} line{'s' if len(more) > 1 else ''})"


def entry_id(day: date, index: int) -> str:
    """An entry's lasting address: its day and its position in that day's log."""
    return f"{day.isoformat()}/{index}"


def log_path(digest_dir: Path, day: date) -> Path:
    return digest_dir / f"{day.isoformat()}.jsonl"


def append_entry(digest_dir: Path, entry: DigestEntry) -> None:
    record = asdict(entry) | {"time": entry.time.isoformat(timespec="seconds")}
    # Kept out of the log while unset, so older and plainer entries stay as they were
    for optional in ("tags", "ref"):
        if not record[optional]:
            del record[optional]
    digest_dir.mkdir(parents=True, exist_ok=True)
    with log_path(digest_dir, entry.time.date()).open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")


def list_days(digest_dir: Path) -> list[date]:
    """Days that have a digest log, oldest first."""
    days = []
    for path in digest_dir.glob("*.jsonl"):
        try:
            days.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return sorted(days)


def open_todos(digest_dir: Path) -> list[tuple[str, DigestEntry]]:
    """(entry_id, todo) for every todo, from any day, that no done entry points at,
    oldest first."""
    todos: list[tuple[str, DigestEntry]] = []
    done: set[str] = set()
    for day in list_days(digest_dir):
        for index, entry in enumerate(read_day(digest_dir, day)):
            if entry.kind == "todo":
                todos.append((entry_id(day, index), entry))
            elif entry.kind == "done" and entry.ref:
                done.add(entry.ref)
    return [(todo_id, todo) for todo_id, todo in todos if todo_id not in done]


def read_day(digest_dir: Path, day: date) -> list[DigestEntry]:
    path = log_path(digest_dir, day)
    if not path.exists():
        return []
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        # The file can be edited by hand (Ctrl+E). A line emptied to `{}` is deleted, and
        # one that can't be read is flagged; both keep their place, so the positions that
        # done entries point at stay right
        placeholder_time = datetime.combine(day, datetime.min.time())
        try:
            record = json.loads(line)
            if record == {}:
                entries.append(DigestEntry(time=placeholder_time, kind="deleted", text=""))
                continue
            record["time"] = datetime.fromisoformat(record["time"])
            record["tags"] = tuple(record.get("tags", ()))
            entries.append(DigestEntry(**record))
        except (ValueError, KeyError, TypeError):
            problem = f"line {number} of {path.name} couldn't be read"
            entries.append(DigestEntry(time=placeholder_time, kind="unreadable", text=problem))
    return entries
