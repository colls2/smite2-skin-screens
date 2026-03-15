# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pillow",
#   "pywin32",
#   "pyyaml",
#   "pyautogui",
#   "numpy",
# ]
# ///

"""
Scroll calibration diagnostic.

Drags the scrollbar thumb to a computed target position for each row
and saves a screenshot so you can visually verify the grid alignment.

Run with:  uv run test_scroll.py
"""

import time
import math
from pathlib import Path
from PIL import ImageGrab, ImageDraw, Image
import yaml
import pyautogui
import numpy as np

try:
    import win32gui, win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

CONFIG_PATH = Path("config.yaml")
OUT_DIR = Path("scroll_test_out")


# ── Config loading ────────────────────────────────────────────────────────────

def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def focus_smite_window():
    if not HAS_WIN32:
        print("  (no pywin32 — skipping window focus)")
        return
    results = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and "smite 2" in win32gui.GetWindowText(hwnd).lower():
            results.append(hwnd)
    win32gui.EnumWindows(cb, None)
    if not results:
        print("ERROR: Smite 2 window not found — launch the game first.")
        raise SystemExit(1)
    win32gui.ShowWindow(results[0], win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(results[0])
    time.sleep(0.5)


# ── Thumb detection (identical to screenshotter.py / calibrate.py) ────────────

def find_thumb_bounds(track: list) -> tuple[int, int] | None:
    """
    Hover at track centre to highlight the thumb, then detect the largest
    contiguous bright run. Returns (thumb_top_y, thumb_bottom_y) in screen
    coordinates, or None.
    """
    l, t, w, h = track
    hover_x = l + w // 2
    hover_y = t + h // 2
    pyautogui.moveTo(hover_x, hover_y, duration=0.05)
    time.sleep(0.15)  # let highlight settle

    img = ImageGrab.grab(bbox=(l, t, l + w, t + h))
    arr = np.array(img.convert("L"), dtype=np.float32)
    row_brightness = arr.mean(axis=1)
    lo, hi = float(row_brightness.min()), float(row_brightness.max())

    print(f"  track strip: lo={lo:.1f}  hi={hi:.1f}  contrast={hi-lo:.1f}")
    if hi - lo < 10:
        print("  ! contrast too low — thumb not detectable")
        return None

    threshold = lo + (hi - lo) * 0.4
    bright = np.where(row_brightness > threshold)[0]
    if len(bright) == 0:
        return None

    # Build contiguous runs with 5-row gap tolerance
    runs: list[tuple[int, int]] = []
    r_start = int(bright[0])
    r_prev  = r_start
    for r in bright[1:]:
        r = int(r)
        if r - r_prev > 5:
            runs.append((r_start, r_prev))
            r_start = r
        r_prev = r
    runs.append((r_start, r_prev))

    top_local, bot_local = max(runs, key=lambda r: r[1] - r[0])

    # Trim gradient bleed from each edge using a stricter threshold
    strict = lo + (hi - lo) * 0.6
    while top_local < bot_local and row_brightness[top_local] < strict:
        top_local += 1
    while bot_local > top_local and row_brightness[bot_local] < strict:
        bot_local -= 1

    return top_local + t, bot_local + t


def drag_thumb_to(track: list, target_cy: int):
    """
    Drag scrollbar thumb to target_cy using slow, deliberate mouse events:
      - move to thumb centre
      - mouseDown, hold 500 ms
      - moveTo target over 1 second
      - hold at target 500 ms
      - mouseUp
    """
    l, t, w, h = track
    cx = l + w // 2

    bounds = find_thumb_bounds(track)
    if bounds is None:
        print("  ! thumb not found — skipping drag")
        return
    current_cy = (bounds[0] + bounds[1]) // 2
    print(f"  drag y={current_cy} → y={target_cy}  (delta={target_cy - current_cy:+d}px)")

    pyautogui.moveTo(cx, current_cy, duration=0.15)
    pyautogui.mouseDown(button="left")
    time.sleep(0.5)                                   # hold before moving
    pyautogui.moveTo(cx, target_cy, duration=1.0)     # slow precise drag
    time.sleep(0.5)                                   # hold at target before release
    pyautogui.mouseUp(button="left")
    time.sleep(0.3)                                   # let game settle


# ── Annotated screenshot helpers ──────────────────────────────────────────────

def annotate_and_save(
    tag: str,
    cfg: dict,
    thumb_target_cy: int | None,
    note: str,
):
    """
    Take a full screenshot and draw:
      - green dashed box around grid_area
      - red horizontal line at GRID_BOTTOM
      - yellow horizontal lines at expected card-row boundaries (bottom_row_cy)
      - cyan dot at thumb target position on the scrollbar track
      - magenta bar showing measured thumb span
    """
    OUT_DIR.mkdir(exist_ok=True)

    regions = cfg["regions"]
    grid    = regions["grid_area"]    # [l, t, w, h]
    track   = regions["scrollbar_track"]
    fc      = regions["first_card"]

    CARD_H  = fc[3]
    CARD_TOP = fc[1]
    CARD_W  = fc[2]
    CARD_LEFT = fc[0]
    GAP_Y   = cfg["grid"]["gap_y"]
    GAP_X   = cfg["grid"]["gap_x"]
    COLS    = cfg["grid"]["columns"]
    GRID_BOTTOM = grid[1] + grid[3]

    # Measure actual thumb position BEFORE screenshotting
    bounds = find_thumb_bounds(track)

    img = ImageGrab.grab()
    draw = ImageDraw.Draw(img)

    # Grid area outline (green)
    draw.rectangle(
        [grid[0], grid[1], grid[0] + grid[2], grid[1] + grid[3]],
        outline="lime", width=2,
    )

    # GRID_BOTTOM line (red)
    draw.line([(0, GRID_BOTTOM), (img.width, GRID_BOTTOM)], fill="red", width=2)

    # bottom_row_cy (where we click for bottom-aligned rows) - yellow line
    bottom_row_cy = GRID_BOTTOM - CARD_H // 2
    draw.line([(0, bottom_row_cy), (img.width, bottom_row_cy)], fill="yellow", width=1)

    # Card column centres — dotted vertical lines
    for col in range(COLS):
        cx = CARD_LEFT + col * (CARD_W + GAP_X) + CARD_W // 2
        draw.line([(cx, grid[1]), (cx, GRID_BOTTOM)], fill=(255, 255, 0, 128), width=1)

    # Thumb target on track (cyan dot)
    tcx = track[0] + track[2] // 2
    if thumb_target_cy is not None:
        r = 6
        draw.ellipse([tcx - r, thumb_target_cy - r, tcx + r, thumb_target_cy + r],
                     outline="cyan", width=2)
        draw.line([(track[0] - 20, thumb_target_cy), (track[0] + track[2] + 20, thumb_target_cy)],
                  fill="cyan", width=1)

    # Actual measured thumb (magenta bar)
    if bounds is not None:
        draw.rectangle(
            [track[0] - 4, bounds[0], track[0] + track[2] + 4, bounds[1]],
            outline="magenta", width=3,
        )
        actual_cy = (bounds[0] + bounds[1]) // 2
        draw.line([(track[0] - 20, actual_cy), (track[0] + track[2] + 20, actual_cy)],
                  fill="magenta", width=1)

    # Note text
    draw.text((10, 10), note, fill="white")

    path = OUT_DIR / f"{tag}.png"
    img.save(str(path))
    print(f"  → saved {path}")

    # Also print a thumbnail of the track strip for debugging
    if bounds is not None:
        th = bounds[1] - bounds[0]
        print(f"  measured thumb: y={bounds[0]}..{bounds[1]}  h={th}px  cy={(bounds[0]+bounds[1])//2}")
    return bounds


# ── Main diagnostic ───────────────────────────────────────────────────────────

def main():
    cfg     = load_config()
    regions = cfg["regions"]
    track   = regions["scrollbar_track"]   # [l, t, w, h]
    grid    = regions["grid_area"]
    fc      = regions["first_card"]

    l_tr, t_tr, w_tr, h_tr = track
    CARD_H   = fc[3]
    CARD_TOP = fc[1]
    GAP_Y    = cfg["grid"]["gap_y"]
    GRID_BOTTOM = grid[1] + grid[3]
    grid_visible_h = GRID_BOTTOM - CARD_TOP
    visible_rows = grid_visible_h / (CARD_H + GAP_Y)
    bottom_row_cy = GRID_BOTTOM - CARD_H // 2

    print("═══ Scroll diagnostic ═══")
    print(f"  track:          [{l_tr}, {t_tr}, {w_tr}, {h_tr}]  (left, top, w, h)")
    print(f"  track_top:      {t_tr}")
    print(f"  track_bottom:   {t_tr + h_tr}")
    print(f"  grid_area:      {grid}")
    print(f"  GRID_BOTTOM:    {GRID_BOTTOM}")
    print(f"  CARD_TOP:       {CARD_TOP}  CARD_H={CARD_H}  GAP_Y={GAP_Y}")
    print(f"  grid_visible_h: {grid_visible_h}px")
    print(f"  visible_rows:   {visible_rows:.3f}")
    print(f"  bottom_row_cy:  {bottom_row_cy}  (click Y for bottom-aligned cards)")
    print()

    print("Focusing Smite 2...")
    focus_smite_window()
    time.sleep(0.3)

    # ── Step 0: snapshot current state before touching anything ───────────────
    print("\n── Step 0: snapshot (no scrolling) ──")
    print("  Detecting thumb at current scroll position:")
    bounds_now = find_thumb_bounds(track)

    OUT_DIR.mkdir(exist_ok=True)
    img0 = ImageGrab.grab()
    draw0 = ImageDraw.Draw(img0)

    # Red rectangle = track region from config
    draw0.rectangle(
        [l_tr, t_tr, l_tr + w_tr, t_tr + h_tr],
        outline="red", width=3,
    )
    draw0.line([(l_tr - 30, t_tr),        (l_tr + w_tr + 30, t_tr)],        fill="red", width=1)
    draw0.line([(l_tr - 30, t_tr + h_tr), (l_tr + w_tr + 30, t_tr + h_tr)], fill="red", width=1)
    draw0.text((l_tr + w_tr + 6, t_tr),            f"config top={t_tr}",        fill="red")
    draw0.text((l_tr + w_tr + 6, t_tr + h_tr - 12), f"config bot={t_tr + h_tr}", fill="red")

    # Blue bar = detected thumb span, drawn just to the right of the track
    bar_x1 = l_tr + w_tr + 20
    bar_x2 = bar_x1 + 14
    if bounds_now is not None:
        th_top, th_bot = bounds_now
        th_cy = (th_top + th_bot) // 2
        draw0.rectangle([bar_x1, th_top, bar_x2, th_bot], fill="#4488ff")
        draw0.line([(l_tr - 30, th_top), (bar_x2 + 4, th_top)], fill="#4488ff", width=1)
        draw0.line([(l_tr - 30, th_bot), (bar_x2 + 4, th_bot)], fill="#4488ff", width=1)
        draw0.text((bar_x2 + 6, th_top),      f"thumb top={th_top}",   fill="#4488ff")
        draw0.text((bar_x2 + 6, th_bot - 12), f"thumb bot={th_bot}",   fill="#4488ff")
        draw0.text((bar_x2 + 6, th_cy - 6),   f"h={th_bot - th_top}px", fill="white")
        print(f"  thumb: y={th_top}..{th_bot}  h={th_bot - th_top}px  cy={th_cy}")
        print(f"  offset from config top: {th_top - t_tr:+d}px  (positive = thumb starts BELOW config top)")
        print(f"  offset from config bot: {(t_tr + h_tr) - th_bot:+d}px  (positive = thumb ends ABOVE config bot)")
    else:
        draw0.text((bar_x1, t_tr + h_tr // 2), "NOT DETECTED", fill="red")
        print("  ! thumb not detected")

    path0 = OUT_DIR / "00_detected.png"
    img0.save(str(path0))
    print(f"  → saved {path0}")

    # ── Step 1: drag to top ───────────────────────────────────────────────────
    print("\n── Step 1: drag thumb to top ──")
    cx = l_tr + w_tr // 2
    bounds = find_thumb_bounds(track)
    if bounds:
        thumb_cy = (bounds[0] + bounds[1]) // 2
        pyautogui.moveTo(cx, thumb_cy, duration=0.1)
        pyautogui.dragTo(cx, t_tr + 3, duration=0.5, button="left")
        time.sleep(0.5)

    print("\nMeasuring thumb at top:")
    bounds_top = annotate_and_save(
        "01_at_top", cfg,
        thumb_target_cy=t_tr + 3,
        note="Step 1: thumb at TOP  (grid should show rows 1-2)",
    )
    if bounds_top is None:
        print("Cannot continue — thumb not detected at top.")
        return

    vis_thumb_h = bounds_top[1] - bounds_top[0]
    total_rows = round(visible_rows * h_tr / vis_thumb_h)
    print(f"  total_rows  = round({visible_rows:.3f} × {h_tr} / {vis_thumb_h}) = {total_rows}")

    # ── Compute targets using CURRENT formula ─────────────────────────────────
    print("\n── Scroll targets (current formula) ──")
    targets_current = {}
    for row in range(3, total_rows + 1):
        cy = int(round(t_tr + row * h_tr / total_rows - vis_thumb_h // 2))
        targets_current[row] = cy
        print(f"  row {row} → thumb_cy = {t_tr} + {row}×{h_tr}/{total_rows} - {vis_thumb_h//2} = {cy}")

    # ── Compute targets using CORRECT formula ──────────────────────────────────
    print("\n── Scroll targets (correct formula) ──")
    targets_correct = {}
    for row in range(3, total_rows + 1):
        f = (row - visible_rows) / (total_rows - visible_rows)
        cy = int(round(t_tr + vis_thumb_h / 2 + f * (h_tr - vis_thumb_h)))
        targets_correct[row] = cy
        print(f"  row {row} → f={f:.4f}  thumb_cy = {t_tr} + {vis_thumb_h//2} + {f:.4f}×{h_tr - vis_thumb_h} = {cy}")

    print()
    print("  row  | current | correct | diff")
    print("  -----|---------|---------|-----")
    for row in range(3, total_rows + 1):
        diff = targets_current[row] - targets_correct[row]
        print(f"  {row:4d} | {targets_current[row]:7d} | {targets_correct[row]:7d} | {diff:+4d}")
    print()

    # ── Step 2: drag to row 3 bottom-align, screenshot ────────────────────────
    print("\n── Step 2: drag to row 3 bottom-align ──")
    target3 = targets_correct[3]
    print(f"  target_cy for row 3 = {target3}")
    drag_thumb_to(track, target3)
    time.sleep(0.3)

    print("  Screenshot after row-3 alignment:")
    bounds_3 = annotate_and_save(
        "02_row3_bottom",
        cfg,
        thumb_target_cy=target3,
        note=f"Step 2: row 3 at bottom  (target thumb_cy={target3})\n"
             f"Bottom of last visible card should touch red line at y={GRID_BOTTOM}",
    )

    # ── Step 3: drag to each subsequent row ───────────────────────────────────
    for row in range(4, total_rows + 1):
        print(f"\n── Step {row}: drag to row {row} bottom-align ──")
        target = targets_correct[row]
        print(f"  target_cy for row {row} = {target}")
        drag_thumb_to(track, target)
        time.sleep(0.3)

        print(f"  Screenshot after row-{row} alignment:")
        annotate_and_save(
            f"0{row}_row{row}_bottom",
            cfg,
            thumb_target_cy=target,
            note=f"Step {row}: row {row} at bottom  (target thumb_cy={target})\n"
                 f"Bottom of last visible card should touch red line at y={GRID_BOTTOM}",
        )

    print(f"\n══ Done. Screenshots saved to {OUT_DIR}/ ══")
    print("Check each screenshot:")
    print("  - The MAGENTA bar shows where the thumb actually landed")
    print("  - The CYAN dot shows where we aimed")
    print("  - The RED line marks GRID_BOTTOM — card bottoms should touch it")
    print("  - The YELLOW line marks bottom_row_cy — card centres should be on it")


if __name__ == "__main__":
    main()
