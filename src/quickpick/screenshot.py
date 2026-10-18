import configparser
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import win32api

from quickpick.hotkey import MODIFIERS, Hotkey

KEYEVENTF_KEYUP = 0x2
# Virtual-key codes for each RegisterHotKey modifier flag
MODIFIER_VKS = {
    MODIFIERS["alt"]: 0x12,
    MODIFIERS["ctrl"]: 0x11,
    MODIFIERS["shift"]: 0x10,
    MODIFIERS["win"]: 0x5B,
}
HELD_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


@dataclass(frozen=True)
class GreenshotSettings:
    region_hotkey: str | None
    output_dir: Path | None


def parse_greenshot_ini(text: str) -> GreenshotSettings:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(text.removeprefix(chr(0xFEFF)))
    core = parser["Core"] if parser.has_section("Core") else {}
    output_dir = core.get("OutputFilePath")
    return GreenshotSettings(
        region_hotkey=core.get("RegionHotkey") or None,
        output_dir=Path(output_dir) if output_dir else None,
    )


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
# Characters Windows doesn't allow in file names; GreenShot replaces them with "_" too
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_TITLE_CHARS = 80


def list_files(folder: Path) -> set[str]:
    try:
        return {entry.name for entry in folder.iterdir()}
    except OSError:
        return set()


def find_new_image(folder: Path, before: set[str]) -> Path | None:
    """The newest image in folder whose name wasn't in the before snapshot, if any."""
    new_images = [
        folder / name
        for name in list_files(folder) - before
        if Path(name).suffix.lower() in IMAGE_SUFFIXES
    ]
    if not new_images:
        return None
    return max(new_images, key=lambda path: path.stat().st_mtime)


def capture_name(started: datetime, context: str, suffix: str) -> str:
    """The file name for a capture: its time and capture context, e.g.
    "2026-10-18 12_02_38-Untitled - Paint.png", made safe for Windows."""
    title = UNSAFE_FILENAME_CHARS.sub("_", context)[:MAX_TITLE_CHARS].strip().rstrip(".")
    stamp = f"{started:%Y-%m-%d %H_%M_%S}"
    return f"{stamp}-{title}{suffix}" if title else f"{stamp}{suffix}"


def rename_capture(image: Path, started: datetime, context: str) -> Path:
    """Rename GreenShot's file after the capture context, since GreenShot's own ${title}
    can name a different window (ADR 0002); the file as it was if it can't be renamed."""
    name = capture_name(started, context, image.suffix)
    if image.name == name:
        return image
    target = image.with_name(name)
    copy = 1
    while target.exists():
        copy += 1
        target = image.with_name(f"{Path(name).stem} ({copy}){image.suffix}")
    try:
        return image.rename(target)
    except OSError:
        return image


def read_greenshot_settings() -> GreenshotSettings:
    ini = Path(os.environ["APPDATA"]) / "Greenshot" / "Greenshot.ini"
    try:
        return parse_greenshot_ini(ini.read_text(encoding="utf-8"))
    except (OSError, configparser.Error):
        return GreenshotSettings(region_hotkey=None, output_dir=None)


def modifiers_held() -> bool:
    return any(win32api.GetAsyncKeyState(vk) & 0x8000 for vk in HELD_MODIFIER_VKS)


def press_hotkey(hotkey: Hotkey) -> None:
    """Simulate hotkey with keybd_event (ADR 0004), modifiers wrapped around the key."""
    modifier_vks = [vk for flag, vk in MODIFIER_VKS.items() if hotkey.modifiers & flag]
    for vk in modifier_vks:
        win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(hotkey.vk, 0, 0, 0)
    win32api.keybd_event(hotkey.vk, 0, KEYEVENTF_KEYUP, 0)
    for vk in reversed(modifier_vks):
        win32api.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
