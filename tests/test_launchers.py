import pytest

from quickpick.launchers import PrefixMenu, StoreLauncher, jira_target, route, strip_colon_form


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


def test_store_launcher_searches_after_its_prefix(repos):
    assert repos.search("g:quick") == [["quickpick  (https://github.com/mlessley/quickpick)"]]


def test_route_picks_the_launcher_for_a_known_prefix_or_the_menu_for_a_colon(repos):
    menu = PrefixMenu([repos])

    assert route("g:quick", [repos], menu, accepts_prefixes=True) is repos
    assert route(":", [repos], menu, accepts_prefixes=True) is menu
    assert route("a:b", [repos], menu, accepts_prefixes=True) is None
    assert route("quick", [repos], menu, accepts_prefixes=True) is None
    assert route("g:quick", [repos], menu, accepts_prefixes=False) is None


def test_the_colon_form_reaches_a_launcher_in_every_mode_including_notes(repos):
    menu = PrefixMenu([repos])

    for accepts_prefixes in (True, False):
        assert route(":g:quick", [repos], menu, accepts_prefixes) is repos
        assert route(":", [repos], menu, accepts_prefixes) is menu
        assert route(":re", [repos], menu, accepts_prefixes) is menu


def test_a_launcher_gets_its_query_without_the_leading_colon():
    assert strip_colon_form(":g:quick") == "g:quick"
    assert strip_colon_form("g:quick") == "g:quick"
    assert strip_colon_form(":) great meeting") == ":) great meeting"


def test_prefix_menu_lists_prefixes_and_fills_in_the_chosen_one(repos):
    menu = PrefixMenu([repos])

    assert menu.search(":") == [["g: Repo shortcuts"]]
    assert menu.search(":repo") == [["g: Repo shortcuts"]]
    assert menu.search(":zzz") == [[]]
    menu.search(":")
    assert menu.activate(":", (0, 0), alternate=False) == ":g:"


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


def test_a_colon_line_the_menu_cannot_match_goes_back_to_the_mode(repos):
    # e.g. ":x note" in notes: the notes list stays in view instead of an empty menu
    menu = PrefixMenu([repos])

    for accepts_prefixes in (True, False):
        assert route(":x note", [repos], menu, accepts_prefixes) is None
        assert route(":) great meeting", [repos], menu, accepts_prefixes) is None
        assert route(":x:unknown", [repos], menu, accepts_prefixes) is None
        assert route(":rep", [repos], menu, accepts_prefixes) is menu
