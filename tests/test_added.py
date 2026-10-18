from datetime import datetime

import pytest

from quickpick.added import AddedEntry, AddedList, parse_addition

AT = datetime(2026, 10, 18, 14, 5)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("10.0.0.1", (None, "10.0.0.1", False)),
        ("vpn ~!~ 10.0.0.1", ("vpn", "10.0.0.1", False)),
        ("vpn~!~10.0.0.1", ("vpn", "10.0.0.1", False)),
        ("*abc123", (None, "abc123", True)),
        ("*token ~!~ abc123", ("token", "abc123", True)),
        ("line one\nline two\n", (None, "line one\nline two", False)),
        ("  indented\n  block", (None, "  indented\n  block", False)),
        ("", None),
        ("  ", None),
        ("vpn ~!~ ", None),
        ("*", None),
    ],
)
def test_reads_an_addition_from_the_query(query, expected):
    assert parse_addition(query) == expected


def test_a_short_value_is_its_own_label():
    entry = AddedEntry(AT, None, "10.0.0.1", False)

    assert entry.display_text == "10.0.0.1"


def test_a_long_or_multiline_value_is_cut_short_with_its_size():
    value = "SELECT id, name\nFROM users\nWHERE active = 1 AND created > '2026-01-01'"
    entry = AddedEntry(AT, None, value, False)

    assert entry.display_text == (
        "SELECT id, name ⏎ FROM users ⏎ WHERE active…  +30 chars · 3 lines"
    )


def test_a_typed_label_shows_before_the_value():
    assert AddedEntry(AT, "vpn", "10.0.0.1", False).display_text == "vpn: 10.0.0.1"


def test_a_masked_value_never_shows_or_labels_itself():
    assert AddedEntry(AT, None, "abc123", True).display_text == "masked · 6 chars · 14:05"
    assert AddedEntry(AT, "token", "abc123", True).display_text == (
        "token · masked · 6 chars · 14:05"
    )
    assert AddedEntry(AT, "my secret", "a\nb\nc", True).display_text == (
        "my secret · masked · 5 chars · 3 lines · 14:05"
    )


def test_added_entries_are_kept_newest_first(tmp_path):
    added = AddedList(tmp_path / "stash-added.jsonl", limit=100)
    added.add(AddedEntry(AT, None, "first", False))
    added.add(AddedEntry(AT, "b", "second\nline", False))

    reread = AddedList(tmp_path / "stash-added.jsonl", limit=100)
    reread.reload()
    assert [entry.value for entry in reread.entries] == ["second\nline", "first"]
    assert reread.entries[0].label == "b"


def test_adding_an_identical_value_moves_it_to_the_top(tmp_path):
    added = AddedList(tmp_path / "stash-added.jsonl", limit=100)
    for value in ("a", "b", "a"):
        added.add(AddedEntry(AT, None, value, False))

    assert [entry.value for entry in added.entries] == ["a", "b"]


def test_only_the_newest_are_kept(tmp_path):
    added = AddedList(tmp_path / "stash-added.jsonl", limit=2)
    for value in ("a", "b", "c"):
        added.add(AddedEntry(AT, None, value, False))

    assert [entry.value for entry in added.entries] == ["c", "b"]


def test_removes_an_entry(tmp_path):
    added = AddedList(tmp_path / "stash-added.jsonl", limit=100)
    for value in ("a", "b"):
        added.add(AddedEntry(AT, None, value, False))

    added.remove(added.entries[0])

    added.reload()
    assert [entry.value for entry in added.entries] == ["a"]


def test_a_missing_file_is_an_empty_list(tmp_path):
    added = AddedList(tmp_path / "stash-added.jsonl", limit=100)
    added.reload()

    assert added.entries == []


def test_search_matches_label_and_value_but_not_a_masked_value():
    entries = [
        AddedEntry(AT, None, "select *\nfrom orders", False),
        AddedEntry(AT, "token", "orders-secret", True),
    ]

    assert AddedList.filter(entries, "ORDERS") == [entries[0]]
    assert AddedList.filter(entries, "token") == [entries[1]]


def test_a_line_spoiled_by_hand_is_skipped(tmp_path):
    path = tmp_path / "stash-added.jsonl"
    path.write_text(
        '{"time": "2026-10-18T14:05:00", "value": "kept"}\nnot json\n{"value": "no time"}\n',
        encoding="utf-8",
    )
    added = AddedList(path, limit=100)
    added.reload()

    assert [entry.value for entry in added.entries] == ["kept"]
