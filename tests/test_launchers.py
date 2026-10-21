import pytest

from quickpick.launchers import CommandMenu, StoreLauncher, command_text, jira_target, route


@pytest.fixture
def repos(tmp_path):
    store = tmp_path / "launcher.txt"
    store.write_text(
        "quickpick~!~https://github.com/mlessley/quickpick\n"
        "dotfiles~!~https://github.com/example/dotfiles\n"
    )
    launcher = StoreLauncher("g", "Repo shortcuts", store)
    launcher.reload()
    return launcher


def test_store_launcher_searches_the_text_after_its_command(repos):
    assert repos.search("quick") == [["quickpick  (https://github.com/mlessley/quickpick)"]]


def test_a_slash_command_goes_to_its_launcher_and_a_bare_slash_to_the_menu(repos):
    menu = CommandMenu([repos])

    assert route("/g quick", [repos], menu) is repos
    assert route("/G", [repos], menu) is repos
    assert route("/", [repos], menu) is menu
    assert route("/re", [repos], menu) is menu
    assert route("quick", [repos], menu) is None
    # The retired forms are plain text now
    assert route("g:quick", [repos], menu) is None
    assert route(":g:quick", [repos], menu) is None


def test_a_slash_line_the_menu_cannot_match_goes_back_to_the_mode(repos):
    # e.g. "/etc/hosts fixed" in notes is a note, and the notes list stays in view
    menu = CommandMenu([repos])

    assert route("/etc/hosts fixed", [repos], menu) is None
    assert route("/x note", [repos], menu) is None
    assert route("/zzz", [repos], menu) is None


def test_a_launcher_gets_the_text_after_its_command():
    assert command_text("/g quick") == "quick"
    assert command_text("/t 25 write spec") == "25 write spec"
    assert command_text("/j") == ""


def test_command_menu_lists_commands_and_fills_in_the_chosen_one(repos):
    menu = CommandMenu([repos])

    assert menu.search("/") == [["/g  Repo shortcuts"]]
    assert menu.search("/repo") == [["/g  Repo shortcuts"]]
    assert menu.search("/zzz") == [[]]
    menu.search("/")
    assert menu.activate("/", (0, 0), alternate=False) == "/g "


BASE = "https://example.atlassian.net"


@pytest.mark.parametrize(
    ("rest", "expected"),
    [
        ("", ("Open PROJ (default project)", f"{BASE}/browse/PROJ")),
        ("123", ("PROJ-123 (default project)", f"{BASE}/browse/PROJ-123")),
        (" abc-42 ", ("ABC-42", f"{BASE}/browse/ABC-42")),
        (
            "login bug",
            (
                'Search Jira for "login bug"',
                f"{BASE}/issues/?jql=text%20~%20%22login%20bug%22",
            ),
        ),
    ],
)
def test_jira_target_resolves_digits_keys_and_text(rest, expected):
    assert jira_target(rest, BASE + "/", "PROJ") == expected
