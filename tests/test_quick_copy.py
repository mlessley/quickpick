from quickpick.quick_copy import QuickCopyEntry, filter_entries, parse_store


def test_parses_single_unmasked_entry():
    entries = parse_store("greeting~!~hello world")

    assert entries == [QuickCopyEntry(key="greeting", value="hello world", masked=False)]


def test_empty_query_returns_all_entries():
    entries = [
        QuickCopyEntry(key="userid", value="mlessley", masked=False),
        QuickCopyEntry(key="greeting", value="hello world", masked=False),
    ]

    assert filter_entries(entries, "") == entries


def test_filter_matches_display_text_case_insensitively():
    entries = [
        QuickCopyEntry(key="userid", value="mlessley", masked=False),
        QuickCopyEntry(key="greeting", value="hello world", masked=False),
    ]

    assert filter_entries(entries, "USER") == [entries[0]]


def test_unmasked_entry_display_text_shows_key_and_value():
    entry = QuickCopyEntry(key="greeting", value="hello world", masked=False)

    assert entry.display_text == "greeting: hello world"


def test_masked_entry_display_text_hides_value():
    entry = QuickCopyEntry(key="api-token", value="abc123", masked=True)

    assert entry.display_text == "api-token"


def test_only_splits_on_first_delimiter():
    entries = parse_store("db~!~host~!~5432")

    assert entries == [QuickCopyEntry(key="db", value="host~!~5432", masked=False)]


def test_strips_leading_star_and_marks_entry_masked():
    entries = parse_store("*api-token~!~abc123")

    assert entries == [QuickCopyEntry(key="api-token", value="abc123", masked=True)]


def test_skips_blank_lines():
    entries = parse_store("greeting~!~hello world\n\nuserid~!~mlessley\n")

    assert entries == [
        QuickCopyEntry(key="greeting", value="hello world", masked=False),
        QuickCopyEntry(key="userid", value="mlessley", masked=False),
    ]


def test_parses_multiple_entries_in_file_order():
    entries = parse_store("greeting~!~hello world\nuserid~!~mlessley")

    assert entries == [
        QuickCopyEntry(key="greeting", value="hello world", masked=False),
        QuickCopyEntry(key="userid", value="mlessley", masked=False),
    ]
