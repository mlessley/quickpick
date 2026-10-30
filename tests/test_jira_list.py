from quickpick.jira_list import (
    JiraLink,
    filter_jira_links,
    forget,
    format_jira_list,
    parse_jira_list,
    remember,
)

BOARD = JiraLink("Sprint board", "https://jira.test/board", pinned=True)
ISSUE = JiraLink("PROJ-1 login fails", "https://jira.test/browse/PROJ-1")
OTHER = JiraLink("PROJ-2", "https://jira.test/browse/PROJ-2")


def test_parses_titles_urls_and_pins_listing_pins_first():
    text = (
        "PROJ-1 login fails ~!~ https://jira.test/browse/PROJ-1\n"
        "\n"
        "! Sprint board ~!~ https://jira.test/board\n"
        "PROJ-2~!~https://jira.test/browse/PROJ-2\n"
    )

    assert parse_jira_list(text) == [BOARD, ISSUE, OTHER]


def test_a_line_without_a_url_is_skipped():
    assert parse_jira_list("just a title\n ~!~ \n") == []


def test_formats_back_to_the_same_lines():
    assert parse_jira_list(format_jira_list([BOARD, ISSUE, OTHER])) == [BOARD, ISSUE, OTHER]
    assert format_jira_list([BOARD]) == "! Sprint board ~!~ https://jira.test/board\n"


def test_remember_puts_a_new_link_at_the_top_below_the_pins():
    links = remember([BOARD, ISSUE], "https://jira.test/browse/PROJ-2", None, "PROJ-2")

    assert links == [BOARD, OTHER, ISSUE]


def test_remember_moves_a_link_back_to_the_top_keeping_its_title():
    links = remember([BOARD, OTHER, ISSUE], ISSUE.url, None, "PROJ-1")

    assert links == [BOARD, ISSUE, OTHER]


def test_remember_with_a_title_renames_the_link():
    [link] = remember([ISSUE], ISSUE.url, "PROJ-1 SSO only", "PROJ-1")

    assert link.title == "PROJ-1 SSO only"


def test_remember_leaves_a_pin_where_it_is():
    links = remember([BOARD, ISSUE], BOARD.url, None, "board")

    assert links == [BOARD, ISSUE]


def test_remember_keeps_only_the_newest_unpinned_links():
    links = [BOARD] + [
        JiraLink(f"PROJ-{n}", f"https://jira.test/browse/PROJ-{n}") for n in range(3)
    ]

    links = remember(links, "https://jira.test/browse/PROJ-9", None, "PROJ-9", limit=2)

    assert [link.title for link in links] == ["Sprint board", "PROJ-9", "PROJ-0"]


def test_forget_removes_a_link_pinned_or_not():
    assert forget([BOARD, ISSUE, OTHER], ISSUE) == [BOARD, OTHER]
    assert forget([BOARD, ISSUE], BOARD) == [ISSUE]


def test_filter_matches_title_or_url_ignoring_case():
    assert filter_jira_links([BOARD, ISSUE, OTHER], "LOGIN") == [ISSUE]
    assert filter_jira_links([BOARD, ISSUE, OTHER], "proj-2") == [OTHER]
    assert filter_jira_links([BOARD, ISSUE], "") == [BOARD, ISSUE]
