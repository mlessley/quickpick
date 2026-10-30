"""The `/j` list: Jira links opened before, newest first, below any pinned ones. Kept in a
`title ~!~ url` file, editable in Notepad, where a leading `!` pins a line."""

from dataclasses import dataclass

from quickpick.store import SEPARATOR

PIN = "!"
# Unpinned links kept; older ones drop off. Pinned ones always stay
RECENT_LIMIT = 50


@dataclass(frozen=True)
class JiraLink:
    title: str
    url: str
    pinned: bool = False


def parse_jira_list(text: str) -> list[JiraLink]:
    """The links in a list file, pinned ones first, each group in file order."""
    links = []
    for line in text.splitlines():
        title, _, url = line.partition(SEPARATOR)
        title, url = title.strip(), url.strip()
        if not url:
            continue
        pinned = title.startswith(PIN)
        if pinned:
            title = title.removeprefix(PIN).strip()
        links.append(JiraLink(title or url, url, pinned))
    return _pins_first(links)


def format_jira_list(links: list[JiraLink]) -> str:
    return "".join(
        f"{PIN + ' ' if link.pinned else ''}{link.title} {SEPARATOR} {link.url}\n" for link in links
    )


def remember(
    links: list[JiraLink], url: str, title: str | None, fallback: str, limit: int = RECENT_LIMIT
) -> list[JiraLink]:
    """links with url just opened: titled title if given, else as it was (or fallback if
    new). A pinned link stays where it is; any other goes to the top, below the pins."""
    existing = next((link for link in links if link.url == url), None)
    new_title = title or (existing.title if existing else fallback)
    if existing and existing.pinned:
        return [JiraLink(new_title, url, True) if link is existing else link for link in links]
    others = [link for link in links if link.url != url]
    pinned = [link for link in others if link.pinned]
    recent = [link for link in others if not link.pinned]
    return pinned + [JiraLink(new_title, url)] + recent[: max(limit - 1, 0)]


def forget(links: list[JiraLink], gone: JiraLink) -> list[JiraLink]:
    return [link for link in links if link != gone]


def filter_jira_links(links: list[JiraLink], query: str) -> list[JiraLink]:
    needle = query.strip().lower()
    return [link for link in links if needle in link.title.lower() or needle in link.url.lower()]


def _pins_first(links: list[JiraLink]) -> list[JiraLink]:
    return [link for link in links if link.pinned] + [link for link in links if not link.pinned]
