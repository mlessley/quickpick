import json
import sqlite3

from quickpick.edge import Link, filter_links, parse_bookmarks, read_history


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

    assert read_history(db, limit=2) == [
        Link(name="Newest", url="https://newest.example.com"),
        Link(name="Middle", url="https://middle.example.com"),
    ]
