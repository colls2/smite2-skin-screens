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
    output/<god-skin-slug>.png

A manifest is written / merged to output/manifest.json after each god.
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


def make_id(name: str) -> str:
    """Produce a URL/filename-safe slug from a display name."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-{2,}", "-", name)   # collapse consecutive dashes (e.g. from " - ")
    return name.strip("-") or "unknown"


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


def detect_scrollable() -> bool:
    """
    Detect whether the skin grid has more than two rows of cards (i.e. needs scrolling).

    Strategy: click the first card (top-left), OCR its skin name, then click 20px
    into the top of the third row (which is partially visible but not in
    visible_card_centers). If the skin name changes, a card is present there →
    grid is scrollable. If unchanged → empty space → no scrollbar.

    Works regardless of card art animation because we compare text names, not images.
    """
    first_cx = CARD_LEFT + CARD_W // 2
    first_cy = CARD_TOP + CARD_H // 2
    click_at(first_cx, first_cy, delay=DELAYS["after_skin_select"])
    name_before = ocr(REGIONS["skin_name"]).strip()

    # 20 px into the top of the third row, same column
    third_row_cy = CARD_TOP + 2 * (CARD_H + GAP_Y) + 20
    click_at(first_cx, third_row_cy, delay=DELAYS["after_skin_select"])
    name_after = ocr(REGIONS["skin_name"]).strip()

    scrollable = name_after.lower() != name_before.lower()
    mode = "SCROLLABLE" if scrollable else "SINGLE PAGE"
    print(f"  Mode: {mode}  (row-1={name_before!r}  row-3={name_after!r})")

    # Leave the first card selected
    click_at(first_cx, first_cy, delay=DELAYS["after_skin_select"])
    return scrollable


def scroll_grid_to_top():
    """
    Scroll the skin grid back to the top.

    Tries to drag the scrollbar thumb to the top; falls back to clicking the top
    of the track (which is the standard Windows scroll-to-top behaviour when there
    is no detectable thumb).
    """
    l, t, w, h = REGIONS["scrollbar_track"]
    cx = l + w // 2
    bounds = find_thumb_bounds()
    if bounds is not None:
        thumb_top, thumb_bottom = bounds
        thumb_cy = (thumb_top + thumb_bottom) // 2
        pyautogui.moveTo(cx, thumb_cy, duration=0.1)
        pyautogui.dragTo(cx, t + 3, duration=0.4, button="left")
        time.sleep(0.4)
        print(f"  [scroll_to_top] dragged thumb (span={thumb_bottom - thumb_top}px) to top")
    else:
        pyautogui.click(cx, t + 3)
        time.sleep(0.3)
        print("  [scroll_to_top] no thumb — clicked track top as fallback")


def scroll_grid_down() -> bool:
    """
    Page-down the skin grid. Returns True if the grid actually scrolled.

    Uses the first card's skin name as the scroll oracle — reliable even when
    the scrollbar thumb can't be detected visually (e.g. theme-matched track).
    Falls back to clicking the lower quarter of the track when no thumb is found.
    """
    first_cx = CARD_LEFT + CARD_W // 2
    first_cy = CARD_TOP + CARD_H // 2
    click_at(first_cx, first_cy, delay=0.3)
    name_before = ocr(REGIONS["skin_name"]).strip()

    l, t, w, h = REGIONS["scrollbar_track"]
    bounds = find_thumb_bounds()
    if bounds is not None:
        click_y = min(bounds[1] + 8, t + h - 2)
        print(f"  [scroll_down] thumb at {bounds[0]}–{bounds[1]}, clicking y={click_y}")
    else:
        click_y = t + (h * 3 // 4)   # lower quarter of track → page-down zone
        print(f"  [scroll_down] no thumb, clicking lower track y={click_y}")

    pyautogui.click(l + w // 2, click_y)
    time.sleep(0.4)

    click_at(first_cx, first_cy, delay=0.3)
    name_after = ocr(REGIONS["skin_name"]).strip()

    scrolled = name_after.lower() != name_before.lower()
    marker = "scrolled" if scrolled else "no change"
    print(f"  [scroll_down] {marker}: {name_before!r} → {name_after!r}")
    return scrolled


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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    capture(REGIONS["model_view"]).save(dest)
    return "saved"


def _log_save(status: str, filename: str, label: str = "") -> tuple[int, int]:
    """Print a save/skip/dry line and return (saved_delta, skipped_delta)."""
    suffix = f" ({label})" if label else ""
    if status == "skipped":
        print(f"  skip  {filename}{suffix} (already exists)")
        return 0, 1
    if status == "dry":
        print(f"  [dry] would save → {filename}{suffix}")
        return 1, 0
    print(f"  saved {filename}{suffix}")
    return 1, 0


def _update_manifest(god_name_raw: str, skins: list[dict], dry_run: bool):
    """Merge skins into the global output/manifest.json."""
    manifest_path = OUTPUT_DIR / "manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception:
        data = {}

    data.setdefault("meta", {"tool": "s2-skin-screenshotter"})
    data["meta"]["last_updated"] = time.strftime("%Y-%m-%d")
    data.setdefault("gods", [])

    god_entry = next((g for g in data["gods"] if g["name"] == god_name_raw), None)
    if god_entry is None:
        god_entry = {"name": god_name_raw, "skins": []}
        data["gods"].append(god_entry)

    by_name = {s["name"]: s for s in god_entry["skins"]}
    for skin in skins:
        by_name[skin["name"]] = skin
    god_entry["skins"] = list(by_name.values())

    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Manifest → {manifest_path}")


def process_current_god(dry_run: bool = False):
    card_centers = visible_card_centers()
    print(f"Grid geometry: {len(card_centers)} card slots visible per page "
          f"({CARD_W}×{CARD_H}px, gap {GAP_X}px, {COLUMNS} cols), "
          f"scrolling via scrollbar ({ROWS_PER_SCROLL} rows per step)")

    print("\nDetecting scroll mode...")
    scrollable = detect_scrollable()

    print("Scrolling grid to top...")
    scroll_grid_to_top()

    saved = 0
    skipped = 0
    page = 0
    god_name_raw = "unknown"
    god_skins: list[dict] = []

    while True:
        for cx, cy in card_centers:
            click_at(cx, cy, delay=DELAYS["after_skin_select"])

            god_name_raw = ocr(REGIONS["god_name"]).strip()
            skin_name_raw = ocr(REGIONS["skin_name"]).strip()

            _cur, total_prisms = get_prism_info()

            if total_prisms > 0:
                # Prism 1/N is the base skin; prisms 2..N are recolors with names
                # of the form "Base Skin Name - Recolor Name".
                navigate_to_first_prism()

                base_name_raw = ocr(REGIONS["skin_name"]).strip()
                base_slug = make_id(god_name_raw + " " +base_name_raw)
                base_file = f"{base_slug}.png"
                s, k = _log_save(save_image(OUTPUT_DIR / base_file, dry_run), base_file,
                                 f"prism 1/{total_prisms}")
                saved += s; skipped += k

                skin_entry: dict = {
                    "name": base_name_raw,
                    "file": base_file,
                    "prisms": [],
                }

                for i in range(2, total_prisms + 1):
                    if REGIONS.get("btn_prism_next"):
                        click_at(*region_center(REGIONS["btn_prism_next"]),
                                 delay=DELAYS.get("after_prism_nav", 0.4))
                    recolor_raw = ocr(REGIONS["skin_name"]).strip()
                    recolor_slug = make_id(god_name_raw + " " +recolor_raw)
                    recolor_file = f"{recolor_slug}.png"
                    s, k = _log_save(save_image(OUTPUT_DIR / recolor_file, dry_run),
                                     recolor_file, f"prism {i}/{total_prisms}")
                    saved += s; skipped += k

                    skin_entry["prisms"].append({
                        "name": recolor_raw,
                        "index": i - 1,   # 1-based among recolors
                        "file": recolor_file,
                    })

                god_skins.append(skin_entry)

            else:
                slug = make_id(god_name_raw + " " +skin_name_raw)
                filename = f"{slug}.png"
                s, k = _log_save(save_image(OUTPUT_DIR / filename, dry_run), filename)
                saved += s; skipped += k

                god_skins.append({
                    "name": skin_name_raw,
                    "file": filename,
                    "prisms": [],
                })

        if not scroll_grid_down():
            print("\nReached end of skin grid.")
            break

        page += 1
        print(f"  --- scrolled to page {page + 1} ---")

    _update_manifest(god_name_raw, god_skins, dry_run)
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
