# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyautogui",
#   "pillow",
#   "pytesseract",
#   "opencv-python",
#   "pyyaml",
#   "pywin32",
# ]
# ///

"""
Screenshot all skins for the currently selected god.

Navigate to the god's skin selection screen in-game, then run:
    uv run screenshotter.py

The script will iterate every skin card in the grid (scrolling as needed),
click each one, OCR the skin name, and save the model view to:
    output/<GodName>/<SkinName>.png
"""

import re
import time
from pathlib import Path

try:
    import win32gui, win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

import cv2
import numpy as np
import pyautogui
import pytesseract
import yaml
from PIL import Image, ImageGrab

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path("config.yaml")


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


CFG = load_config()
pytesseract.pytesseract.tesseract_cmd = CFG.get(
    "tesseract_path", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

DELAYS      = CFG["delays"]
REGIONS     = CFG["regions"]
GRID_CFG    = CFG["grid"]
OUTPUT_DIR  = Path(CFG.get("output_dir", "output"))

# Unpack grid geometry
_fc         = REGIONS["first_card"]   # [left, top, w, h]
CARD_W      = _fc[2]
CARD_H      = _fc[3]
CARD_LEFT   = _fc[0]
CARD_TOP    = _fc[1]
GAP_X       = GRID_CFG["gap_x"]
GAP_Y       = GRID_CFG["gap_y"]
COLUMNS     = GRID_CFG["columns"]

_ga         = REGIONS["grid_area"]    # [left, top, w, h]
GRID_BOTTOM = _ga[1] + _ga[3]

ROWS_PER_SCROLL    = 2   # rows advanced per scroll step (matches visible rows)

# ── Helpers ───────────────────────────────────────────────────────────────────

def region_center(region: list) -> tuple[int, int]:
    l, t, w, h = region
    return l + w // 2, t + h // 2


def click_at(x: int, y: int, delay: float = DELAYS["after_click"]):
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click()
    time.sleep(delay)


def capture(region: list) -> Image.Image:
    l, t, w, h = region
    return ImageGrab.grab(bbox=(l, t, l + w, t + h))


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Upscale and threshold to improve Tesseract accuracy on game UI text."""
    arr = np.array(img.convert("L"))
    arr = cv2.resize(arr, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    _, arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(arr)


def ocr(region: list) -> str:
    img = preprocess_for_ocr(capture(region))
    text = pytesseract.image_to_string(img, config="--psm 7").strip()
    return text


def sanitize_filename(name: str) -> str:
    """Turn OCR text into a safe filename component."""
    name = name.strip()
    name = re.sub(r"[^\w\s\-]", "", name)   # keep word chars, spaces, hyphens
    name = re.sub(r"\s+", "_", name)         # spaces → underscores
    return name or "unknown"


def images_equal(a: Image.Image, b: Image.Image, threshold: float = 0.995) -> bool:
    """Return True if two images are visually the same (>= threshold fraction of matching pixels)."""
    arr_a = np.array(a.convert("RGB"), dtype=np.float32)
    arr_b = np.array(b.convert("RGB"), dtype=np.float32)
    if arr_a.shape != arr_b.shape:
        return False
    diff = np.abs(arr_a - arr_b)
    matching = np.mean(diff < 5)   # pixels within 5 grey levels count as equal
    return float(matching) >= threshold


# ── Grid iteration ────────────────────────────────────────────────────────────

def visible_card_centers() -> list[tuple[int, int]]:
    """
    Compute screen (x, y) centers for every card slot that is fully visible
    within grid_area vertically. Card positions are fixed on screen; the grid
    content scrolls underneath them.
    """
    centers = []
    row = 0
    while True:
        top = CARD_TOP + row * (CARD_H + GAP_Y)
        bottom = top + CARD_H
        if bottom > GRID_BOTTOM:
            break
        for col in range(COLUMNS):
            cx = CARD_LEFT + col * (CARD_W + GAP_X) + CARD_W // 2
            cy = top + CARD_H // 2
            centers.append((cx, cy))
        row += 1
    return centers


def find_thumb_bounds() -> tuple[int, int] | None:
    """
    Find the scrollbar thumb top/bottom Y in screen coordinates.
    The thumb is identified as the brightest continuous region in the track.
    Returns (thumb_top_y, thumb_bottom_y) or None if detection fails.
    """
    track = REGIONS["scrollbar_track"]
    l, t, w, h = track
    arr = np.array(capture(track).convert("L"), dtype=np.float32)  # grayscale

    row_brightness = arr.mean(axis=1)
    threshold = row_brightness.mean() * 1.2   # thumb is brighter than the track bg
    thumb_rows = np.where(row_brightness > threshold)[0]

    if len(thumb_rows) == 0:
        return None
    return int(thumb_rows[0]) + t, int(thumb_rows[-1]) + t


def scroll_grid_to_top():
    """Drag the scrollbar thumb to the top of the track."""
    bounds = find_thumb_bounds()
    if bounds is None:
        print("  Warning: could not detect scrollbar thumb for scroll-to-top.")
        return
    thumb_top, thumb_bottom = bounds
    l, t, w, h = REGIONS["scrollbar_track"]
    cx = l + w // 2
    thumb_cy = (thumb_top + thumb_bottom) // 2
    pyautogui.moveTo(cx, thumb_cy, duration=0.1)
    pyautogui.dragTo(cx, t + 3, duration=0.4, button="left")
    time.sleep(0.4)


def scroll_grid_down() -> bool:
    """
    Click just below the scrollbar thumb to page-down.
    Returns False if the thumb is already at the bottom (no more content).
    """
    bounds = find_thumb_bounds()
    if bounds is None:
        print("  Warning: could not detect scrollbar thumb.")
        return False

    thumb_top, thumb_bottom = bounds
    l, t, w, h = REGIONS["scrollbar_track"]
    track_bottom = t + h

    if thumb_bottom >= track_bottom - 8:
        return False   # already at the bottom

    # Click just below the thumb — standard Windows scrollbar "page down"
    cx = l + w // 2
    pyautogui.click(cx, thumb_bottom + 8)
    time.sleep(0.4)
    return True


# ── Main flow ─────────────────────────────────────────────────────────────────

def process_current_god(dry_run: bool = False):
    card_centers = visible_card_centers()
    print(f"Grid geometry: {len(card_centers)} card slots visible per page "
          f"({CARD_W}×{CARD_H}px, gap {GAP_X}px, {COLUMNS} cols), "
          f"scrolling via scrollbar ({ROWS_PER_SCROLL} rows per step)")

    print("\nScrolling grid to top...")
    scroll_grid_to_top()

    saved = 0
    skipped = 0
    page = 0

    while True:
        before_scroll = capture(REGIONS["grid_area"])

        for cx, cy in card_centers:
            click_at(cx, cy, delay=DELAYS["after_skin_select"])

            god_name  = sanitize_filename(ocr(REGIONS["god_name"]))
            skin_name = sanitize_filename(ocr(REGIONS["skin_name"]))

            dest = OUTPUT_DIR / god_name / f"{skin_name}.png"

            if dest.exists():
                print(f"  skip  {god_name}/{skin_name}.png (already exists)")
                skipped += 1
                continue

            if dry_run:
                print(f"  [dry] would save → {dest}")
                saved += 1
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            model_img = capture(REGIONS["model_view"])
            model_img.save(dest)
            print(f"  saved {dest}")
            saved += 1

        # Scroll down; stop if scrollbar is already at the bottom
        if not scroll_grid_down():
            print("\nReached end of skin grid (scrollbar at bottom).")
            break

        # Fallback: if the grid content didn't change despite the scroll, stop
        after_scroll = capture(REGIONS["grid_area"])
        if images_equal(before_scroll, after_scroll):
            print("\nReached end of skin grid (grid content unchanged).")
            break

        page += 1
        print(f"  --- scrolled to page {page + 1} ---")

    print(f"\nDone. saved={saved} skipped={skipped}")


def focus_smite_window():
    if not HAS_WIN32:
        print("Warning: pywin32 not available, cannot focus game window.")
        return
    results = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and "smite 2" in win32gui.GetWindowText(hwnd).lower():
            results.append(hwnd)
    win32gui.EnumWindows(cb, None)
    if not results:
        print("Warning: Smite 2 window not found. Is the game running?")
        return
    win32gui.ShowWindow(results[0], win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(results[0])
    time.sleep(0.5)  # let the window come to front before any input


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no files will be written.\n")
    focus_smite_window()
    process_current_god(dry_run=dry_run)
