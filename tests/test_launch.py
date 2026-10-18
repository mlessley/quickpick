import sys
from pathlib import Path

import pytest

from quickpick import app, launch


@pytest.fixture
def shown(monkeypatch, tmp_path):
    messages: list[str] = []
    monkeypatch.setattr(launch, "show_error", messages.append)
    monkeypatch.setattr(launch, "LOG_PATH", tmp_path / "quickpick.log")
    # gui_main points these at the log; put them back for the rest of the test run
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    return messages


def test_without_a_console_a_startup_failure_is_shown_in_a_message_box(monkeypatch, shown):
    monkeypatch.setattr(app, "main", lambda: sys.exit("Invalid config: bogus hotkey"))

    with pytest.raises(SystemExit):
        launch.gui_main()

    assert shown == ["Invalid config: bogus hotkey"]


def test_a_crash_is_logged_and_points_at_the_log(monkeypatch, shown):
    def crash() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "main", crash)

    with pytest.raises(SystemExit):
        launch.gui_main()

    assert "boom" in launch.LOG_PATH.read_text(encoding="utf-8")
    assert str(launch.LOG_PATH) in shown[0]


def test_the_shortcut_runs_the_console_free_entry_point_with_uvw_from_the_repo():
    repo, uvw = Path("C:/source/repos/quickpick"), Path("C:/Users/me/bin/uvw.exe")

    target, arguments, working_dir = launch.shortcut_command(repo, uvw)

    assert target == uvw
    assert arguments == f'run --project "{repo}" quickpick-gui'
    assert working_dir == repo
