import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Link:
    """A bookmark or history item: something Edge can open."""

    name: str
    url: str


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
                "select title, url from urls where hidden = 0"
                " order by last_visit_time desc limit ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    return [Link(name=title or url, url=url) for title, url in rows]


def filter_links(links: list[Link], query: str) -> list[Link]:
    needle = query.lower()
    return [link for link in links if needle in link.name.lower() or needle in link.url.lower()]


def profile_dir(profile: str) -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data" / profile
