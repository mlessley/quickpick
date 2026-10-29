from datetime import date, datetime

import pyperclip
import pytest

from quickpick.digest import DigestEntry, append_entry
from quickpick.edge import Link
from quickpick.modes import (
    NOTES_EMPTY_HINT,
    SAVED_EMPTY_HINT,
    SCRATCH_EMPTY_HINT,
    SEARCH_HINT,
    BookmarksMode,
    Muted,
    NoteSearch,
    NotesMode,
    StashMode,
)
from quickpick.scratch import ScratchList


def stash(tmp_path, saved: str = "") -> StashMode:
    store = tmp_path / "quick-copy.txt"
    store.write_text(saved)
    mode = StashMode(store, ScratchList(tmp_path / "stash-scratch.jsonl", limit=100))
    mode.reload()
    return mode


@pytest.fixture
def clipboard(monkeypatch):
    copied: list[str] = []
    monkeypatch.setattr(pyperclip, "copy", copied.append)
    return copied


def test_plain_query_searches_the_stash(tmp_path):
    mode = stash(tmp_path, "userid~!~mlessley\nratio a:b~!~3:4\n")

    assert mode.search("userid") == [["userid: mlessley"], [Muted(SCRATCH_EMPTY_HINT)]]
    assert mode.search("a:b") == [["ratio a:b: 3:4"], [Muted(SCRATCH_EMPTY_HINT)]]


def test_empty_lists_say_how_to_fill_them(tmp_path):
    mode = stash(tmp_path)

    assert mode.search("") == [[Muted(SAVED_EMPTY_HINT)], [Muted(SCRATCH_EMPTY_HINT)]]


def test_ctrl_enter_adds_the_query_to_the_scratch_list(tmp_path):
    mode = stash(tmp_path, "userid~!~mlessley\n")

    assert mode.activate("line one\nline two", None, alternate=True) == ""

    assert mode.search("line") == [[], ["line one ⏎ line two"]]
    assert mode.notice == "Stashed, at the top of Scratch"


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
    assert mode.search("10.0.0.2") == [[], [Muted(SCRATCH_EMPTY_HINT)]]

    assert mode.activate("vpn ~!~ 10.0.0.2", None, alternate=True) == ""
    assert mode.notice == 'Stashed "vpn"'
    assert mode.search("10.0.0.2") == [[], ["vpn: 10.0.0.2"]]


def test_nothing_to_add_says_so(tmp_path):
    mode = stash(tmp_path)

    assert mode.activate("  ", None, alternate=True) == "  "
    assert mode.notice == "Type or paste something to stash first"


def test_removes_the_selected_scratch_entry(tmp_path):
    mode = stash(tmp_path, "userid~!~mlessley\n")
    mode.activate("a", None, alternate=True)
    mode.activate("b", None, alternate=True)
    mode.search("")

    assert mode.remove((0, 0)) is False
    assert mode.remove((1, 0)) is True

    assert mode.search("") == [["userid: mlessley"], ["a"]]


def note(day: date, hour: int, text: str) -> DigestEntry:
    return DigestEntry(time=datetime(day.year, day.month, day.day, hour, 0), kind="note", text=text)


def test_notes_follow_the_last_week_greyed_under_a_divider_per_day(tmp_path):
    friday, monday = date(2026, 10, 9), date(2026, 10, 12)
    append_entry(tmp_path, note(date(2026, 10, 4), 9, "too old"))
    append_entry(tmp_path, note(date(2026, 10, 8), 9, "thursday"))
    append_entry(tmp_path, note(friday, 9, "standup"))
    append_entry(tmp_path, note(friday, 17, "wrap up"))
    append_entry(tmp_path, note(monday, 8, "coffee"))
    mode = NotesMode(tmp_path, today=lambda: monday)
    mode.reload()

    assert mode.search("")[1:] == [
        [
            Muted("── Thursday 2026-10-08 ──"),
            Muted("09:00  thursday"),
            Muted("── Friday 2026-10-09 ──"),
            Muted("09:00  standup"),
            Muted("17:00  wrap up"),
            "── Today ──",
            "08:00  coffee",
        ]
    ]


def test_hand_edited_lines_are_hidden_or_flagged_in_notes(tmp_path):
    monday = date(2026, 10, 12)
    append_entry(tmp_path, note(monday, 8, "coffee"))
    with (tmp_path / "2026-10-12.jsonl").open("a", encoding="utf-8") as log:
        log.write("{}\nnot json\n")
    mode = NotesMode(tmp_path, today=lambda: monday)
    mode.reload()

    assert mode.search("")[1] == [
        "08:00  coffee",
        Muted("⚠ line 3 of 2026-10-12.jsonl couldn't be read"),
    ]


def test_clearing_puts_a_marker_after_everything_so_far(tmp_path):
    monday = date(2026, 10, 12)
    append_entry(tmp_path, note(date(2026, 10, 9), 9, "standup"))
    append_entry(tmp_path, note(monday, 8, "coffee"))
    mode = NotesMode(tmp_path, today=lambda: monday)
    mode.reload()

    mode.clear(datetime(2026, 10, 12, 10, 42))
    append_entry(tmp_path, note(monday, 11, "after"))
    mode.reload()
    rows = mode.search("")[1]

    assert rows[mode.clear_row :] == [
        Muted("── cleared 10:42 · PageUp shows earlier ──"),
        "11:00  after",
    ]
    assert "08:00  coffee" in rows[: mode.clear_row]


def test_a_clear_from_an_earlier_day_no_longer_applies(tmp_path):
    monday = date(2026, 10, 12)
    append_entry(tmp_path, note(monday, 8, "coffee"))
    mode = NotesMode(tmp_path, today=lambda: monday)
    mode.clear(datetime(2026, 10, 11, 22, 0))
    mode.reload()

    assert Muted("── cleared 22:00 · PageUp shows earlier ──") not in mode.search("")[1]
    assert mode.clear_row is None


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


def search_digest(tmp_path) -> None:
    for day, hour, kind, text, tags in (
        (date(2026, 10, 14), 9, "note", "idea: weekly summary", ()),
        (date(2026, 10, 14), 10, "timer", "started 25 min: write the deck", ()),
        (date(2026, 10, 15), 9, "note", "Standup\nana: sends the Deck\n... by Friday", ()),
        (date(2026, 10, 15), 10, "todo", "book the room", ("planning",)),
        (date(2026, 10, 16), 9, "screenshot", "Deck review - PowerPoint", ()),
    ):
        entry = DigestEntry(
            time=datetime(day.year, day.month, day.day, hour, 0), kind=kind, text=text, tags=tags
        )
        append_entry(tmp_path, entry)


def test_search_finds_every_word_in_any_order_across_all_days(tmp_path):
    search_digest(tmp_path)
    search = NoteSearch(tmp_path)
    search.reload()

    assert search.search("deck ANA") == [["10-15  09:00  … ana: sends the Deck  (+2 lines)"]]
    assert search.search("deck") == [
        [
            "10-15  09:00  … ana: sends the Deck  (+2 lines)",
            "10-16  09:00  [screenshot] Deck review - PowerPoint",
        ]
    ]


def test_search_matches_tags_and_continued_labels_but_not_timers(tmp_path):
    search_digest(tmp_path)
    search = NoteSearch(tmp_path)
    search.reload()

    assert search.search("#planning") == [["10-15  10:00  #planning ☐ book the room"]]
    assert search.search("friday ana") == [["10-15  09:00  … ... by Friday  (+2 lines)"]]
    assert search.search("write") == [[]]


def test_search_hints_until_something_is_typed(tmp_path):
    search = NoteSearch(tmp_path)
    search.reload()

    assert search.search("  ") == [[Muted(SEARCH_HINT)]]


def test_enter_opens_the_match_in_the_viewer_and_ctrl_enter_copies_it(tmp_path, clipboard):
    search_digest(tmp_path)
    opened: list[str] = []
    search = NoteSearch(tmp_path, open_viewer=opened.append)
    search.reload()
    search.search("summary")

    assert search.activate("summary", (0, 0), alternate=False) is None
    assert opened == ["?days=all#e-2026-10-14-0"]
    assert search.activate("summary", (0, 0), alternate=True) == "summary"
    assert clipboard == ["idea: weekly summary"]


def test_history_rows_start_with_when_they_were_visited(tmp_path):
    mode = BookmarksMode(tmp_path, now=lambda: datetime(2026, 10, 28, 15, 0))
    mode.bookmarks = [Link(name="Jira", url="https://jira.example.com")]
    mode.history = [
        Link("Today", "https://a.example.com", visited=datetime(2026, 10, 28, 9, 5)),
        Link("Monday", "https://b.example.com", visited=datetime(2026, 10, 26, 9, 5)),
    ]

    assert mode.search("") == [
        ["Jira  (https://jira.example.com)"],
        ["09:05  Today  (https://a.example.com)", "Mon  Monday  (https://b.example.com)"],
    ]
