import pytest
from pydantic import ValidationError

from quickpick.config import ensure_config, load_config


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


def _searches(tmp_path, searches: str):
    path = tmp_path / "config.json"
    path.write_text(f'{{"searches": {searches}}}')
    return load_config(path).searches


def test_no_web_searches_by_default(tmp_path):
    assert load_config(tmp_path / "config.json").searches == []


def test_web_searches_are_read_with_lowercase_commands(tmp_path):
    [people] = _searches(
        tmp_path, '[{"command": "P", "name": "People", "url": "https://x.test/?q={query}"}]'
    )

    assert (people.command, people.name, people.url) == ("p", "People", "https://x.test/?q={query}")


@pytest.mark.parametrize(
    "search",
    [
        '{"command": "p", "name": "People", "url": "https://x.test/"}',
        '{"command": "g", "name": "Clash", "url": "https://x.test/?q={query}"}',
        '{"command": "p q", "name": "Space", "url": "https://x.test/?q={query}"}',
        '{"command": "/p", "name": "Slash", "url": "https://x.test/?q={query}"}',
        '{"command": "p", "name": "Script", "url": "javascript:alert({query})"}',
    ],
)
def test_rejects_a_web_search_without_a_query_slot_or_with_a_bad_command(tmp_path, search):
    with pytest.raises(ValidationError):
        _searches(tmp_path, f"[{search}]")


def test_rejects_two_web_searches_with_the_same_command(tmp_path):
    with pytest.raises(ValidationError, match="w"):
        _searches(
            tmp_path,
            '[{"command": "w", "name": "A", "url": "https://a.test/?q={query}"},'
            ' {"command": "W", "name": "B", "url": "https://b.test/?q={query}"}]',
        )


def test_ensure_config_writes_a_working_sample_when_there_is_none(tmp_path):
    path = tmp_path / "data" / "config.json"

    ensure_config(path)

    config = load_config(path)
    assert config.searches and all("example.com" in s.url for s in config.searches)


def test_ensure_config_leaves_an_existing_config_alone(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"theme": "light"}')

    ensure_config(path)

    assert path.read_text() == '{"theme": "light"}'
