from datetime import date, datetime

from quickpick.digest import DigestEntry, append_entry, read_day
from quickpick.modes import NotesMode, TagMenu
from quickpick.tags import (
    ActiveTags,
    label_status,
    parse_tag_query,
    recent_labels,
    recent_tags,
    typed_label,
)

TODAY = date(2026, 10, 16)


def tagged(day: int, hour: int, *tags: str) -> DigestEntry:
    return DigestEntry(time=datetime(2026, 10, day, hour, 0), kind="note", text="x", tags=tags)


def test_toggling_turns_a_tag_on_and_off_ignoring_case_and_the_hash():
    tags = ActiveTags()

    tags.toggle("#XYZ-mtg")
    tags.toggle("ops")
    assert tags.active == ["xyz-mtg", "ops"]

    tags.toggle("xyz-MTG")
    assert tags.active == ["ops"]

    tags.clear()
    assert tags.active == []


def test_a_lone_hash_word_is_a_tag_query_but_a_sentence_is_a_note():
    assert parse_tag_query("#xyz-mtg") == "xyz-mtg"
    assert parse_tag_query("#") == ""
    assert parse_tag_query("#xyz-mtg notes from the call") is None
    assert parse_tag_query("plain note") is None
    assert parse_tag_query("#no!good") is None


def test_recent_tags_are_most_recently_used_first(tmp_path):
    append_entry(tmp_path, tagged(14, 9, "old", "ops"))
    append_entry(tmp_path, tagged(15, 9, "budget"))
    append_entry(tmp_path, tagged(15, 10, "ops"))

    assert recent_tags(tmp_path) == ["ops", "budget", "old"]


def test_tag_menu_offers_the_typed_tag_first_then_matching_recent_ones(tmp_path):
    append_entry(tmp_path, tagged(15, 9, "xyz-mtg", "xyz-review", "ops"))
    tags = ActiveTags()
    tags.toggle("xyz-review")
    menu = TagMenu(tags, tmp_path)
    menu.reload()

    assert menu.search("#xyz") == [["#xyz   new tag", "#xyz-review   on", "#xyz-mtg"]]
    assert menu.search("#") == [["#xyz-review   on", "#xyz-mtg", "#ops"]]


def test_enter_in_the_tag_menu_toggles_the_selected_tag_and_clears_the_query(tmp_path):
    tags = ActiveTags()
    menu = TagMenu(tags, tmp_path)
    menu.reload()
    menu.search("#new-one")

    assert menu.activate("#new-one", (0, 0), alternate=False) == ""
    assert tags.active == ["new-one"]


def test_notes_and_todos_carry_the_tags_that_are_on(tmp_path):
    tags = ActiveTags()
    tags.toggle("xyz-mtg")
    notes = NotesMode(tmp_path, tags=tags)
    notes.reload()

    notes.activate("decided to ship Friday", None, alternate=False)

    [entry] = read_day(tmp_path, date.today())
    assert entry.tags == ("xyz-mtg",)


def test_recent_labels_are_most_recently_used_first(tmp_path):
    for day, hour, text in ((14, 9, "js: old"), (15, 9, "Bob: one"), (15, 10, "js: two")):
        entry = DigestEntry(time=datetime(2026, 10, day, hour, 0), kind="note", text=text)
        append_entry(tmp_path, entry)

    assert recent_labels(tmp_path) == ["js", "bob"]


def test_the_label_being_typed_is_found_once_the_colon_and_space_are_there():
    assert typed_label("bob: will send") == "bob"
    assert typed_label("[] Bob: chase budget") == "bob"
    assert typed_label("bob:") is None
    assert typed_label("https://example.com") is None
    assert typed_label("plain note") is None


def test_a_new_label_close_to_a_known_one_suggests_it():
    known = ["bob", "betty", "js"]

    assert label_status("bob", known) == (True, None)
    assert label_status("bobb", known) == (False, "bob")
    assert label_status("url", known) == (False, None)
