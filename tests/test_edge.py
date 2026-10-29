import json
import sqlite3
from datetime import UTC, datetime

from quickpick.edge import Link, filter_links, parse_bookmarks, read_history, visit_label


def _chrome_time(when: datetime) -> int:
    """Chromium's timestamps: microseconds since 1601-01-01 UTC."""
    return int((when - datetime(1601, 1, 1, tzinfo=UTC)).total_seconds() * 1_000_000)


def _local(when: datetime) -> datetime:
    return when.astimezone().replace(tzinfo=None)


def _url(name, url):
    return {"type": "url", "name": name, "url": url}


def _folder(name, *children):
    return {"type": "folder", "name": name, "children": list(children)}


def test_flattens_bookmarks_from_nested_folders_across_roots():
    text = json.dumps(
        {
            "roots": {
                "bookmark_bar": _folder(
                    "Favorites bar",
                    _url("Jira", "https://jira.example.com"),
                    _folder("Repos", _url("quickpick", "https://github.com/mlessley/quickpick")),
                ),
                "other": _folder("Other favorites", _url("Docs", "https://docs.example.com")),
                "synced": _folder("Mobile favorites"),
            }
        }
    )

    assert parse_bookmarks(text) == [
        Link(name="Jira", url="https://jira.example.com"),
        Link(name="quickpick", url="https://github.com/mlessley/quickpick"),
        Link(name="Docs", url="https://docs.example.com"),
    ]


def test_filter_matches_name_or_url_case_insensitively():
    jira = Link(name="Jira board", url="https://jira.example.com")
    repo = Link(name="quickpick", url="https://github.com/mlessley/quickpick")

    assert filter_links([jira, repo], "JIRA") == [jira]
    assert filter_links([jira, repo], "github") == [repo]


def test_reads_most_recent_visible_history_first_up_to_limit(tmp_path):
    db = tmp_path / "History"
    with sqlite3.connect(db) as conn:
        conn.execute("create table urls (url text, title text, last_visit_time int, hidden int)")
        conn.executemany(
            "insert into urls values (?, ?, ?, ?)",
            [
                ("https://old.example.com", "Old", 100, 0),
                ("https://hidden.example.com", "Hidden", 400, 1),
                ("https://newest.example.com", "Newest", 300, 0),
                ("https://middle.example.com", "Middle", 200, 0),
            ],
        )
    conn.close()

    assert [(link.name, link.url) for link in read_history(db, limit=2)] == [
        ("Newest", "https://newest.example.com"),
        ("Middle", "https://middle.example.com"),
    ]


def test_history_carries_the_last_visit_in_local_time(tmp_path):
    visited = datetime(2026, 10, 28, 12, 30, tzinfo=UTC)
    db = tmp_path / "History"
    with sqlite3.connect(db) as conn:
        conn.execute("create table urls (url text, title text, last_visit_time int, hidden int)")
        conn.execute(
            "insert into urls values (?, ?, ?, ?)",
            ("https://a.example.com", "A", _chrome_time(visited), 0),
        )
    conn.close()

    [link] = read_history(db, limit=1)

    assert link.visited == _local(visited)


def test_history_never_visited_has_no_time(tmp_path):
    db = tmp_path / "History"
    with sqlite3.connect(db) as conn:
        conn.execute("create table urls (url text, title text, last_visit_time int, hidden int)")
        conn.execute("insert into urls values (?, ?, ?, ?)", ("https://a.example.com", "A", 0, 0))
    conn.close()

    [link] = read_history(db, limit=1)

    assert link.visited is None


NOW = datetime(2026, 10, 28, 15, 0)  # a Wednesday


def test_visit_label_is_the_time_today():
    assert visit_label(datetime(2026, 10, 28, 9, 5), NOW) == "09:05"


def test_visit_label_is_the_weekday_within_the_last_week():
    assert visit_label(datetime(2026, 10, 26, 23, 0), NOW) == "Mon"
    assert visit_label(datetime(2026, 10, 22, 8, 0), NOW) == "Thu"


def test_visit_label_is_the_date_from_a_week_ago():
    assert visit_label(datetime(2026, 10, 21, 8, 0), NOW) == "Oct 21"
    assert visit_label(datetime(2026, 10, 3, 8, 0), NOW) == "Oct 3"


def test_visit_label_names_the_year_before_this_one():
    assert visit_label(datetime(2025, 12, 30, 8, 0), NOW) == "Dec 30 2025"


def test_visit_label_is_empty_without_a_visit():
    assert visit_label(None, NOW) == ""
