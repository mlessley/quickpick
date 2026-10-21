from datetime import date, datetime

import pytest

from quickpick.digest import (
    DigestEntry,
    append_entry,
    carried_label,
    day_labels,
    line_labels,
    list_days,
    one_line,
    open_todos,
    read_day,
)


def test_entries_read_back_in_the_order_they_were_appended(tmp_path):
    note = DigestEntry(time=datetime(2026, 10, 14, 9, 30), kind="note", text="standup: ship 04")
    shot = DigestEntry(
        time=datetime(2026, 10, 14, 9, 45),
        kind="screenshot",
        text="Jira - Sprint board",
        path="C:/shots/board.png",
    )

    append_entry(tmp_path, note)
    append_entry(tmp_path, shot)

    assert read_day(tmp_path, date(2026, 10, 14)) == [note, shot]


def test_each_day_reads_only_its_own_entries(tmp_path):
    yesterday = DigestEntry(time=datetime(2026, 10, 13, 17, 0), kind="note", text="wrap up")
    today = DigestEntry(time=datetime(2026, 10, 14, 8, 0), kind="note", text="start")

    append_entry(tmp_path, yesterday)
    append_entry(tmp_path, today)

    assert read_day(tmp_path, date(2026, 10, 14)) == [today]
    assert read_day(tmp_path, date(2026, 10, 12)) == []


def test_lists_days_with_logs_oldest_first(tmp_path):
    for day in (13, 15, 14):
        entry = DigestEntry(time=datetime(2026, 10, day, 9, 0), kind="note", text="hi")
        append_entry(tmp_path, entry)
    (tmp_path / "notes.txt").write_text("not a log")

    assert list_days(tmp_path) == [date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]


def test_tags_and_references_round_trip_and_are_left_out_of_the_log_when_unset(tmp_path):
    tagged = DigestEntry(
        time=datetime(2026, 10, 16, 9, 0), kind="todo", text="call Jane", tags=("xyz-mtg",)
    )
    done = DigestEntry(
        time=datetime(2026, 10, 16, 11, 0), kind="done", text="call Jane", ref="2026-10-16/0"
    )
    plain = DigestEntry(time=datetime(2026, 10, 16, 12, 0), kind="note", text="lunch")

    for entry in (tagged, done, plain):
        append_entry(tmp_path, entry)

    assert read_day(tmp_path, date(2026, 10, 16)) == [tagged, done, plain]
    last_line = (tmp_path / "2026-10-16.jsonl").read_text().splitlines()[-1]
    assert "tags" not in last_line and "ref" not in last_line


def test_display_text_marks_each_kind_and_shows_tags_first():
    def shown(kind: str, tags: tuple[str, ...] = ()) -> str:
        return DigestEntry(
            time=datetime(2026, 10, 16, 9, 5), kind=kind, text="x", tags=tags
        ).display_text

    assert shown("note") == "09:05  x"
    assert shown("note", ("xyz-mtg", "ops")) == "09:05  #xyz-mtg #ops x"
    assert shown("screenshot") == "09:05  [screenshot] x"
    assert shown("todo") == "09:05  ☐ x"
    assert shown("done") == "09:05  ☑ x"
    assert shown("timer") == "09:05  ⏱ x"


def test_a_note_of_several_lines_shows_its_first_line_and_how_many_more():
    entry = DigestEntry(
        time=datetime(2026, 10, 18, 9, 5), kind="note", text="idea: summary page\n- by week\n- tags"
    )

    assert entry.display_text == "09:05  idea: summary page  (+2 lines)"
    assert entry.label == "idea"
    assert one_line("one\ntwo") == "one  (+1 line)"
    assert one_line("one") == "one"


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("bob: the project will be done tomorrow", "bob"),
        ("js: agreed", "js"),
        ("url: https://example.com/spec", "url"),
        ("Bob: fine", "bob"),
        ("https://example.com", None),
        ("10:30 call moved", None),
        ("t:25 write spec", None),
        ("t: said we're late", "t"),
        ("plain note", None),
    ],
)
def test_a_note_starting_with_a_word_colon_space_has_that_label(text, label):
    entry = DigestEntry(time=datetime(2026, 10, 16, 9, 0), kind="note", text=text)

    assert entry.label == label


def test_todos_and_their_done_entries_have_labels_but_screenshots_do_not():
    def entry(kind: str) -> DigestEntry:
        return DigestEntry(time=datetime(2026, 10, 16, 9, 0), kind=kind, text="Bob: send deck")

    assert (entry("todo").label, entry("done").label) == ("bob", "bob")
    assert entry("screenshot").label is None


def test_every_line_of_a_note_can_carry_a_label_but_a_todos_only_its_first():
    def entry(kind: str) -> DigestEntry:
        return DigestEntry(
            time=datetime(2026, 10, 18, 9, 0),
            kind=kind,
            text="Standup\nana: sends the deck\nben: owns QA\nANA: and the notes",
        )

    assert entry("note").labels == ("ana", "ben")
    assert entry("note").label is None
    assert entry("todo").labels == ()


def test_continuation_lines_carry_the_label_before_them():
    def note(minute: int, text: str, kind: str = "note") -> DigestEntry:
        return DigestEntry(time=datetime(2026, 10, 20, 9, minute), kind=kind, text=text)

    entries = [
        note(0, "ana: sends the deck"),
        note(1, "... and the notes"),
        note(2, "Room - Notepad", kind="screenshot"),
        note(3, "…by Friday"),
        note(4, "plain line"),
        note(5, "... nothing to carry"),
        note(6, "Standup\nben: owns QA\n... and the release\nother\n... not ben"),
    ]

    assert line_labels(entries) == [
        [("ana", False)],
        [("ana", True)],
        [],
        [("ana", True)],
        [(None, False)],
        [(None, False)],
        [(None, False), ("ben", False), ("ben", True), (None, False), (None, False)],
    ]
    assert day_labels(entries)[1] == ("ana",)
    assert carried_label(entries) is None
    assert carried_label(entries[:4]) == "ana"


def test_hand_edited_lines_keep_their_places(tmp_path):
    (tmp_path / "2026-10-20.jsonl").write_text(
        '{"time": "2026-10-20T09:00:00", "kind": "todo", "text": "first"}\n'
        "{}\n"
        "not json\n"
        '{"time": "2026-10-20T09:03:00", "kind": "todo", "text": "fourth"}\n'
        "\n"
        '{"time": "2026-10-20T09:05:00", "kind": "done", "text": "fourth",'
        ' "ref": "2026-10-20/3"}\n',
        encoding="utf-8",
    )

    entries = read_day(tmp_path, date(2026, 10, 20))

    assert [entry.kind for entry in entries] == ["todo", "deleted", "unreadable", "todo", "done"]
    assert entries[2].text == "line 3 of 2026-10-20.jsonl couldn't be read"
    # The done entry still points at "fourth", so only "first" is open
    assert [todo.text for _id, todo in open_todos(tmp_path)] == ["first"]
