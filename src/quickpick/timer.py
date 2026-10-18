"""The focus timer: `t:25 write spec` counts down 25 minutes, logged to the digest."""

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from quickpick.digest import DigestEntry, append_entry
from quickpick.modes import Muted, Row, Selection
from quickpick.tags import ActiveTags

TIMER_QUERY = re.compile(r"(\d+)(?:\s+(.*))?")
MAX_MINUTES = 600
DEFAULT_LABEL = "focus"


def parse_timer(text: str) -> tuple[int, str] | None:
    """(minutes, what it's for) from "25 write spec"; None unless it starts with minutes."""
    match = TIMER_QUERY.fullmatch(text.strip())
    if not match or not 1 <= int(match[1]) <= MAX_MINUTES:
        return None
    return int(match[1]), (match[2] or "").strip() or DEFAULT_LABEL


def format_remaining(remaining: timedelta) -> str:
    seconds = max(0, round(remaining.total_seconds()))
    return f"{seconds // 60}:{seconds % 60:02d}"


class FocusTimer:
    """One countdown at a time; starting, finishing and cancelling are logged to the
    digest with the tags that are on."""

    def __init__(
        self, digest_dir: Path, tags: ActiveTags, clock: Callable[[], datetime] = datetime.now
    ) -> None:
        self.digest_dir = digest_dir
        self.tags = tags
        self.clock = clock
        self.ends: datetime | None = None
        self.minutes = 0
        self.label = ""

    @property
    def running(self) -> bool:
        return self.ends is not None

    def start(self, minutes: int, label: str) -> None:
        if self.running:
            self.cancel()
        self.ends = self.clock() + timedelta(minutes=minutes)
        self.minutes, self.label = minutes, label
        self._log(f"started {label} ({minutes} min)")

    def cancel(self) -> None:
        if self.running:
            self._log(f"cancelled {self.label}")
            self.ends = None

    def remaining(self) -> timedelta:
        return self.ends - self.clock() if self.ends else timedelta(0)

    def check(self) -> bool:
        """Called every second or so: True once, when the running timer has just run out."""
        if self.ends is None or self.clock() < self.ends:
            return False
        self._log(f"finished {self.label} ({self.minutes} min)")
        self.ends = None
        return True

    def status(self) -> str | None:
        """e.g. "⏱ 18:42 write spec", or None when no timer is running."""
        if not self.running:
            return None
        return f"⏱ {format_remaining(self.remaining())} {self.label}"

    def _log(self, text: str) -> None:
        entry = DigestEntry(time=self.clock(), kind="timer", text=text, tags=self.tags.snapshot())
        append_entry(self.digest_dir, entry)


class TimerLauncher:
    """The `t:` prefix: `t:25 write spec` starts a timer; a bare `t:` shows the running
    one, and Enter cancels it."""

    prefix = "t"
    name = "t: Focus timer"
    panes = ("",)
    shows_tail = False
    accepts_prefixes = False

    def __init__(self, timer: FocusTimer) -> None:
        self.timer = timer

    def reload(self) -> None:
        pass

    def search(self, query: str) -> list[list[Row]]:
        rest = query[2:].strip()
        if not rest and self.timer.running:
            remaining = format_remaining(self.timer.remaining())
            return [[f"⏱ {remaining} left · {self.timer.label}   Enter cancels it"]]
        parsed = parse_timer(rest)
        if parsed is None:
            return [[Muted("Minutes, then what it's for, e.g. t:25 write spec")]]
        minutes, label = parsed
        replacing = " (replaces the running one)" if self.timer.running else ""
        return [[f"Start a {minutes}-minute timer: {label}{replacing}"]]

    def activate(self, query: str, selection: Selection | None, alternate: bool) -> str | None:
        rest = query[2:].strip()
        if not rest and self.timer.running:
            self.timer.cancel()
            return ""
        parsed = parse_timer(rest)
        if parsed is None:
            return query
        self.timer.start(*parsed)
        return None

    def edit(self) -> bool:
        return False
