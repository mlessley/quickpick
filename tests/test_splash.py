from datetime import datetime
from pathlib import Path

from quickpick.config import AppShortcut, Config
from quickpick.digest import DigestEntry
from quickpick.launchers import StoreLauncher
from quickpick.splash import format_key, hotkey_groups, today_line


def entry(hour: int, minute: int, kind: str, text: str) -> DigestEntry:
    return DigestEntry(time=datetime(2026, 10, 16, hour, minute), kind=kind, text=text)


def test_keys_are_shown_the_way_they_are_pressed():
    assert format_key("ctrl+alt+space") == "Ctrl+Alt+Space"
    assert format_key("ctrl+o") == "Ctrl+O"
    assert format_key("alt+f5") == "Alt+F5"


def test_hotkey_list_comes_from_the_config_and_the_launchers():
    config = Config(
        summon_hotkey="ctrl+shift+q",
        apps=[
            AppShortcut(key="ctrl+k", name="Paint", program="mspaint.exe"),
            AppShortcut(key="alt+1", name="Notepad", program="notepad.exe"),
        ],
    )
    launchers = [
        StoreLauncher("g", "Repo shortcuts", Path("unused.txt")),
        StoreLauncher("w", "Wiki", Path("unused.txt")),
    ]

    groups = dict(hotkey_groups(config, launchers))

    assert list(groups) == [
        "Anywhere",
        "In the popup",
        "Notes",
        "Stash",
        "Bookmarks",
        "Commands",
        "Apps",
        "Settings",
    ]
    assert groups["Anywhere"][0] == ("Ctrl+Shift+Q", "Show or hide the popup")
    assert ("Ctrl+H", "This help") in groups["In the popup"]
    # The help scrolls, so each app and command gets its own row again
    assert groups["Apps"] == [("Ctrl+K", "Paint"), ("Alt+1", "Notepad")]
    assert groups["Commands"] == [("/g", "Repo shortcuts"), ("/w", "Wiki")]
    assert groups["Settings"][0] == ("Ctrl+,", "Open config.json (restart to apply)")


def test_apps_group_is_left_out_when_none_are_configured():
    groups = dict(hotkey_groups(Config(apps=[]), []))

    assert "Apps" not in groups


def test_today_line_counts_notes_and_screenshots_and_quotes_the_last_note():
    entries = [
        entry(9, 5, "note", "standup"),
        entry(9, 30, "screenshot", "Jira - Board"),
        entry(10, 42, "note", "reviewed PR 42"),
        entry(11, 0, "screenshot", "Teams"),
    ]

    assert today_line(entries) == (
        'Today: 2 notes · 2 screenshots · last note 10:42 "reviewed PR 42"'
    )


def test_today_line_uses_singulars_and_shortens_a_long_last_note():
    long_note = "x" * 80

    line = today_line([entry(8, 0, "note", long_note)])

    assert line.startswith("Today: 1 note · last note 08:00 ")
    assert line.endswith('…"')
    assert len(line) < 100


def test_today_line_when_nothing_is_logged_yet():
    assert today_line([]) == "Nothing logged yet today"


def test_today_line_counts_only_notes_and_screenshots():
    entries = [entry(9, 0, "note", "standup"), entry(9, 5, "todo", "call Jane")]
    entries.append(entry(9, 6, "timer", "started focus (25 min)"))

    assert today_line(entries) == 'Today: 1 note · last note 09:00 "standup"'
