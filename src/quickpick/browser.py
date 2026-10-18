import os
from typing import Literal

Browser = Literal["edge", "chrome"]

# Executable names Windows resolves through their registered App Paths
EXECUTABLES: dict[str, str] = {"edge": "msedge", "chrome": "chrome"}


def choose_browser(default: Browser, alternate: bool) -> Browser:
    """Enter opens in the default browser; Ctrl+Enter (alternate) in the other one."""
    if not alternate:
        return default
    return "chrome" if default == "edge" else "edge"


def open_in_new_window(url: str, browser: Browser) -> None:
    os.startfile(EXECUTABLES[browser], arguments=f'--new-window "{url}"')
