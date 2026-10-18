import pytest

from quickpick.app_switch import Window, app_key_sequences, pick_window


def window(hwnd: int, program: str, title: str, **flags: bool) -> Window:
    return Window(
        hwnd=hwnd,
        program=program,
        title=title,
        visible=flags.get("visible", True),
        minimized=flags.get("minimized", False),
        owned=flags.get("owned", False),
        tool=flags.get("tool", False),
    )


def test_picks_the_most_recent_window_of_the_program_ignoring_case():
    windows = [
        window(1, "Code.exe", "quickpick - Visual Studio Code"),
        window(2, "notepad.exe", "todo.txt - Notepad"),
        window(3, "Notepad.exe", "older.txt - Notepad"),
    ]

    assert pick_window(windows, "NOTEPAD.EXE", None) == windows[1]


def test_minimized_windows_count_but_hidden_owned_tool_and_untitled_ones_do_not():
    windows = [
        window(1, "ms-teams.exe", "TeamsMessageWindow", visible=False),
        window(2, "ms-teams.exe", "Meeting toolbar", owned=True),
        window(3, "ms-teams.exe", "Sharing", tool=True),
        window(4, "ms-teams.exe", ""),
        window(5, "ms-teams.exe", "Chat | Microsoft Teams", minimized=True),
    ]

    assert pick_window(windows, "ms-teams.exe", None) == windows[4]


def test_title_narrows_to_windows_containing_it_ignoring_case():
    windows = [
        window(1, "OUTLOOK.EXE", "RE: lunch - Message (HTML)"),
        window(2, "OUTLOOK.EXE", "Inbox - me@example.com - Outlook"),
    ]

    assert pick_window(windows, "outlook.exe", "inbox") == windows[1]


def test_no_matching_window_gives_none():
    assert pick_window([window(1, "Code.exe", "x")], "OUTLOOK.EXE", None) is None


def test_app_keys_become_tk_sequences_that_also_fire_with_caps_lock():
    assert app_key_sequences("ctrl+o") == ["<Control-o>", "<Control-O>"]
    assert app_key_sequences("Ctrl+Alt+T") == ["<Control-Alt-t>", "<Control-Alt-T>"]
    assert app_key_sequences("alt+f5") == ["<Alt-F5>"]
    assert app_key_sequences("f9") == ["<F9>"]


@pytest.mark.parametrize("spec", ["o", "ctrl+shift+o", "ctrl+bogus", "ctrl+"])
def test_rejects_app_keys_that_are_typing_or_unsupported(spec):
    with pytest.raises(ValueError):
        app_key_sequences(spec)
