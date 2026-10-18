# quickpick

[![CI](https://github.com/mlessley/quickpick/actions/workflows/ci.yml/badge.svg)](https://github.com/mlessley/quickpick/actions/workflows/ci.yml)

A personal Windows productivity tool: a hotkey-summoned popup for quickly copying saved strings, launching Edge bookmarks/history, and capturing notes and screenshots into a chronological digest.

![The popup in notes mode: open todos above today's notes, a tag switched on, and a label being typed](docs/images/notes.png)

## Why this exists

I wanted one keystroke for the small things I do all day (paste a saved string, open a link, jot down who said what in a meeting) without leaving the keyboard or adopting another app. The constraints shaped it more than the features did:

- **A managed Windows laptop.** No admin rights, and nothing that watches the keyboard: global hotkeys go through `RegisterHotKey`, which only sees its own key combinations ([ADR-0001](./docs/adr/0001-registerhotkey-not-keyboard-hooking.md)).
- **Keyboard first.** One summon hotkey, modes cycled inside the popup ([ADR-0003](./docs/adr/0003-single-summon-hotkey-with-in-app-mode-cycling.md)).
- **Plain files I own.** Notes are an append-only JSON Lines file per day; nothing is edited in place, nothing goes to a cloud service.
- **Use what's already installed.** Edge's own bookmarks and history, GreenShot for screenshots, Outlook and Teams as they are.

It's built in Python with Tk and pywin32. [CONTEXT.md](./CONTEXT.md) is the glossary of its terms and [docs/adr](./docs/adr) records the key design decisions. It was built with [Claude Code](https://claude.com/claude-code), working from a glossary, specs and tickets, test first.

## Running

Requires Windows and [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run quickpick
```

Quickpick stays running in that console. At startup the popup opens centred on the screen with the mouse, on a splash showing today's digest so far and every hotkey (generated from your config). Typing, or any popup key, goes straight on from the splash; **Ctrl+H** brings it back at any time. Press **Ctrl+Alt+Space** from any window to open the popup and again to close it; **Ctrl+C** in the console, or **Ctrl+Q** twice in the popup, quits.

**Without a console:** `uv run quickpick-shortcuts` adds Quickpick to the Start menu and starts it whenever you sign in to Windows (`uv run quickpick-shortcuts --remove` takes both away). The shortcuts run `uvw run --project <this folder> quickpick-gui`, so Quickpick runs from this checkout with no console window, and uv keeps its packages in sync on each start. Quit it with **Ctrl+Q** twice in the popup. Anything that stops it starting (a bad `config.json`, a hotkey that's already taken, e.g. by a copy already running) is shown in a message box, and its output goes to `~/.quickpick-data/quickpick.log`.

The popup has modes; **Ctrl+Tab** / **Ctrl+Shift+Tab** switch between them, and the popup reopens in whichever mode you used last. Drag the bar along the top (the mode names) to move the popup; it reopens where you left it until Quickpick restarts.

- **Quick copy**: **Enter** or double-click copies the selected value. **F2** opens the quick-copy store in Notepad; changes show up the next time the popup opens.
- **Edge**: lists your Edge bookmarks and, below them, your most recent history (up to 100 matches), both filtered by the same query. **Tab** / **Shift+Tab** move the selection between the two lists; **Enter** or double-click opens the selected item in a new browser window.
- **Notes**: type a note and press **Enter** to add it to today's digest; the popup stays open and the list below shows today's notes, newest at the bottom, under the last earlier day with entries (greyed) for context. **PageUp/PageDown** scroll it. **F2** opens the full digest in the [viewer](#viewer), starting it inside Quickpick if it isn't already running. If the viewer is already open (as the active tab of an Edge or Chrome window), that window is brought forward and reloaded instead of opening another. **Ctrl+N** from any other mode jumps to Notes; pressed in Notes, it opens the viewer like F2 (so Ctrl+N twice opens the viewer from anywhere).
  - **Todos**: a note starting with `[]` (e.g. `[] call Jane`) is a todo. Open todos, from any day, are listed above the notes until ticked off: **Up/Down** select one, **Ctrl+D** ticks it off. The splash shows how many are open.
  - **Tags**: type `#xyz-mtg` alone and press **Enter** to switch that tag on (inventing it if it's new); the same again switches it off. Typing `#` lists your recent tags. Active tags show at the top right (click one to switch it off) and label every note, todo, screenshot and timer entry until the popup closes, so pin it (below) to keep a meeting's tag on. In the viewer, click a tag to see everything with it.
  - **Labels**: start a note or todo with a word, a colon and a space, e.g. `bob: it'll be done tomorrow`, `js: agreed` or `url: https://…`, to label just that line. In the viewer the label is a link to every entry with it, from any day. Older notes written this way are labelled too. While you type one, a badge at the right of the query box shows it in green if you've used it before, or in amber as a new label, with the label it's probably a typo of (e.g. `new label: bobb · bob?`).

### Screenshots

**Ctrl+Alt+S** (works whether or not the popup is open) takes a screenshot through [GreenShot](https://getgreenshot.org/): Quickpick closes the popup, triggers GreenShot's region capture, and adds a `[screenshot]` entry to today's digest with the title of the window you were in and the saved image. Set GreenShot's destination to save directly to a file (Preferences, Destination: untick "Select destination dynamically", tick "Save directly"); Quickpick reads GreenShot's capture hotkey and save folder from its own settings.

**Prefixes** start the query with a launcher instead of the current mode. In every mode, put a **`:`** in front (`:g:home`); in Quick copy and Edge the plain form (`g:home`) works too, while in Notes a line without the leading `:` is always a note (so `g: …` is a labelled note). For example, **`g:home`** searches your repo shortcuts (the launcher store; **F2** edits it), and **`j:`** opens Jira: `j:123` is issue 123 in your default project, `j:ABC-42` that issue, `j:some words` a Jira text search, and a bare `j:` the default project. Type **`:`** to list the available prefixes; **Enter** on one fills it in (`:g:`). In Notes, a line starting with a colon that matches no prefix, like `:) great meeting`, is saved as a note. Unknown plain prefixes are searched as plain text.

Wherever Quickpick opens a URL, **Enter** uses your default browser (Edge unless configured) and **Ctrl+Enter** uses the other one (Chrome / Edge).

In quick copy and Edge: type to filter, **Up/Down** to move. **Esc** closes the popup in every mode.

**Focus timer:** **`:t:25 write spec`** (or `t:25 write spec` outside Notes) starts a 25-minute timer (one at a time); a bare **`:t:`** shows it, and **Enter** cancels it. The time left shows at the top right; when it runs out, a notice pops up in the bottom-right corner with a sound. Starting, finishing and cancelling are logged to the digest.

**Pin:** **Ctrl+P** (or the 📌 at the top right) keeps the popup open: copying, opening links, switching apps and the viewer no longer close it, the summon hotkey only brings it forward, and after a screenshot it comes back. Only **Esc** closes it. Unpinned or not, the summon hotkey brings an open popup forward when another window has focus, and closes it only when it already has focus.

**App switching:** in any mode, **Ctrl+O** brings Outlook to the front and **Ctrl+T** Teams (restoring them if minimized) and hides the popup. It switches to the app's most recently used window and never starts the app: if it has no open window (not running, or closed to the tray), the popup says so. Add more apps or change the keys with `apps` in `config.json`.

### Viewer

```
uv run quickpick-viewer
```

Opens the digest in your browser as a log: notes and screenshots in time order, oldest at the top, opening scrolled to the newest at the bottom. It's served locally at `http://127.0.0.1:8765/`. It shows the last 30 days; the bar at the top loads 30 more days at a time, or everything (load everything before searching all of history with Ctrl+F). Reload the page to see new entries. **Edit in GreenShot** under a screenshot opens it in GreenShot's editor. **Ctrl+C** in the console stops the viewer; it runs independently of the popup. You rarely need to start it this way: **F2** in notes mode starts the same viewer inside Quickpick on first use (it stops when Quickpick quits), or just opens the page if a standalone viewer is already running.

Data lives in `~/.quickpick-data/`:

- `quick-copy.txt`: one `key~!~value` entry per line; prefix the key with `*` to hide its value in the list. Pass a different path as the first argument to use another store.
- `launcher.txt`: the `g:` launcher store, one `key~!~url` entry per line (e.g. `quickpick~!~https://github.com/mlessley/quickpick`).
- `digest/YYYY-MM-DD.jsonl`: one file per day of notes and screenshots, one JSON entry per line. Screenshot entries store the image's full path, so if you move images, update those paths too.
- `screenshots/`: a suggested home for GreenShot's captures. Set it as GreenShot's storage location (Preferences, Output); Quickpick follows whatever folder GreenShot uses.
- `config.json` (optional):
  - `summon_hotkey`: e.g. `"ctrl+shift+q"`. Modifiers are `ctrl`, `alt`, `shift`, `win`. Default `"ctrl+alt+space"`.
  - `screenshot_hotkey`: default `"ctrl+alt+s"`.
  - `greenshot_hotkey` / `screenshot_dir`: override the capture hotkey and save folder otherwise read from GreenShot's settings.
  - `browser`: `"edge"` (default) or `"chrome"`; the browser Enter opens URLs in. Ctrl+Enter uses the other.
  - `theme`: `"dark"` (default) or `"light"`, for both the popup and the viewer.
  - `jira_base_url` / `jira_default_project`: your Jira site (e.g. `"https://yourco.atlassian.net"`) and the project `j:123` resolves against. The built-in defaults are placeholders.
  - `greenshot_exe`: GreenShot's executable, used by the viewer's Edit button. Default: the per-user install under `%LOCALAPPDATA%\Programs\Greenshot`.
  - `viewer_port`: default `8765`.
  - `edge_profile`: the Edge profile folder whose bookmarks and history to list, e.g. `"Profile 1"`. Default `"Default"`.
  - `apps`: the popup's app-switch keys, each `{"key": ..., "name": ..., "program": ..., "title": ...}`. `program` is the executable's file name (any case); the optional `title` keeps only windows whose title contains it. Keys are Ctrl and/or Alt plus a letter or digit, or an F-key; the popup's own keys (Ctrl+N, Ctrl+A/C/V/X/Z, F2) are refused. A list here replaces the default, which is:
    ```json
    "apps": [
      {"key": "ctrl+o", "name": "Outlook", "program": "OUTLOOK.EXE"},
      {"key": "ctrl+t", "name": "Teams", "program": "ms-teams.exe"}
    ]
    ```

## License

[MIT](./LICENSE)
