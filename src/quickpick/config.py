import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from quickpick.app_switch import RESERVED_APP_KEYS, normalize_app_key
from quickpick.browser import Browser
from quickpick.hotkey import parse_hotkey
from quickpick.theme import Theme

DATA_DIR = Path.home() / ".quickpick-data"
CONFIG_PATH = DATA_DIR / "config.json"


def _default_greenshot_exe() -> Path:
    # GreenShot's per-user install; it registers no App Paths entry to look it up by
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Greenshot" / "Greenshot.exe"


class AppShortcut(BaseModel):
    """A popup key that brings a running app's window to the front."""

    key: str
    name: str
    program: str  # executable file name, matched ignoring case
    title: str | None = None  # only windows whose title contains this

    @field_validator("key")
    @classmethod
    def _check_key(cls, spec: str) -> str:
        key = normalize_app_key(spec)
        if key in RESERVED_APP_KEYS:
            raise ValueError(f"app key {spec!r} is already used by the popup")
        return key


# Commands Quickpick defines itself: /g repo shortcuts, /j Jira, /t focus timer
BUILT_IN_COMMANDS = {"g", "j", "t"}
QUERY_SLOT = "{query}"


class WebSearch(BaseModel):
    """A `/command` that opens a web page searching for what's typed after it."""

    command: str
    name: str
    url: str  # a web address with {query} where the typed text goes

    @field_validator("command")
    @classmethod
    def _check_command(cls, command: str) -> str:
        command = command.lower()
        if not command or not all(char.isalnum() for char in command):
            raise ValueError(f"search command {command!r}: letters and digits only, no slash")
        if command in BUILT_IN_COMMANDS:
            raise ValueError(f"search command {command!r} is already used by Quickpick")
        return command

    @field_validator("url")
    @classmethod
    def _check_url(cls, url: str) -> str:
        if QUERY_SLOT not in url:
            raise ValueError(f"search url {url!r} needs {QUERY_SLOT} where the text goes")
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError(f"search url {url!r} must be a web address")
        return url


DEFAULT_APPS = [
    AppShortcut(key="ctrl+o", name="Outlook", program="OUTLOOK.EXE"),
    AppShortcut(key="ctrl+t", name="Teams", program="ms-teams.exe"),
]


class Config(BaseModel):
    summon_hotkey: str = "ctrl+alt+space"
    screenshot_hotkey: str = "ctrl+alt+s"
    # Default to GreenShot's own settings (its RegionHotkey and OutputFilePath)
    greenshot_hotkey: str | None = None
    screenshot_dir: Path | None = None
    edge_profile: str = "Default"
    browser: Browser = "edge"
    theme: Theme = "dark"
    # Placeholders; set the real values in your own ~/.quickpick-data/config.json
    jira_base_url: str = "https://your-company.atlassian.net"
    jira_default_project: str = "PROJ"
    greenshot_exe: Path = Field(default_factory=_default_greenshot_exe)
    viewer_port: int = 8765
    # Newest entries the stash's scratch list keeps; older ones drop off
    stash_scratch_limit: int = Field(default=100, ge=1)
    apps: list[AppShortcut] = Field(default_factory=lambda: list(DEFAULT_APPS))
    # Your own `/command`s searching a site, e.g. a people directory; none by default
    searches: list[WebSearch] = Field(default_factory=list)

    @field_validator("searches")
    @classmethod
    def _check_unique_search_commands(cls, searches: list[WebSearch]) -> list[WebSearch]:
        commands = [search.command for search in searches]
        duplicates = sorted({command for command in commands if commands.count(command) > 1})
        if duplicates:
            raise ValueError(f"more than one search uses /{', /'.join(duplicates)}")
        return searches

    @field_validator("apps")
    @classmethod
    def _check_unique_app_keys(cls, apps: list[AppShortcut]) -> list[AppShortcut]:
        keys = [app.key for app in apps]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"more than one app uses {', '.join(duplicates)}")
        return apps

    @field_validator("summon_hotkey", "screenshot_hotkey")
    @classmethod
    def _check_hotkey(cls, spec: str) -> str:
        parse_hotkey(spec)
        return spec

    @field_validator("greenshot_hotkey")
    @classmethod
    def _check_simulated_hotkey(cls, spec: str | None) -> str | None:
        if spec is not None:
            parse_hotkey(spec, require_modifier=False)
        return spec


# Written by Ctrl+, when there's no config yet: placeholders that show the shape
SAMPLE_CONFIG = """{
  "jira_base_url": "https://your-company.atlassian.net",
  "jira_default_project": "PROJ",
  "searches": [
    {"command": "w", "name": "Wiki", "url": "https://wiki.example.com/search?q={query}"},
    {"command": "d", "name": "Directory", "url": "https://directory.example.com/find?query={query}"},
    {"command": "m", "name": "Maps", "url": "https://maps.example.com/?search={query}"}
  ]
}
"""


def ensure_config(path: Path) -> None:
    """Create the config from SAMPLE_CONFIG if there isn't one yet, to edit by hand."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SAMPLE_CONFIG, encoding="utf-8")


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    return Config.model_validate_json(path.read_text())
