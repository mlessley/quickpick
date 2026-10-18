# Global hotkeys via ctypes + RegisterHotKey, not keyboard/pynput

Quickpick runs on a managed Windows laptop without admin rights and needs global hotkeys that work regardless of window focus. We use `ctypes` bindings to the Win32 `RegisterHotKey` API rather than the `keyboard` or `pynput` libraries. Both of those work by installing a low-level keyboard hook that sees every keystroke system-wide, which is far more access than a launcher needs and the kind of behaviour endpoint security software is right to be wary of. `RegisterHotKey` is least privilege: it only fires for the exact registered combination, sees nothing else, and needs no admin rights.

This rules out features that need to watch keys in general, such as summoning with a double tap of Ctrl.
