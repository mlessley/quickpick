import pytest

from quickpick import launchers
from quickpick.launchers import (
    CommandMenu,
    JiraLauncher,
    JiraTarget,
    SearchLauncher,
    StoreLauncher,
    command_text,
    jira_target,
    route,
)
from quickpick.modes import Muted


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
        ("", JiraTarget("Open PROJ (default project)", f"{BASE}/browse/PROJ")),
        (
            "123",
            JiraTarget("PROJ-123 (default project)", f"{BASE}/browse/PROJ-123", None, "PROJ-123"),
        ),
        (" abc-42 ", JiraTarget("ABC-42", f"{BASE}/browse/ABC-42", None, "ABC-42")),
        (
            "123 login fails on SSO",
            JiraTarget(
                "PROJ-123 login fails on SSO (default project)",
                f"{BASE}/browse/PROJ-123",
                "PROJ-123 login fails on SSO",
                "PROJ-123",
            ),
        ),
        (
            "abc-42 export",
            JiraTarget("ABC-42 export", f"{BASE}/browse/ABC-42", "ABC-42 export", "ABC-42"),
        ),
        (
            "https://jira.test/browse/PROJ-77",
            JiraTarget("Open PROJ-77", "https://jira.test/browse/PROJ-77", None, "PROJ-77"),
        ),
        (
            "https://jira.test/board?rapidView=12 Sprint board",
            JiraTarget(
                "Open Sprint board",
                "https://jira.test/board?rapidView=12",
                "Sprint board",
                "https://jira.test/board?rapidView=12",
            ),
        ),
        (
            "login bug",
            JiraTarget(
                'Search Jira for "login bug"',
                f"{BASE}/issues/?jql=text%20~%20%22login%20bug%22",
            ),
        ),
    ],
)
def test_jira_target_resolves_digits_keys_urls_and_text(rest, expected):
    assert jira_target(rest, BASE + "/", "PROJ") == expected


def jira(tmp_path, text: str = "") -> JiraLauncher:
    path = tmp_path / "jira.txt"
    if text:
        path.write_text(text, encoding="utf-8")
    launcher = JiraLauncher("j", BASE, "PROJ", path)
    launcher.reload()
    return launcher


LIST = (
    "PROJ-1 login fails ~!~ https://jira.test/browse/PROJ-1\n"
    "! Sprint board ~!~ https://jira.test/board\n"
)


def test_jira_lists_the_pins_then_recent_links_under_what_is_typed(tmp_path):
    launcher = jira(tmp_path, LIST)

    assert launcher.search("") == [
        ["Open PROJ (default project)", "📌 Sprint board", "PROJ-1 login fails"]
    ]
    assert launcher.search("login") == [['Search Jira for "login"', "PROJ-1 login fails"]]
    assert launcher.search("1 more") == [["PROJ-1 more (default project)", "PROJ-1 login fails"]]


def test_opening_an_issue_remembers_it_at_the_top(tmp_path, opened):
    launcher = jira(tmp_path, LIST)
    launcher.search("5 flaky test")

    launcher.activate("5 flaky test", (0, 0), alternate=False)

    assert opened == [(f"{BASE}/browse/PROJ-5", "edge")]
    assert jira(tmp_path).search("")[0][1:] == [
        "📌 Sprint board",
        "PROJ-5 flaky test",
        "PROJ-1 login fails",
    ]


def test_opening_a_listed_link_moves_it_to_the_top(tmp_path, opened):
    launcher = jira(tmp_path, LIST + "PROJ-2 ~!~ https://jira.test/browse/PROJ-2\n")
    launcher.search("")

    launcher.activate("", (0, 3), alternate=True)

    assert opened == [("https://jira.test/browse/PROJ-2", "chrome")]
    assert jira(tmp_path).search("")[0][2:] == ["PROJ-2", "PROJ-1 login fails"]


def test_a_text_search_is_not_remembered(tmp_path, opened):
    launcher = jira(tmp_path)
    launcher.search("login bug")

    launcher.activate("login bug", (0, 0), alternate=False)

    assert len(opened) == 1
    assert not (tmp_path / "jira.txt").exists()


def test_remove_drops_the_selected_link_but_not_the_typed_one(tmp_path):
    launcher = jira(tmp_path, LIST)
    launcher.search("")

    assert not launcher.remove((0, 0))
    assert launcher.remove((0, 1))

    assert jira(tmp_path).search("") == [["Open PROJ (default project)", "PROJ-1 login fails"]]


@pytest.fixture
def opened(monkeypatch):
    urls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launchers, "open_in_new_window", lambda url, browser: urls.append((url, browser))
    )
    return urls


def people() -> SearchLauncher:
    return SearchLauncher("p", "People", "https://people.example.com/search?query={query}")


def test_web_search_offers_to_search_for_what_is_typed():
    launcher = people()

    assert launcher.name == "/p People"
    assert launcher.search("jane doe") == [['Search People for "jane doe"']]


def test_web_search_with_nothing_typed_says_what_to_type(opened):
    launcher = people()

    [[hint]] = launcher.search("  ")
    launcher.activate("  ", (0, 0), alternate=False)

    assert isinstance(hint, Muted)
    assert opened == []


def test_web_search_puts_the_query_into_the_url_encoded(opened):
    launcher = people()
    launcher.search("jane doe & co/x")

    launcher.activate("jane doe & co/x", (0, 0), alternate=False)

    assert opened == [("https://people.example.com/search?query=jane%20doe%20%26%20co%2Fx", "edge")]
    assert launcher.notice == 'Searched People for "jane doe & co/x" in Edge'


def test_web_search_alternate_uses_the_other_browser(opened):
    launcher = people()
    launcher.search("x")

    launcher.activate("x", (0, 0), alternate=True)

    assert opened[0][1] == "chrome"
