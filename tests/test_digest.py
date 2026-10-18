from datetime import date, datetime

import pytest

from quickpick.digest import DigestEntry, append_entry, list_days, read_day


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
