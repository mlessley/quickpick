"""The viewer's small markdown subset: inline code, bold, italic, web links, headings,
bullets and fenced code blocks. Everything is escaped and only these tags are made, so a
note can never inject HTML (see docs/adr/0005)."""

import re
from html import escape
from typing import Literal

FENCE = re.compile(r"\s*```")
HEADING = re.compile(r"(#{1,3}) (.*)")
BULLET = re.compile(r"(\s*)[-*] (.*)")
# Only web addresses: never javascript: or file:, and never a quote, which would end the
# browser's command-line argument
URL = r"https?://[^\s<>\"'`]+"
INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>(?!\s).+?(?<!\s))\*\*"
    r"|(?<![\w*])\*(?P<italic>(?![\s*]).+?(?<![\s*]))\*(?![\w*])"
    rf"|(?P<url>{URL})"
)
# Read as the sentence's punctuation rather than part of the address
URL_TRAILING = ".,;:!?'\""

Kind = Literal["text", "code"]


def split_code(lines: list[str]) -> list[tuple[Kind, range]]:
    """The runs of text and fenced code in lines, as line ranges; the ``` lines themselves
    are in neither. A fence left open runs to the end."""
    runs: list[tuple[Kind, range]] = []
    start = 0
    in_code = False
    for index, line in enumerate(lines):
        if FENCE.match(line):
            if in_code or index > start:
                runs.append(("code" if in_code else "text", range(start, index)))
            in_code = not in_code
            start = index + 1
    if in_code or start < len(lines):
        runs.append(("code" if in_code else "text", range(start, len(lines))))
    return runs


def format_line(line: str) -> str:
    """A line of text as HTML: a heading, a bullet, or plain, then inline formatting."""
    heading = HEADING.fullmatch(line)
    if heading:
        return f'<span class="h{len(heading[1])}">{inline(heading[2])}</span>'
    bullet = BULLET.fullmatch(line)
    if bullet:
        return f"{bullet[1]}• {inline(bullet[2])}"
    return inline(line)


def inline(text: str) -> str:
    """Escaped text with `code`, **bold**, *italic* and web addresses made into links."""
    parts: list[str] = []
    position = 0
    for match in INLINE.finditer(text):
        parts.append(escape(text[position : match.start()]))
        position = match.end()
        if match["code"] is not None:
            parts.append(f"<code>{escape(match['code'])}</code>")
        elif match["bold"] is not None:
            parts.append(f"<strong>{inline(match['bold'])}</strong>")
        elif match["italic"] is not None:
            parts.append(f"<em>{inline(match['italic'])}</em>")
        else:
            url, rest = _trim_url(match["url"])
            parts.append(_link(url) + escape(rest))
    parts.append(escape(text[position:]))
    return "".join(parts)


def first_url(text: str) -> str | None:
    """The first web address in text, without any punctuation trailing it."""
    match = re.search(URL, text)
    return _trim_url(match[0])[0] if match else None


def _trim_url(url: str) -> tuple[str, str]:
    """The address, and any trailing punctuation that belongs to the sentence instead."""
    end = len(url)
    while end > 0:
        last = url[end - 1]
        unbalanced = last == ")" and url[:end].count("(") < url[:end].count(")")
        if last not in URL_TRAILING and not unbalanced:
            break
        end -= 1
    return url[:end], url[end:]


def _link(url: str) -> str:
    return f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(url)}</a>'
