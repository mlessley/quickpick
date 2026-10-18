from datetime import date, datetime

from quickpick.digest import DigestEntry, append_entry, open_todos, read_day
from quickpick.modes import NotesMode
from quickpick.splash import todos_line
from quickpick.tags import ActiveTags

WEDNESDAY, FRIDAY = date(2026, 10, 14), date(2026, 10, 16)


def at(day: date, hour: int, kind: str, text: str, **fields) -> DigestEntry:
    return DigestEntry(
        time=datetime(day.year, day.month, day.day, hour, 0), kind=kind, text=text, **fields
    )


def test_todos_stay_open_across_days_until_a_done_entry_points_at_them(tmp_path):
    append_entry(tmp_path, at(WEDNESDAY, 9, "todo", "call Jane"))
    append_entry(tmp_path, at(WEDNESDAY, 10, "todo", "fix build"))
    append_entry(tmp_path, at(FRIDAY, 9, "done", "fix build", ref="2026-10-14/1"))
    append_entry(tmp_path, at(FRIDAY, 10, "todo", "book room"))

    assert [(todo_id, entry.text) for todo_id, entry in open_todos(tmp_path)] == [
        ("2026-10-14/0", "call Jane"),
        ("2026-10-16/1", "book room"),
    ]


def test_brackets_make_a_todo_with_the_tags_that_are_on(tmp_path):
    tags = ActiveTags()
    tags.toggle("xyz-mtg")
    notes = NotesMode(tmp_path, today=lambda: FRIDAY, tags=tags)
    notes.reload()

    notes.activate("[] send the deck", None, alternate=False)
    notes.activate("[]   ", None, alternate=False)

    [entry] = read_day(tmp_path, date.today())
    assert (entry.kind, entry.text, entry.tags) == ("todo", "send the deck", ("xyz-mtg",))


def test_open_todos_list_above_the_log_and_say_which_day_they_are_from(tmp_path):
    append_entry(tmp_path, at(WEDNESDAY, 9, "todo", "call Jane"))
    append_entry(tmp_path, at(FRIDAY, 9, "todo", "book room", tags=("ops",)))
    notes = NotesMode(tmp_path, today=lambda: FRIDAY)
    notes.reload()

    todos, log = notes.search("")

    assert todos == ["☐ call Jane   · Wed 10-14", "☐ #ops book room"]
    assert log[-1] == "09:00  #ops ☐ book room"


def test_ticking_off_the_selected_todo_logs_done_and_removes_it(tmp_path):
    append_entry(tmp_path, at(WEDNESDAY, 9, "todo", "call Jane", tags=("ops",)))
    append_entry(tmp_path, at(WEDNESDAY, 10, "todo", "fix build"))
    notes = NotesMode(tmp_path, today=lambda: FRIDAY)
    notes.reload()

    notes.complete((0, 1))

    assert [entry.text for _id, entry in open_todos(tmp_path)] == ["call Jane"]
    [done] = read_day(tmp_path, date.today())
    assert (done.kind, done.text, done.ref) == ("done", "fix build", "2026-10-14/1")
    assert notes.search("")[0] == ["☐ #ops call Jane   · Wed 10-14"]


def test_splash_lists_the_first_few_open_todos():
    todos = [
        ("a/0", at(FRIDAY, 9, "todo", text))
        for text in ("call Jane", "fix build", "book room", "email Raj")
    ]

    assert todos_line(todos) == "4 open todos: call Jane · fix build · book room · …"
    assert todos_line(todos[:1]) == "1 open todo: call Jane"
    assert todos_line([]) is None
