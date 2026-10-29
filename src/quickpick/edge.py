import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Chromium stores times as microseconds since this moment
CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Link:
    """A bookmark or history item: something Edge can open."""

    name: str
    url: str
    visited: datetime | None = None  # history only: the last visit, in local time


def _walk(node: dict) -> list[Link]:
    if node.get("type") == "url":
        return [Link(name=node["name"], url=node["url"])]
    links = []
    for child in node.get("children", []):
        links.extend(_walk(child))
    return links


def parse_bookmarks(text: str) -> list[Link]:
    links = []
    for root in json.loads(text)["roots"].values():
        if isinstance(root, dict):
            links.extend(_walk(root))
    return links


def read_history(db_path: Path, limit: int) -> list[Link]:
    """Most recent visible history first. Reads a copy, since Edge locks the live database."""
    with tempfile.TemporaryDirectory() as temp_dir:
        copy = Path(temp_dir) / "History"
        shutil.copyfile(db_path, copy)
        conn = sqlite3.connect(copy)
        try:
            rows = conn.execute(
                "select title, url, last_visit_time from urls where hidden = 0"
                " order by last_visit_time desc limit ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    return [
        Link(name=title or url, url=url, visited=_from_chrome_time(visited))
        for title, url, visited in rows
    ]


def _from_chrome_time(value: int | None) -> datetime | None:
    if not value:
        return None
    try:
        return (CHROME_EPOCH + timedelta(microseconds=value)).astimezone().replace(tzinfo=None)
    except (OSError, OverflowError):
        # Out of range for the platform (Windows can't localise times before 1970)
        return None


def visit_label(visited: datetime | None, now: datetime) -> str:
    """When a history item was last visited, as briefly as its age allows: "14:32" today,
    "Mon" within the week, "Oct 3" before that, with the year if it isn't this one."""
    if visited is None:
        return ""
    days_ago = (now.date() - visited.date()).days
    if days_ago <= 0:
        return visited.strftime("%H:%M")
    if days_ago < 7:
        return visited.strftime("%a")
    label = f"{visited:%b} {visited.day}"
    return label if visited.year == now.year else f"{label} {visited.year}"


def filter_links(links: list[Link], query: str) -> list[Link]:
    needle = query.lower()
    return [link for link in links if needle in link.name.lower() or needle in link.url.lower()]


def profile_dir(profile: str) -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data" / profile
