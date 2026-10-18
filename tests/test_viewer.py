import socket
import urllib.request
from datetime import date, datetime

import pytest

from quickpick.app_switch import Window
from quickpick.config import Config
from quickpick.digest import DigestEntry
from quickpick.viewer import (
    BackgroundViewer,
    days_in_window,
    find_viewer_window,
    make_server,
    parse_span,
    render_page,
)

TODAY = date(2026, 10, 16)


def note(day: date, text: str) -> DigestEntry:
    return DigestEntry(time=datetime(day.year, day.month, day.day, 9, 0), kind="note", text=text)


def test_window_covers_the_last_span_calendar_days_including_today():
    days = [date(2026, 9, 16), date(2026, 9, 17), date(2026, 10, 1), TODAY]

    assert days_in_window(days, TODAY, 30) == [date(2026, 9, 17), date(2026, 10, 1), TODAY]
    assert days_in_window(days, TODAY, None) == days


def test_span_comes_from_the_query_and_falls_back_to_30_days():
    assert parse_span("days=60") == 60
    assert parse_span("days=all") is None
    assert parse_span("") == 30
    assert parse_span("days=-5") == 30
    assert parse_span("days=lots") == 30


def test_page_escapes_notes_and_links_screenshots_by_day_and_position():
    oct_14 = [
        note(date(2026, 10, 14), "<b>standup</b>"),
        DigestEntry(
            time=datetime(2026, 10, 14, 9, 5),
            kind="screenshot",
            text="Jira - Board",
            path="C:/shots/board.png",
        ),
        DigestEntry(time=datetime(2026, 10, 14, 9, 9), kind="screenshot", text="Cancelled"),
    ]

    page = render_page(
        [(date(2026, 10, 14), oct_14)], "tok123", span=60, today=TODAY, first_day=date(2026, 10, 14)
    )

    assert "&lt;b&gt;standup&lt;/b&gt;" in page
    assert "<b>standup" not in page
    assert 'src="/image/2026-10-14/1"' in page
    assert 'action="/edit/2026-10-14/1"' in page
    assert 'name="token" value="tok123"' in page
    assert 'name="days" value="60"' in page
    assert "/image/2026-10-14/2" not in page
    assert "no image" in page


def test_page_reads_oldest_day_first_with_a_bar_to_load_earlier_days():
    oct_14, oct_15 = date(2026, 10, 14), date(2026, 10, 15)
    days = [(oct_14, [note(oct_14, "earlier")]), (oct_15, [note(oct_15, "later")])]

    page = render_page(days, "tok", span=30, today=TODAY, first_day=date(2026, 8, 1))

    assert page.index("earlier") < page.index("later")
    assert 'id="d-2026-10-14"' in page
    assert "Showing the last 30 days (since 2026-09-17)" in page
    assert 'href="/?days=60#d-2026-10-14"' in page
    assert 'href="/?days=all#d-2026-10-14"' in page
    assert "Start of digest" not in page


def test_bar_marks_the_start_of_the_digest_once_everything_is_loaded():
    oct_14 = date(2026, 10, 14)

    page = render_page(
        [(oct_14, [note(oct_14, "hi")])], "tok", span=30, today=TODAY, first_day=oct_14
    )

    assert "Start of digest (first entry 2026-10-14)" in page
    assert "?days=" not in page


def test_empty_window_says_so_under_the_bar():
    page = render_page([], "tok", span=30, today=TODAY, first_day=date(2026, 8, 1))

    assert "No entries in the last 30 days" in page
    assert 'href="/?days=60"' in page


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_background_viewer_starts_its_server_once_and_opens_the_page(tmp_path):
    port, opened = free_port(), []
    viewer = BackgroundViewer(
        Config(viewer_port=port), tmp_path, opened.append, reuse_open=lambda: False
    )
    try:
        viewer.open()
        viewer.open()

        url = f"http://127.0.0.1:{port}/"
        assert opened == [url, url]
        assert urllib.request.urlopen(url).status == 200
    finally:
        viewer.close()


def test_background_viewer_opens_the_page_of_a_viewer_already_on_the_port(tmp_path):
    port, opened = free_port(), []
    with socket.socket() as other_viewer:
        other_viewer.bind(("127.0.0.1", port))
        other_viewer.listen()
        viewer = BackgroundViewer(
            Config(viewer_port=port), tmp_path, opened.append, reuse_open=lambda: False
        )

        viewer.open()

        assert opened == [f"http://127.0.0.1:{port}/"]
        assert viewer.server is None


def test_a_second_server_on_the_viewer_port_is_refused(tmp_path):
    config = Config(viewer_port=free_port())
    first = make_server(config, tmp_path)
    try:
        with pytest.raises(OSError):
            make_server(config, tmp_path)
    finally:
        first.server_close()


def test_page_uses_the_configured_theme():
    dark = render_page([], "tok", span=30, today=TODAY, first_day=None)
    light = render_page([], "tok", span=30, today=TODAY, first_day=None, theme="light")

    assert '<html lang="en" data-theme="dark">' in dark
    assert '<html lang="en" data-theme="light">' in light


def test_tags_show_as_chips_linking_to_everything_with_that_tag():
    entries = [
        DigestEntry(time=datetime(2026, 10, 16, 9, 0), kind="note", text="hi", tags=("xyz-mtg",))
    ]

    page = render_page([(TODAY, entries)], "tok", span=30, today=TODAY, first_day=TODAY)

    assert '<a class="tag" href="/?days=all&amp;tag=xyz-mtg">#xyz-mtg</a>' in page


def test_tag_filter_keeps_only_tagged_entries_at_their_original_positions():
    entries = [
        DigestEntry(time=datetime(2026, 10, 16, 9, 0), kind="note", text="untagged"),
        DigestEntry(
            time=datetime(2026, 10, 16, 9, 5),
            kind="screenshot",
            text="shared screen",
            path="C:/shots/a.png",
            tags=("xyz-mtg",),
        ),
    ]
    other_day = [DigestEntry(time=datetime(2026, 10, 15, 9, 0), kind="note", text="nope")]

    page = render_page(
        [(date(2026, 10, 15), other_day), (TODAY, entries)],
        "tok",
        span=None,
        today=TODAY,
        first_day=date(2026, 10, 15),
        tag="xyz-mtg",
    )

    assert "untagged" not in page and "nope" not in page
    assert 'id="d-2026-10-15"' not in page
    assert 'src="/image/2026-10-16/1"' in page
    assert "Everything tagged #xyz-mtg" in page
    assert 'href="/">Back to the log</a>' in page


def test_todos_show_whether_they_are_still_open():
    entries = [
        DigestEntry(time=datetime(2026, 10, 16, 9, 0), kind="todo", text="call Jane"),
        DigestEntry(time=datetime(2026, 10, 16, 9, 5), kind="todo", text="fix build"),
        DigestEntry(
            time=datetime(2026, 10, 16, 9, 9), kind="done", text="fix build", ref="2026-10-16/1"
        ),
    ]

    page = render_page(
        [(TODAY, entries)],
        "tok",
        span=30,
        today=TODAY,
        first_day=TODAY,
        open_todo_ids={"2026-10-16/0"},
    )

    assert "☐ call Jane" in page
    assert page.count("☑ fix build") == 2


def test_labels_link_to_everything_with_that_label_from_any_day():
    entries = [
        DigestEntry(time=datetime(2026, 10, 16, 9, 0), kind="note", text="Bob: done tomorrow"),
        DigestEntry(time=datetime(2026, 10, 16, 9, 5), kind="note", text="js: agreed"),
    ]

    log = render_page([(TODAY, entries)], "tok", span=30, today=TODAY, first_day=TODAY)
    bobs = render_page(
        [(TODAY, entries)], "tok", span=None, today=TODAY, first_day=TODAY, label="bob"
    )

    assert '<a class="label" href="/?days=all&amp;label=bob">Bob:</a> done tomorrow' in log
    assert "done tomorrow" in bobs and "agreed" not in bobs
    assert "Everything labelled bob:" in bobs


def browser_window(hwnd: int, program: str, title: str) -> Window:
    return Window(
        hwnd=hwnd,
        program=program,
        title=title,
        visible=True,
        minimized=False,
        owned=False,
        tool=False,
    )


def test_the_open_viewer_is_the_latest_browser_window_showing_its_page():
    windows = [
        browser_window(1, "Code.exe", "viewer.py - Quickpick digest - Visual Studio Code"),
        browser_window(2, "msedge.exe", "Inbox - Outlook - Microsoft Edge"),
        browser_window(3, "chrome.exe", "Quickpick digest - Google Chrome"),
        browser_window(4, "msedge.exe", "Quickpick digest - Personal - Microsoft Edge"),
    ]

    assert find_viewer_window(windows) == windows[2]
    assert find_viewer_window(windows[:2]) is None


def test_opening_reuses_an_open_viewer_instead_of_a_new_window(tmp_path):
    opened, reused = [], []
    viewer = BackgroundViewer(
        Config(viewer_port=free_port()),
        tmp_path,
        opened.append,
        reuse_open=lambda: reused.append(True) or True,
    )
    try:
        viewer.open()

        assert reused == [True] and opened == []
        # The server still starts, so a viewer left open from an earlier run reloads fine
        assert viewer.server is not None
    finally:
        viewer.close()


def test_each_labelled_line_of_a_note_links_its_label_and_any_finds_the_note():
    note = DigestEntry(
        time=datetime(2026, 10, 18, 9, 0), kind="note", text="Standup\nana: sends the deck"
    )

    log = render_page([(TODAY, [note])], "tok", span=30, today=TODAY, first_day=TODAY)
    anas = render_page(
        [(TODAY, [note])], "tok", span=None, today=TODAY, first_day=TODAY, label="ana"
    )

    link = '<a class="label" href="/?days=all&amp;label=ana">ana:</a>'
    assert f"Standup\n{link} sends the deck" in log
    assert "Standup" in anas
