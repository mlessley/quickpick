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


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    return Config.model_validate_json(path.read_text())
