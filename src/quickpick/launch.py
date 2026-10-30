"""Running Quickpick without a console: the `quickpick-gui` entry point, and the
`quickpick-shortcuts` command that adds it to the Start menu and to sign-in."""

import ctypes
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from quickpick.config import DATA_DIR
from quickpick.icon import ICON_PATH

LOG_PATH = DATA_DIR / "quickpick.log"
# Started afresh past this size, so the log never grows without bound
LOG_MAX_BYTES = 1_000_000
MB_ICONERROR = 0x10
MB_TOPMOST = 0x40000
SHORTCUT_NAME = "Quickpick.lnk"
# Set for a restarted Quickpick: the process id of the one it replaces, to wait out
WAIT_FOR_ENV = "QUICKPICK_WAIT_FOR"
WAIT_FOR_MS = 15_000
SYNCHRONIZE = 0x100000
CREATE_NEW_CONSOLE = 0x10
CREATE_NO_WINDOW = 0x08000000


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, "Quickpick", MB_ICONERROR | MB_TOPMOST)


def has_visible_console() -> bool:
    """True when Quickpick was started in a console window someone can see."""
    console = ctypes.windll.kernel32.GetConsoleWindow()
    return bool(console) and bool(ctypes.windll.user32.IsWindowVisible(console))


def relaunch(pid: int) -> None:
    """Start Quickpick again the way this one was started (Ctrl+R), told to wait until
    process pid has exited, so its hotkeys and the viewer's port are free. Started from a
    console, the new one gets a console of its own, since it can't take over this one's;
    otherwise it gets none, as when started from the Start menu."""
    env = os.environ | {WAIT_FOR_ENV: str(pid)}
    # The venv's own python, not orig_argv[0]: that's the base interpreter a venv's
    # python hands over to, which doesn't have the venv's packages. python.exe rather
    # than pythonw.exe, which hands over to a console python that would show a window
    python = str(Path(sys.executable).with_name("python.exe"))
    flags = CREATE_NEW_CONSOLE if has_visible_console() else CREATE_NO_WINDOW
    subprocess.Popen([python, *sys.orig_argv[1:]], env=env, creationflags=flags)


def wait_for_previous() -> None:
    """In a restarted Quickpick, wait for the one it replaces to finish exiting."""
    pid = os.environ.pop(WAIT_FOR_ENV, None)
    if not pid:
        return
    import pywintypes
    import win32api
    import win32event

    try:
        process = win32api.OpenProcess(SYNCHRONIZE, False, int(pid))
    except (pywintypes.error, ValueError):
        return  # already gone
    try:
        win32event.WaitForSingleObject(process, WAIT_FOR_MS)
    finally:
        process.Close()


def gui_main() -> None:
    """Quickpick with no console: output goes to the log, and anything that stops it from
    starting (or crashes it) is shown in a message box, since nobody sees the output."""
    from quickpick import app

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    too_big = LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES
    log = LOG_PATH.open("w" if too_big else "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    try:
        app.main()
    except SystemExit as stop:
        # main() exits with a message when it can't start (bad config, hotkey taken)
        if isinstance(stop.code, str):
            print(stop.code)
            show_error(stop.code)
        raise
    except Exception:
        traceback.print_exc()
        show_error(f"Quickpick stopped unexpectedly. Details are in {LOG_PATH}")
        sys.exit(1)


def shortcut_command(repo: Path, uvw: Path) -> tuple[Path, str, Path]:
    """(target, arguments, working folder) for a shortcut that starts Quickpick with no
    console, running this checkout through uv so its environment is kept in sync."""
    return uvw, f'run --project "{repo}" quickpick-gui', repo


def shortcut_folders() -> list[Path]:
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return [programs, programs / "Startup"]


def install_shortcuts() -> None:
    """`quickpick-shortcuts`: add Quickpick to the Start menu and start it at sign-in;
    `quickpick-shortcuts --remove` takes both away again."""
    import win32com.client

    folders = shortcut_folders()
    if "--remove" in sys.argv[1:]:
        for folder in folders:
            (folder / SHORTCUT_NAME).unlink(missing_ok=True)
        print("Removed the Start menu and sign-in shortcuts.")
        return
    uvw = shutil.which("uvw")
    if uvw is None:
        sys.exit("uvw (installed with uv) isn't on PATH, so there's nothing to point at.")
    # The checkout this package is installed from (src/quickpick/launch.py -> repo root)
    repo = Path(__file__).resolve().parents[2]
    target, arguments, working_dir = shortcut_command(repo, Path(uvw))
    shell = win32com.client.Dispatch("WScript.Shell")
    for folder in folders:
        shortcut = shell.CreateShortcut(str(folder / SHORTCUT_NAME))
        shortcut.TargetPath = str(target)
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = str(working_dir)
        shortcut.Description = "Quickpick"
        shortcut.IconLocation = f"{ICON_PATH},0"
        shortcut.Save()
        print(f"Created {folder / SHORTCUT_NAME}")
