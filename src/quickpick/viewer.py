"""The viewer: a local web page rendering the full digest across all days."""

import hmac
import mimetypes
import re
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import date, timedelta
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from pydantic import ValidationError

from quickpick.app_switch import Window, bring_to_front, is_app_window, list_windows
from quickpick.browser import open_in_new_window
from quickpick.config import CONFIG_PATH, DATA_DIR, Config, load_config
from quickpick.digest import (
    KIND_MARKS,
    LABEL,
    DigestEntry,
    entry_id,
    list_days,
    open_todos,
    read_day,
)
from quickpick.hotkey import parse_hotkey
from quickpick.screenshot import press_hotkey
from quickpick.theme import Theme
from quickpick.windows import foreground_window

# Screenshots are addressed by day and position in that day's log, never by file path
# Also how a browser window showing the viewer is recognised, from its title
PAGE_TITLE = "Quickpick digest"
VIEWER_BROWSERS = {"msedge.exe", "chrome.exe"}
RELOAD_KEY = parse_hotkey("f5", require_modifier=False)

ENTRY_ROUTE = re.compile(r"/(image|edit)/(\d{4}-\d{2}-\d{2})/(\d+)")

# The page's default window in calendar days, and how far each "more days" link extends it
WINDOW_DAYS = 30

PAGE_STYLE = """
:root { color-scheme: light;
        --bg: #fafafa; --fg: #1d1d1f; --muted: #6e6e73; --rule: #d2d2d7; --accent: #0067c0;
        --label: #1a7f37; }
:root[data-theme="dark"] { color-scheme: dark;
        --bg: #161618; --fg: #ececf0; --muted: #9a9aa2; --rule: #3a3a40; --accent: #4ea1ff;
        --label: #5fd38d; }
body { margin: 0 auto; max-width: 960px; padding: 16px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 system-ui, sans-serif; }
.bar { margin: 0 0 8px; color: var(--muted); }
h2 { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: 12px;
     margin: 16px 0 4px; padding: 4px 0; background: var(--bg); color: var(--muted);
     font-size: 13px; font-weight: 600; }
h2::before, h2::after { content: ""; flex: 1; border-top: 1px solid var(--rule); }
h2::before { flex: 0 0 24px; }
h2, .entry { scroll-margin-top: 40px; }
.entry { display: flex; gap: 12px; padding: 6px 0; }
.time { flex: none; width: 3.5em; color: var(--muted); font-variant-numeric: tabular-nums; }
.body { min-width: 0; flex: 1; }
.body > span { white-space: pre-wrap; }
.context { color: var(--muted); }
a { color: var(--accent); }
a.tag { color: var(--accent); text-decoration: none; }
a.tag:hover { text-decoration: underline; }
a.label { color: var(--label); font-weight: 600; text-decoration: none; }
a.label:hover { text-decoration: underline; }
img { display: block; max-width: 100%; margin: 6px 0; border: 1px solid var(--rule); }
form { margin: 0; }
"""

# Opens at the newest entry (or the one in the URL's fragment) and holds it in view while
# lazy images around it load, until the reader scrolls or types
PAGE_SCRIPT = """
const target = (location.hash && document.getElementById(location.hash.slice(1)))
  || document.getElementById("end");
const block = target.id === "end" ? "end" : "start";
let held = true;
const hold = () => { if (held) target.scrollIntoView({ block }); };
for (const event of ["wheel", "keydown", "mousedown", "touchstart"]) {
  addEventListener(event, () => { held = false; }, { once: true, passive: true });
}
for (const img of document.images) img.addEventListener("load", hold);
hold();
"""


def days_in_window(days: list[date], today: date, span: int | None) -> list[date]:
    """The days within the last span calendar days up to today; all of them when span is None."""
    if span is None:
        return days
    since = today - timedelta(days=span - 1)
    return [day for day in days if day >= since]


def parse_span(query: str) -> int | None:
    """The window from days=N in a query string or form body; None for days=all."""
    value = parse_qs(query).get("days", [""])[0]
    if value == "all":
        return None
    if value.isdigit() and int(value) > 0:
        return int(value)
    return WINDOW_DAYS


def _span_param(span: int | None) -> str:
    return "all" if span is None else str(span)


def _render_bar(
    span: int | None, today: date, first_day: date | None, first_shown: date | None
) -> str:
    if first_day is None:
        return '<p class="bar">No digest entries yet.</p>'
    since = None if span is None else today - timedelta(days=span - 1)
    if since is None or first_day >= since:
        return f'<p class="bar">Start of digest (first entry {first_day.isoformat()})</p>'
    # Lands back on the oldest day already loaded, so the reader keeps their place
    anchor = f"#d-{first_shown.isoformat()}" if first_shown else ""
    return (
        f'<p class="bar">Showing the last {span} days (since {since.isoformat()}) · '
        f'<a href="/?days={span + WINDOW_DAYS}{anchor}">▲ {WINDOW_DAYS} more days</a> · '
        f'<a href="/?days=all{anchor}">Show everything</a></p>'
    )


def _render_tags(entry: DigestEntry) -> str:
    """Each tag as a link to everything with that tag."""
    return "".join(
        f'<a class="tag" href="/?{escape(urlencode({"days": "all", "tag": tag}))}">'
        f"#{escape(tag)}</a> "
        for tag in entry.tags
    )


def _render_text(entry: DigestEntry) -> str:
    """The entry's text, each labelled line's label (`idea: `) a link to everything with
    that label."""
    if not entry.labels:
        return escape(entry.text)
    first, *more = entry.text.split("\n")
    # Only a note's later lines carry labels; a todo's are plain text
    later = [_render_line(line) if entry.kind == "note" else escape(line) for line in more]
    return "\n".join([_render_line(first), *later])


def _render_line(line: str) -> str:
    match = LABEL.match(line)
    if match is None:
        return escape(line)
    word, rest = line.split(":", 1)
    query = escape(urlencode({"days": "all", "label": match[1].lower()}))
    return f'<a class="label" href="/?{query}">{escape(word)}:</a>{escape(rest)}'


def _render_entry(
    day: date,
    index: int,
    entry: DigestEntry,
    token: str,
    days: str,
    open_todo_ids: set[str] | None,
) -> str:
    time = f'<span class="time">{entry.time:%H:%M}</span>'
    tags = _render_tags(entry)
    if entry.kind != "screenshot":
        mark = KIND_MARKS.get(entry.kind, "")
        if entry.kind == "todo" and open_todo_ids is not None:
            mark = "☐ " if entry_id(day, index) in open_todo_ids else "☑ "
        # Done and timer entries are bookkeeping, so they're shown quieter than notes
        quiet = ' class="context"' if entry.kind in ("done", "timer") else ""
        text = f"<span{quiet}>{mark}{_render_text(entry)}</span>"
        return f'<div class="entry">{time}<div class="body">{tags}{text}</div></div>'
    context = f'<div class="context">{tags}Screenshot: {escape(entry.text)}</div>'
    if not entry.path:
        return (
            f'<div class="entry">{time}<div class="body">{context}'
            '<div class="context">(no image)</div></div></div>'
        )
    address = entry_id(day, index)
    return (
        f'<div class="entry" id="e-{day.isoformat()}-{index}">{time}<div class="body">{context}'
        f'<img src="/image/{address}" alt="{escape(entry.text)}" loading="lazy">'
        f'<form method="post" action="/edit/{address}">'
        f'<input type="hidden" name="token" value="{escape(token)}">'
        f'<input type="hidden" name="days" value="{days}">'
        "<button>Edit in GreenShot</button></form></div></div>"
    )


def render_page(
    days: list[tuple[date, list[DigestEntry]]],
    token: str,
    *,
    span: int | None,
    today: date,
    first_day: date | None,
    theme: Theme = "dark",
    tag: str | None = None,
    label: str | None = None,
    open_todo_ids: set[str] | None = None,
) -> str:
    """The digest as a log: the window's days in the order given, entries in log order.

    first_day is the digest's oldest day, which decides whether earlier days can be loaded.
    tag / label keep only the entries with that tag / label. open_todo_ids marks which
    todos are still open; without it every todo shows as open.
    """
    sections = []
    for day, entries in days:
        rendered = "".join(
            _render_entry(day, index, entry, token, _span_param(span), open_todo_ids)
            for index, entry in enumerate(entries)
            if (tag is None or tag in entry.tags) and (label is None or label in entry.labels)
        )
        if rendered:
            heading = f'<h2 id="d-{day.isoformat()}">{day:%A} {day.isoformat()}</h2>'
            sections.append(heading + rendered)
    body = "".join(sections)
    if tag is not None or label is not None:
        what = f"tagged #{escape(tag)}" if tag is not None else f"labelled {escape(label)}:"
        bar = f'<p class="bar">Everything {what} · <a href="/">Back to the log</a></p>'
        body = body or "<p>Nothing matches.</p>"
    else:
        bar = _render_bar(span, today, first_day, days[0][0] if days else None)
        if not body and first_day is not None:
            body = f"<p>No entries in the last {span} days.</p>"
    return (
        f'<!doctype html><html lang="en" data-theme="{theme}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{PAGE_TITLE}</title><style>{PAGE_STYLE}</style></head>"
        f'<body>{bar}{body}<div id="end"></div><script>{PAGE_SCRIPT}</script></body></html>'
    )


def find_screenshot(digest_dir: Path, day: str, index: str) -> Path | None:
    """The image of the screenshot entry at day/index, if there is one."""
    try:
        entries = read_day(digest_dir, date.fromisoformat(day))
    except ValueError:
        return None
    position = int(index)
    if position >= len(entries):
        return None
    entry = entries[position]
    if entry.kind != "screenshot" or not entry.path:
        return None
    return Path(entry.path)


def make_handler(
    digest_dir: Path,
    token: str,
    open_in_editor: Callable[[Path], None],
    theme: Theme = "dark",
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/":
                span, today = parse_span(url.query), date.today()
                params = parse_qs(url.query)
                tag = params.get("tag", [None])[0]
                label = params.get("label", [None])[0]
                if tag is not None or label is not None:
                    # Their entries can be from any day, e.g. weeks ago
                    span = None
                all_days = list_days(digest_dir)
                days = [
                    (day, read_day(digest_dir, day))
                    for day in days_in_window(all_days, today, span)
                ]
                first_day = all_days[0] if all_days else None
                page = render_page(
                    days,
                    token,
                    span=span,
                    today=today,
                    first_day=first_day,
                    theme=theme,
                    tag=tag,
                    label=label,
                    open_todo_ids={todo_id for todo_id, _todo in open_todos(digest_dir)},
                )
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", page.encode())
                return
            match = ENTRY_ROUTE.fullmatch(url.path)
            image = None
            if match and match[1] == "image":
                image = find_screenshot(digest_dir, match[2], match[3])
            if image is None or not image.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
            self._send(HTTPStatus.OK, content_type, image.read_bytes())

        def do_POST(self) -> None:
            match = ENTRY_ROUTE.fullmatch(self.path)
            if not match or match[1] != "edit":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            form = parse_qs(body)
            # Stops other sites in the browser from triggering the editor via this port
            if not hmac.compare_digest(form.get("token", [""])[0], token):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            image = find_screenshot(digest_dir, match[2], match[3])
            if image is None or not image.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            open_in_editor(image)
            self.send_response(HTTPStatus.SEE_OTHER)
            # Returns to the same screenshot with the same days loaded
            days = _span_param(parse_span(body))
            self.send_header("Location", f"/?days={days}#e-{match[2]}-{match[3]}")
            self.end_headers()

        def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


class ViewerServer(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR would let a second viewer bind the same port without error
    allow_reuse_address = False


def viewer_url(config: Config) -> str:
    return f"http://127.0.0.1:{config.viewer_port}/"


def make_server(config: Config, digest_dir: Path) -> ViewerServer:
    """The viewer's server on its configured port; raises OSError if the port is taken."""

    def open_in_greenshot(image: Path) -> None:
        subprocess.Popen([str(config.greenshot_exe), str(image)])

    token = secrets.token_urlsafe(16)
    handler = make_handler(digest_dir, token, open_in_greenshot, config.theme)
    return ViewerServer(("127.0.0.1", config.viewer_port), handler)


def find_viewer_window(windows: list[Window]) -> Window | None:
    """The most recently used browser window showing the viewer. A browser window's title
    is its active tab's, so a viewer in a background tab isn't found."""
    for window in windows:
        if (
            is_app_window(window)
            and window.program.lower() in VIEWER_BROWSERS
            and PAGE_TITLE in window.title
        ):
            return window
    return None


def reload_open_viewer() -> bool:
    """Bring a viewer already open in a browser forward and reload it (F5, as it is, filters
    and all). False when none is open. F5 is only pressed if the window really took the
    focus, so the key never lands anywhere else."""
    window = find_viewer_window(list_windows())
    if window is None:
        return False
    bring_to_front(window)
    if foreground_window() == window.hwnd:
        press_hotkey(RELOAD_KEY)
    return True


class BackgroundViewer:
    """The viewer hosted inside the popup's process, started the first time it's opened."""

    def __init__(
        self,
        config: Config,
        digest_dir: Path,
        open_url: Callable[[str], None] | None = None,
        reuse_open: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
        self.digest_dir = digest_dir
        self.open_url = open_url or (lambda url: open_in_new_window(url, config.browser))
        # Brings forward and reloads a viewer already open in a browser; False if none is
        self.reuse_open = reuse_open or reload_open_viewer
        self.server: ViewerServer | None = None

    def open(self) -> None:
        if self.server is None:
            try:
                self.server = make_server(self.config, self.digest_dir)
            except OSError:
                # Most likely a standalone quickpick-viewer already serving the page
                pass
            else:
                threading.Thread(target=self.server.serve_forever, daemon=True).start()
        if not self.reuse_open():
            self.open_url(viewer_url(self.config))

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def main() -> None:
    try:
        config = load_config(CONFIG_PATH)
    except ValidationError as error:
        sys.exit(f"Invalid config {CONFIG_PATH}:\n{error}")

    try:
        server = make_server(config, DATA_DIR / "digest")
    except OSError as error:
        sys.exit(f"Could not start the viewer on port {config.viewer_port}: {error}")

    url = viewer_url(config)
    print(f"quickpick viewer at {url}; Ctrl+C to stop")
    open_in_new_window(url, config.browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
