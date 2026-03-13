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

import json
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

    # A real thumb occupies only a fraction of the track.
    # If >60% of rows are "bright", this is card art bleeding into the region — no scrollbar.
    if len(thumb_rows) > len(row_brightness) * 0.6:
        return None

    return int(thumb_rows[0]) + t, int(thumb_rows[-1]) + t


def scroll_grid_to_top():
    """Drag the scrollbar thumb to the top of the track. No-op if no scrollbar."""
    bounds = find_thumb_bounds()
    if bounds is None:
        return  # no scrollbar — grid fits on one page, nothing to scroll
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
    Returns False if the grid didn't scroll (no real scrollbar, or already at bottom).

    Uses thumb-position comparison rather than grid-image comparison because the
    animated 3D model background causes the grid_area image to change between frames
    even when no scroll occurs, making image-diff checks unreliable.
    """
    before_bounds = find_thumb_bounds()
    if before_bounds is None:
        return False

    thumb_top, thumb_bottom = before_bounds
    l, t, w, h = REGIONS["scrollbar_track"]
    track_bottom = t + h

    if thumb_bottom >= track_bottom - 8:
        return False   # thumb already at the bottom

    # Click just below the thumb — standard Windows scrollbar "page down"
    cx = l + w // 2
    pyautogui.click(cx, thumb_bottom + 8)
    time.sleep(0.4)

    after_bounds = find_thumb_bounds()
    if after_bounds is None:
        return False

    # If the thumb didn't move, the "thumb" was a static UI element
    # (e.g., the decorative panel border) — not a real scrollbar thumb
    if abs(after_bounds[0] - before_bounds[0]) < 3:
        return False

    return True


# ── Prism helpers ─────────────────────────────────────────────────────────────

def get_prism_info() -> tuple[int, int]:
    """
    OCR the prism counter region.
    Returns (current_index, total), e.g. "4/5" → (4, 5).
    Returns (0, 0) if the region is unconfigured or pattern not found.
    """
    if not REGIONS.get("prism_counter"):
        return 0, 0
    text = ocr(REGIONS["prism_counter"])
    m = re.search(r'(\d+)\s*/\s*(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def navigate_to_first_prism():
    """Click ◄ until the prism counter shows 1/N."""
    if not REGIONS.get("btn_prism_prev"):
        return
    for _ in range(30):  # safety limit
        cur, _total = get_prism_info()
        if cur <= 1:
            break
        click_at(*region_center(REGIONS["btn_prism_prev"]), delay=DELAYS.get("after_prism_nav", 0.4))


# ── Main flow ─────────────────────────────────────────────────────────────────

def save_image(dest: Path, dry_run: bool) -> str:
    """Capture model_view and save to dest. Returns 'saved', 'skipped', or 'dry'."""
    if dest.exists():
        return "skipped"
    if dry_run:
        return "dry"
    dest.parent.mkdir(parents=True, exist_ok=True)
    capture(REGIONS["model_view"]).save(dest)
    return "saved"


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
    god_name = "unknown"
    manifest: list[dict] = []

    while True:
        for cx, cy in card_centers:
            click_at(cx, cy, delay=DELAYS["after_skin_select"])

            god_name  = sanitize_filename(ocr(REGIONS["god_name"]))
            skin_name = sanitize_filename(ocr(REGIONS["skin_name"]))

            cur_prism, total_prisms = get_prism_info()

            if total_prisms > 0:
                # Card has prism variants. Prism 1/N is the base skin; 2..N are recolors.
                skin_entry: dict = {"prisms": []}
                navigate_to_first_prism()

                for i in range(1, total_prisms + 1):
                    prism_name_raw = ocr(REGIONS["skin_name"])
                    prism_name = sanitize_filename(prism_name_raw)
                    dest = OUTPUT_DIR / god_name / f"{prism_name}.png"
                    status = save_image(dest, dry_run)

                    label = f"{god_name}/{prism_name}.png (prism {i}/{total_prisms})"
                    if status == "skipped":
                        print(f"  skip  {label} (already exists)")
                        skipped += 1
                    elif status == "dry":
                        print(f"  [dry] would save → {label}")
                        saved += 1
                    else:
                        print(f"  saved {label}")
                        saved += 1

                    skin_entry["prisms"].append({
                        "name": prism_name_raw.strip(),
                        "index": i,
                        "file": f"{god_name}/{prism_name}.png",
                    })

                    if i == 1:
                        # Record base skin fields from first prism
                        skin_entry["name"] = prism_name_raw.strip()
                        skin_entry["file"] = f"{god_name}/{prism_name}.png"
                        skin_entry["is_prism_skin"] = True

                    if i < total_prisms and REGIONS.get("btn_prism_next"):
                        click_at(*region_center(REGIONS["btn_prism_next"]),
                                 delay=DELAYS.get("after_prism_nav", 0.4))

                manifest.append(skin_entry)

            else:
                # No prisms — single capture.
                dest = OUTPUT_DIR / god_name / f"{skin_name}.png"
                status = save_image(dest, dry_run)

                label = f"{god_name}/{skin_name}.png"
                if status == "skipped":
                    print(f"  skip  {label} (already exists)")
                    skipped += 1
                elif status == "dry":
                    print(f"  [dry] would save → {label}")
                    saved += 1
                else:
                    print(f"  saved {label}")
                    saved += 1

                manifest.append({
                    "name": skin_name,
                    "file": f"{god_name}/{skin_name}.png",
                    "is_prism_skin": False,
                    "prisms": [],
                })

        if not scroll_grid_down():
            print("\nReached end of skin grid.")
            break

        page += 1
        print(f"  --- scrolled to page {page + 1} ---")

    # Save per-god manifest
    if manifest:
        god_dir = OUTPUT_DIR / god_name
        god_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = god_dir / "skins.json"
        existing: list = []
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        # Merge: update existing entries by name, append new ones
        by_name = {e["name"]: e for e in existing}
        for entry in manifest:
            by_name[entry["name"]] = entry
        manifest_path.write_text(
            json.dumps(list(by_name.values()), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Manifest saved → {manifest_path}")

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
