"""Bundled xVPN branding. No runtime dependencies beyond Tkinter."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
import tkinter as tk

ASSET_DIR = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSET_DIR / "xvpn.ico"
COMPACT_PNG_PATH = ASSET_DIR / "xvpn_compact.png"


def apply_application_icon(root: tk.Tk) -> bool:
    """Set a real OS window/taskbar icon rather than changing a screenshot.

    On Windows, the .ico includes purpose-made small frames for 16/24/32px.
    On other platforms, Tk's iconphoto uses a compact PNG.
    If the asset was removed or the platform rejects it, retain Tk defaults.
    """
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "xVPN.Manager.Desktop"
            )
        except (AttributeError, OSError):
            pass
        if ICON_PATH.is_file():
            try:
                root.iconbitmap(default=str(ICON_PATH))
                return True
            except tk.TclError:
                pass
    if COMPACT_PNG_PATH.is_file():
        try:
            photo = tk.PhotoImage(master=root, file=str(COMPACT_PNG_PATH))
            root.iconphoto(True, photo)
            root._xvpn_window_icon = photo  # Keep Tk reference alive.
            return True
        except tk.TclError:
            pass
    return False


def load_header_icon(root: tk.Tk) -> tk.PhotoImage | None:
    if not COMPACT_PNG_PATH.is_file():
        return None
    try:
        photo = tk.PhotoImage(master=root, file=str(COMPACT_PNG_PATH))
        return photo.subsample(6, 6)  # about 43x43 px; no Pillow needed on end-user PC
    except tk.TclError:
        return None
