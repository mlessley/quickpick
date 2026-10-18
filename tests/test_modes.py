from datetime import date, datetime

from quickpick.digest import DigestEntry, append_entry
from quickpick.modes import NOTES_EMPTY_HINT, Muted, NotesMode, QuickCopyMode


def test_plain_query_searches_the_quick_copy_store(tmp_path):
    store = tmp_path / "quick-copy.txt"
    store.write_text("userid~!~mlessley\nratio a:b~!~3:4\n")
    mode = QuickCopyMode(store)
    mode.reload()

    assert mode.search("userid") == [["userid: mlessley"]]
    assert mode.search("a:b") == [["ratio a:b: 3:4"]]


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
