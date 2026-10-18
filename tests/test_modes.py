from datetime import date, datetime

import pyperclip
import pytest

from quickpick.added import AddedList
from quickpick.digest import DigestEntry, append_entry
from quickpick.modes import (
    ADDED_EMPTY_HINT,
    NOTES_EMPTY_HINT,
    SAVED_EMPTY_HINT,
    Muted,
    NotesMode,
    StashMode,
)


def stash(tmp_path, saved: str = "") -> StashMode:
    store = tmp_path / "quick-copy.txt"
    store.write_text(saved)
    mode = StashMode(store, AddedList(tmp_path / "stash-added.jsonl", limit=100))
    mode.reload()
    return mode


@pytest.fixture
def clipboard(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(pyperclip, "copy", copied.append)
    return copied


def test_plain_query_searches_the_stash(tmp_path):
    mode = stash(tmp_path, "userid~!~mlessley\nratio a:b~!~3:4\n")

    assert mode.search("userid") == [["userid: mlessley"], [Muted(ADDED_EMPTY_HINT)]]
    assert mode.search("a:b") == [["ratio a:b: 3:4"], [Muted(ADDED_EMPTY_HINT)]]


def test_empty_lists_say_how_to_fill_them(tmp_path):
    mode = stash(tmp_path)

    assert mode.search("") == [[Muted(SAVED_EMPTY_HINT)], [Muted(ADDED_EMPTY_HINT)]]


def test_ctrl_enter_adds_the_query_to_the_added_list(tmp_path):
    mode = stash(tmp_path, "userid~!~mlessley\n")

    assert mode.activate("line one\nline two", None, alternate=True) == ""

    assert mode.search("line") == [[], ["line one ⏎ line two"]]
    assert mode.notice == "Stashed, at the top of Added"


def test_enter_copies_from_either_list(tmp_path, clipboard):
    mode = stash(tmp_path, "userid~!~mlessley\n")
    mode.activate("vpn ~!~ 10.0.0.1", None, alternate=True)
    mode.search("")

    mode.activate("", (0, 0), alternate=False)
    mode.activate("", (1, 0), alternate=False)

    assert clipboard == ["mlessley", "10.0.0.1"]


def test_a_label_already_in_use_asks_first(tmp_path):
    mode = stash(tmp_path, "vpn~!~10.0.0.1\n")

    assert mode.activate("vpn ~!~ 10.0.0.2", None, alternate=True) == "vpn ~!~ 10.0.0.2"
    assert mode.notice == '"vpn" exists: Ctrl+Enter again adds it'
    assert mode.search("10.0.0.2") == [[], [Muted(ADDED_EMPTY_HINT)]]

    assert mode.activate("vpn ~!~ 10.0.0.2", None, alternate=True) == ""
    assert mode.notice == 'Stashed "vpn"'
    assert mode.search("10.0.0.2") == [[], ["vpn: 10.0.0.2"]]


def test_nothing_to_add_says_so(tmp_path):
    mode = stash(tmp_path)

    assert mode.activate("  ", None, alternate=True) == "  "
    assert mode.notice == "Type or paste something to stash first"


def test_removes_the_selected_added_entry(tmp_path):
    mode = stash(tmp_path, "userid~!~mlessley\n")
    mode.activate("a", None, alternate=True)
    mode.activate("b", None, alternate=True)
    mode.search("")

    assert mode.remove((0, 0)) is False
    assert mode.remove((1, 0)) is True

    assert mode.search("") == [["userid: mlessley"], ["a"]]


def note(day: date, hour: int, text: str) -> DigestEntry:
    return DigestEntry(time=datetime(day.year, day.month, day.day, hour, 0), kind="note", text=text)


def test_notes_follow_the_last_earlier_day_greyed_under_a_divider(tmp_path):
    friday, monday = date(2026, 10, 9), date(2026, 10, 12)
    append_entry(tmp_path, note(date(2026, 10, 8), 9, "thursday"))
    append_entry(tmp_path, note(friday, 9, "standup"))
    append_entry(tmp_path, note(friday, 17, "wrap up"))
    append_entry(tmp_path, note(monday, 8, "coffee"))
    mode = NotesMode(tmp_path, today=lambda: monday)
    mode.reload()

    assert mode.search("")[1:] == [
        [
            Muted("── Friday 2026-10-09 ──"),
            Muted("09:00  standup"),
            Muted("17:00  wrap up"),
            "── Today ──",
            "08:00  coffee",
        ]
    ]


def test_notes_hint_where_the_first_note_goes_while_today_is_empty(tmp_path):
    friday, monday = date(2026, 10, 9), date(2026, 10, 12)
    append_entry(tmp_path, note(friday, 9, "standup"))
    mode = NotesMode(tmp_path, today=lambda: monday)
    mode.reload()

    assert mode.search("")[1][-2:] == ["── Today ──", Muted(NOTES_EMPTY_HINT)]


def test_notes_on_the_first_day_ever_show_only_the_hint(tmp_path):
    mode = NotesMode(tmp_path, today=lambda: date(2026, 10, 12))
    mode.reload()

    assert mode.search("") == [[], [Muted(NOTES_EMPTY_HINT)]]


def test_f2_in_notes_opens_the_viewer_and_hides_the_popup(tmp_path):
    opened = []
    mode = NotesMode(tmp_path, open_viewer=lambda: opened.append("viewer"))

    assert mode.edit() is True
    assert opened == ["viewer"]
