"""`python -m quickpick.gui`: Quickpick with no console, as the Start menu shortcut starts
it (`uvw run python -m quickpick.gui`).

Not the `quickpick-gui` script: that runs through the venv's pythonw.exe, which uv makes a
console launcher, so a console window would open beside the popup. uvw starts the venv's
python.exe with no window instead."""

from quickpick.launch import gui_main

if __name__ == "__main__":
    gui_main()
