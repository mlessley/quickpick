import pytest
from pydantic import ValidationError

from quickpick.config import load_config


def test_missing_file_uses_default_summon_hotkey(tmp_path):
    config = load_config(tmp_path / "config.json")

    assert config.summon_hotkey == "ctrl+alt+space"


def test_rejects_malformed_summon_hotkey(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"summon_hotkey": "ctrl+alt+bogus"}')

    with pytest.raises(ValidationError, match="bogus"):
        load_config(path)


def test_outlook_and_teams_are_the_default_apps(tmp_path):
    config = load_config(tmp_path / "config.json")

    assert [(app.key, app.program) for app in config.apps] == [
        ("ctrl+o", "OUTLOOK.EXE"),
        ("ctrl+t", "ms-teams.exe"),
    ]


def test_configured_apps_replace_the_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"apps": [{"key": "ctrl+k", "name": "Paint", "program": "mspaint.exe", "title": "x"}]}'
    )

    [paint] = load_config(path).apps

    assert (paint.name, paint.title) == ("Paint", "x")


@pytest.mark.parametrize(
    "key", ["ctrl+n", "ctrl+h", "ctrl+p", "ctrl+d", "ctrl+q", "Ctrl+V", "f2", "ctrl+bogus"]
)
def test_rejects_app_keys_the_popup_already_uses_or_cannot_bind(tmp_path, key):
    path = tmp_path / "config.json"
    path.write_text(f'{{"apps": [{{"key": "{key}", "name": "X", "program": "x.exe"}}]}}')

    with pytest.raises(ValidationError):
        load_config(path)


def test_rejects_two_apps_on_the_same_key(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"apps": [{"key": "ctrl+o", "name": "A", "program": "a.exe"},'
        ' {"key": "Ctrl+O", "name": "B", "program": "b.exe"}]}'
    )

    with pytest.raises(ValidationError, match=r"ctrl\+o"):
        load_config(path)


def test_theme_defaults_to_dark_and_rejects_unknown_themes(tmp_path):
    assert load_config(tmp_path / "config.json").theme == "dark"

    path = tmp_path / "config.json"
    path.write_text('{"theme": "purple"}')
    with pytest.raises(ValidationError):
        load_config(path)
