# Hand-rolled markdown subset in the viewer, no Mermaid

The viewer formats notes with a small markdown subset rendered in Python (inline code, fenced blocks, bold, italic, lists, headings, links), escaping everything first so a note can never produce HTML of its own. A markdown library (Python or JavaScript) and Mermaid were rejected to keep third-party code off a local page that can launch programs; Mermaid in particular needs a ~3 MB script or an online renderer. A `mermaid` block shows as a code block.

## Considered Options

- **marked.js + mermaid.js, vendored or from a CDN**: full markdown and diagrams, but megabytes of third-party script, raw HTML passing through by default, and (from a CDN) a network dependency.
- **`markdown-it-py`**: one pure-Python dependency, but it brings raw-HTML handling back and works on whole documents, which conflicts with per-line labels and continuations.
- **Optional user-supplied `mermaid.min.js`**: left open as a later addition; nothing ships in the repo.
