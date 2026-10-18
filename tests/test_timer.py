from datetime import date, datetime, timedelta

from quickpick.digest import read_day
from quickpick.tags import ActiveTags
from quickpick.timer import (
    FocusTimer,
    TimerLauncher,
    format_remaining,
    parse_timer,
)

START = datetime(2026, 10, 16, 9, 0)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def test_timer_queries_are_minutes_then_what_it_is_for():
    assert parse_timer("25 write spec") == (25, "write spec")
    assert parse_timer(" 5 ") == (5, "focus")
    assert parse_timer("write spec") is None
    assert parse_timer("0 nothing") is None
    assert parse_timer("") is None


def test_remaining_time_reads_as_minutes_and_seconds():
    assert format_remaining(timedelta(minutes=18, seconds=42)) == "18:42"
    assert format_remaining(timedelta(seconds=5)) == "0:05"


def test_a_timer_logs_its_start_and_finish_with_the_tags_that_are_on(tmp_path):
    clock, tags = Clock(), ActiveTags()
    tags.toggle("xyz-mtg")
    timer = FocusTimer(tmp_path, tags, clock)

    timer.start(25, "write spec")
    clock.now += timedelta(minutes=10)
    assert format_remaining(timer.remaining()) == "15:00"
    assert timer.check() is False

    clock.now += timedelta(minutes=15)
    assert timer.check() is True
    assert not timer.running

    log = read_day(tmp_path, date(2026, 10, 16))
    assert [entry.text for entry in log] == [
        "started write spec (25 min)",
        "finished write spec (25 min)",
    ]
    assert {entry.kind for entry in log} == {"timer"}
    assert log[1].tags == ("xyz-mtg",)


def test_cancelling_logs_it_and_starting_again_replaces_the_running_timer(tmp_path):
    clock = Clock()
    timer = FocusTimer(tmp_path, ActiveTags(), clock)

    timer.start(25, "write spec")
    timer.start(10, "email")
    timer.cancel()

    assert [entry.text for entry in read_day(tmp_path, date(2026, 10, 16))] == [
        "started write spec (25 min)",
        "cancelled write spec",
        "started email (10 min)",
        "cancelled email",
    ]


def test_t_prefix_starts_a_timer_and_a_bare_t_shows_and_cancels_the_running_one(tmp_path):
    clock = Clock()
    timer = FocusTimer(tmp_path, ActiveTags(), clock)
    launcher = TimerLauncher(timer)

    assert launcher.search("t:25 write spec") == [["Start a 25-minute timer: write spec"]]
    assert launcher.activate("t:25 write spec", (0, 0), alternate=False) is None
    assert timer.running

    clock.now += timedelta(minutes=6, seconds=18)
    assert launcher.search("t:") == [["⏱ 18:42 left · write spec   Enter cancels it"]]
    assert launcher.activate("t:", (0, 0), alternate=False) == ""
    assert not timer.running
