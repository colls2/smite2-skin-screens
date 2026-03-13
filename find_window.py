# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyautogui",
#   "pywin32",
# ]
# ///

"""
Locate and focus the Smite 2 game window.
Run with: uv run find_window.py
"""

import sys
import win32gui
import win32con


WINDOW_TITLE_FRAGMENT = "SMITE 2"


def find_smite_window() -> int | None:
    """Return the hwnd of the Smite 2 window, or None if not found."""
    results = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if WINDOW_TITLE_FRAGMENT.lower() in title.lower():
                results.append((hwnd, title))

    win32gui.EnumWindows(callback, None)
    return results[0] if results else None


def focus_window(hwnd: int):
    """Bring the window to the foreground."""
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the window."""
    return win32gui.GetWindowRect(hwnd)


if __name__ == "__main__":
    print(f"Looking for window containing '{WINDOW_TITLE_FRAGMENT}'...")
    match = find_smite_window()

    if not match:
        print("  [FAIL] Smite 2 window not found. Is the game running?")
        sys.exit(1)

    hwnd, title = match
    print(f"  [OK] Found: '{title}' (hwnd={hwnd})")

    rect = get_window_rect(hwnd)
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    print(f"  [OK] Position: ({left}, {top})  Size: {width}x{height}")

    focus_window(hwnd)
    print("  [OK] Window focused.")
