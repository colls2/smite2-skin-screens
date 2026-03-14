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


def cursor_is_hand() -> bool:
    """Return True if the current cursor is the hand/pointer (IDC_HAND = 32649).

    Used to detect whether the mouse is hovering over a clickable card slot vs
    empty space in the grid. Requires pywin32; returns False on non-Windows or
    if detection fails (caller treats the slot as valid in that case).
    """
    if not HAS_WIN32:
        return False
    try:
        import ctypes
        _, hcursor, _ = win32gui.GetCursorInfo()
        hand_cursor = ctypes.windll.user32.LoadCursorW(0, 32649)  # IDC_HAND
        return bool(hcursor == hand_cursor)
    except Exception:
        return False


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


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


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


# ── Template-matching button finder ───────────────────────────────────────────

_template_cache: dict[str, np.ndarray | None] = {}

def _load_template(key: str) -> np.ndarray | None:
    if key not in _template_cache:
        path = CONFIG_PATH.parent / f"{key}_template.png"
        _template_cache[key] = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.exists() else None
    return _template_cache[key]


def _find_button(key: str) -> tuple[int, int]:
    """Locate a button via template matching; falls back to calibrated region center.

    Searches within the calibrated region expanded by template_search_margin pixels
    in every direction, so small UI shifts (e.g. prism buttons drifting up/down)
    are handled automatically.
    """
    region = REGIONS.get(key)
    if not region:
        raise KeyError(f"Region {key!r} not configured")
    template = _load_template(key)
    if template is None:
        return region_center(region)

    margin    = CFG.get("template_search_margin",   60)
    threshold = CFG.get("template_match_threshold", 0.7)
    l, t, w, h = region
    sl, st = max(0, l - margin), max(0, t - margin)
    sw, sh = w + 2 * margin, h + 2 * margin

    search_img = np.array(capture([sl, st, sw, sh]).convert("L"))
    result = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        print(f"  warn  template match {key!r} confidence {max_val:.2f} < {threshold} — using calibrated center")
        return region_center(region)

    th, tw = template.shape[:2]
    cx = sl + max_loc[0] + tw // 2
    cy = st + max_loc[1] + th // 2
    return cx, cy


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
    """Navigate to prism 1/N using whichever direction requires fewer clicks.
    Assumes the prism selector wraps: pressing ► at N/N goes to 1/N."""
    cur, total = get_prism_info()
    if cur <= 1 or total == 0:
        return
    backward_steps = cur - 1          # ◄ clicks to reach 1
    forward_steps  = total - cur + 1  # ► clicks to wrap through N back to 1
    if backward_steps <= forward_steps:
        btn_key, steps = "btn_prism_prev", backward_steps
    else:
        btn_key, steps = "btn_prism_next", forward_steps
    if not REGIONS.get(btn_key):
        return
    for _ in range(steps):
        click_at(*_find_button(btn_key), delay=DELAYS.get("after_prism_nav", 0.4))


# ── Main flow ─────────────────────────────────────────────────────────────────

def park_mouse():
    """Move the mouse to the configured park position (outside the capture area)."""
    park = CFG.get("mouse_park")
    if park:
        pyautogui.moveTo(park[0], park[1], duration=0.1)


def save_image(dest: Path, dry_run: bool) -> str:
    """Capture model_view and save to dest. Returns 'saved', 'skipped', or 'dry'."""
    if dest.exists():
        return "skipped"
    if dry_run:
        return "dry"
    delay = DELAYS.get("before_screenshot", 3.0)
    if delay > 0:
        time.sleep(delay)
    park_mouse()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    quality = CFG.get("webp_quality", 90)
    capture(REGIONS["model_view"]).save(dest, format="WEBP", quality=quality)
    return "saved"


def capture_spin_webp(dest: Path, dry_run: bool) -> str:
    """Capture an animated WebP: still frames then a full rotation drag.

    Sequence: spin_still_s seconds of the front pose (mouse parked), then
    spin_duration_s seconds of click-drag rotation across the model.
    The model is assumed to already be loaded (call after save_image).
    """
    if dest.exists():
        return "skipped"
    if dry_run:
        return "dry"

    drag_px    = CFG.get("spin_drag_px",    800)
    spin_dur   = CFG.get("spin_duration_s", 3.0)
    still_dur  = CFG.get("spin_still_s",    2.0)
    fps        = CFG.get("spin_fps",        15)
    scale      = CFG.get("spin_scale",      0.5)
    quality    = CFG.get("webp_quality",    90)

    frame_ms       = int(1000 / fps)
    frame_interval = frame_ms / 1000.0
    still_count    = max(1, int(still_dur * fps))

    park = CFG.get("mouse_park")
    park_mouse()

    l, t, w, h = REGIONS["model_view"]
    out_w = max(1, int(w * scale))
    out_h = max(1, int(h * scale))

    def grab_frame() -> Image.Image:
        img = capture(REGIONS["model_view"])
        if scale != 1.0:
            img = img.resize((out_w, out_h), Image.LANCZOS)
        return img

    frames: list[Image.Image] = []

    # Still frames — mouse is parked outside the capture region
    for _ in range(still_count):
        frames.append(grab_frame())
        time.sleep(frame_interval)

    # Spin frames — drag as one continuous move; capture frames concurrently in a thread
    # so the drag duration is exactly spin_dur (not inflated by grab overhead per step).
    import threading

    spin_frames: list[Image.Image] = []
    capturing = True

    def _capture_loop():
        while capturing:
            spin_frames.append(grab_frame())
            time.sleep(frame_interval)

    cap_thread = threading.Thread(target=_capture_loop, daemon=True)

    drag_x = park[0] if park else l + w // 2
    drag_y = park[1] if park else t + h // 2
    pyautogui.mouseDown(drag_x, drag_y, button="left")
    cap_thread.start()
    pyautogui.moveRel(drag_px, 0, duration=spin_dur)
    capturing = False
    cap_thread.join()
    pyautogui.mouseUp()

    frames.extend(spin_frames)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        dest, format="WEBP", save_all=True,
        append_images=frames[1:], duration=frame_ms,
        quality=quality, loop=0,
    )
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


def _init_manifest(dry_run: bool):
    """Create output/manifest.json with empty structure if it doesn't exist yet."""
    manifest_path = OUTPUT_DIR / "manifest.json"
    if manifest_path.exists():
        return
    data = {
        "meta": {"tool": "s2-skin-screenshotter", "created": time.strftime("%Y-%m-%d")},
        "gods": {},
    }
    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Manifest created → {manifest_path}")


def _update_manifest(god_name_raw: str, skins: list[dict], dry_run: bool):
    """Merge skins into the global output/manifest.json."""
    manifest_path = OUTPUT_DIR / "manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception:
        data = {}

    data.setdefault("meta", {"tool": "s2-skin-screenshotter"})
    data["meta"]["last_updated"] = time.strftime("%Y-%m-%d")
    # gods/skins/prisms are all dicts keyed by name (order-independent merging)
    if isinstance(data.get("gods"), list):
        data["gods"] = {g["name"]: {"skins": g.get("skins", [])} for g in data["gods"]}
    data.setdefault("gods", {})

    god_key = make_id(god_name_raw)
    god_entry = data["gods"].setdefault(god_key, {"skins": {}})
    if isinstance(god_entry.get("skins"), list):
        god_entry["skins"] = {
            s["file"].removesuffix(".webp"): dict(
                s, prisms={p["file"].removesuffix(".webp"): p for p in s.get("prisms", [])}
                if isinstance(s.get("prisms"), list) else s.get("prisms", {})
            )
            for s in god_entry["skins"]
        }
    for skin in skins:
        skin_key = skin["file"].removesuffix(".webp")
        god_entry["skins"][skin_key] = skin

    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Manifest → {manifest_path}")


def process_current_god(dry_run: bool = False, no_spin: bool = False):
    _init_manifest(dry_run)
    run_start = time.monotonic()

    card_centers = visible_card_centers()
    print(f"Grid geometry: {len(card_centers)} card slots visible per page "
          f"({CARD_W}×{CARD_H}px, gap {GAP_X}px, {COLUMNS} cols), "
          f"scrolling via scrollbar ({ROWS_PER_SCROLL} rows per step)")

    print("\nDetecting scroll mode...")
    scrollable = detect_scrollable()

    print("Scrolling grid to top...")
    scroll_grid_to_top()

    # Ensure the first skin is freshly selected before we start capturing.
    # If skin 1 was already active when we arrived, clicking it again does nothing
    # and idle animations may have started. Clicking skin 2 → skin 1 forces a reload.
    c1x, c1y = card_centers[0]
    c2x, c2y = card_centers[1]
    click_at(c2x, c2y, delay=DELAYS["after_skin_select"])
    click_at(c1x, c1y, delay=DELAYS["after_skin_select"])

    saved = 0
    skipped = 0
    page = 0
    god_name_raw = "unknown"
    god_skins: list[dict] = []

    while True:
        for cx, cy in card_centers:
            # Hover first to let the OS cursor update, then check if it's the
            # hand cursor. Arrow cursor = empty padding slot → skip it.
            pyautogui.moveTo(cx, cy, duration=0.1)
            time.sleep(0.1)
            if HAS_WIN32 and not cursor_is_hand():
                print(f"  skip  slot ({cx},{cy}) — no card (arrow cursor)")
                continue

            click_at(cx, cy, delay=DELAYS["after_skin_select"])

            god_name_raw = ocr(REGIONS["god_name"]).strip()
            skin_name_raw = ocr(REGIONS["skin_name"]).strip()

            if not god_name_raw:
                print(f"  warn  OCR returned empty god name at ({cx},{cy}) — skipping skin")
                continue
            if not skin_name_raw:
                print(f"  warn  OCR returned empty skin name at ({cx},{cy}) — skipping skin")
                continue

            _cur, total_prisms = get_prism_info()

            # Track files written for this skin. On Ctrl+C we delete them so
            # the next run starts fresh rather than finding a partial capture.
            _skin_files: list[Path] = []
            try:
                if total_prisms > 0:
                    # Prism 1/N is the base skin; prisms 2..N are recolors with names
                    # of the form "Base Skin Name - Recolor Name".
                    navigate_to_first_prism()

                    base_name_raw = ocr(REGIONS["skin_name"]).strip()
                    if not base_name_raw:
                        print(f"  warn  OCR returned empty prism base name at ({cx},{cy}) — skipping skin")
                        continue
                    base_slug = make_id(god_name_raw + " " + base_name_raw)
                    base_file = f"{base_slug}.webp"
                    base_spin = f"{base_slug}-spin.webp"
                    _skin_files.append(OUTPUT_DIR / base_file)
                    if not no_spin:
                        _skin_files.append(OUTPUT_DIR / base_spin)
                    s, k = _log_save(save_image(OUTPUT_DIR / base_file, dry_run), base_file,
                                     f"prism 1/{total_prisms}")
                    saved += s; skipped += k
                    if not no_spin:
                        s, k = _log_save(capture_spin_webp(OUTPUT_DIR / base_spin, dry_run), base_spin,
                                         f"spin prism 1/{total_prisms}")
                        saved += s; skipped += k

                    skin_entry: dict = {
                        "name": base_name_raw,
                        "file": base_file,
                        **({} if no_spin else {"spin_file": base_spin}),
                        "prisms": {},
                    }

                    for i in range(2, total_prisms + 1):
                        if REGIONS.get("btn_prism_next"):
                            click_at(*_find_button("btn_prism_next"),
                                     delay=DELAYS.get("after_prism_nav", 0.4))
                        recolor_raw = ocr(REGIONS["skin_name"]).strip()
                        if not recolor_raw:
                            print(f"  warn  OCR returned empty recolor name (prism {i}/{total_prisms}) — skipping recolor")
                            continue
                        recolor_slug = make_id(god_name_raw + " " + recolor_raw)
                        recolor_file = f"{recolor_slug}.webp"
                        recolor_spin = f"{recolor_slug}-spin.webp"
                        _skin_files.append(OUTPUT_DIR / recolor_file)
                        if not no_spin:
                            _skin_files.append(OUTPUT_DIR / recolor_spin)
                        s, k = _log_save(save_image(OUTPUT_DIR / recolor_file, dry_run),
                                         recolor_file, f"prism {i}/{total_prisms}")
                        saved += s; skipped += k
                        if not no_spin:
                            s, k = _log_save(capture_spin_webp(OUTPUT_DIR / recolor_spin, dry_run),
                                             recolor_spin, f"spin prism {i}/{total_prisms}")
                            saved += s; skipped += k

                        skin_entry["prisms"][recolor_slug] = {
                            "name": recolor_raw,
                            "index": i - 1,   # 1-based among recolors
                            "file": recolor_file,
                            **({} if no_spin else {"spin_file": recolor_spin}),
                        }

                    god_skins.append(skin_entry)

                else:
                    slug = make_id(god_name_raw + " " + skin_name_raw)
                    filename = f"{slug}.webp"
                    spin_file = f"{slug}-spin.webp"
                    _skin_files.append(OUTPUT_DIR / filename)
                    if not no_spin:
                        _skin_files.append(OUTPUT_DIR / spin_file)
                    s, k = _log_save(save_image(OUTPUT_DIR / filename, dry_run), filename)
                    saved += s; skipped += k
                    if not no_spin:
                        s, k = _log_save(capture_spin_webp(OUTPUT_DIR / spin_file, dry_run), spin_file,
                                         "spin")
                        saved += s; skipped += k

                    god_skins.append({
                        "name": skin_name_raw,
                        "file": filename,
                        **({} if no_spin else {"spin_file": spin_file}),
                        "prisms": {},
                    })

            except KeyboardInterrupt:
                removed = [f for f in _skin_files if f.exists()]
                for f in removed:
                    f.unlink()
                    print(f"\n  cleanup  {f.name}")
                print("\nInterrupted. Partial files removed. Manifest not updated.")
                raise

        if not scroll_grid_down():
            print("\nReached end of skin grid.")
            break

        page += 1
        print(f"  --- scrolled to page {page + 1} ---")

    _update_manifest(god_name_raw, god_skins, dry_run)
    elapsed = time.monotonic() - run_start
    print(f"\nDone. saved={saved} skipped={skipped}  ({_fmt_elapsed(elapsed)})")


def process_all_gods(dry_run: bool = False, no_spin: bool = False):
    """Iterate every god by repeatedly clicking btn_next_god, stopping when we
    see a god name we've already processed (handles the wrap-around)."""
    if not REGIONS.get("btn_next_god"):
        print("btn_next_god not configured — processing current god only.")
        process_current_god(dry_run=dry_run, no_spin=no_spin)
        return

    start_god: str | None = None
    god_number = 0
    all_start = time.monotonic()

    while True:
        current_god = ocr(REGIONS["god_name"]).strip() or "unknown"

        if start_god is None:
            # Record the god we started on; stop when we return to it.
            start_god = current_god
        elif current_god == start_god:
            print(f"\nWrapped back to {start_god!r} — full roster processed.")
            break

        god_number += 1
        print(f"\n{'='*60}")
        print(f"God {god_number}: {current_god}  (total elapsed: {_fmt_elapsed(time.monotonic() - all_start)})")
        print(f"{'='*60}")

        god_start = time.monotonic()
        process_current_god(dry_run=dry_run, no_spin=no_spin)
        print(f"  → {current_god} finished in {_fmt_elapsed(time.monotonic() - god_start)}")

        # Advance to the next god
        print(f"\nAdvancing to next god...")
        click_at(*region_center(REGIONS["btn_next_god"]),
                 delay=DELAYS.get("after_god_select", 1.5))

    total = _fmt_elapsed(time.monotonic() - all_start)
    print(f"\nAll done. Processed {god_number} god(s) in {total}.")


def focus_smite_window() -> bool:
    """Focus the Smite 2 window. Returns True on success or if pywin32 unavailable, False if not found."""
    if not HAS_WIN32:
        print("Warning: pywin32 not available, cannot verify game window.")
        return True
    results = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and "smite 2" in win32gui.GetWindowText(hwnd).lower():
            results.append(hwnd)
    win32gui.EnumWindows(cb, None)
    if not results:
        print("Error: Smite 2 window not found. Launch the game and try again.")
        return False
    win32gui.ShowWindow(results[0], win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(results[0])
    time.sleep(0.5)  # let the window come to front before any input
    return True


if __name__ == "__main__":
    import sys
    import argparse
    p = argparse.ArgumentParser(
        description="Capture skin screenshots and animations from Smite 2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Navigate to a god's skin screen in-game before running.",
    )
    p.add_argument("--all-gods", action="store_true",
                   help="Iterate the full god roster automatically")
    p.add_argument("--no-spin",  action="store_true",
                   help="Skip animated WebP captures (static screenshots only)")
    p.add_argument("--dry-run",  action="store_true",
                   help="Print what would be saved without writing any files")
    args = p.parse_args()

    if args.dry_run:
        print("DRY RUN — no files will be written.\n")
    if args.no_spin:
        print("NO SPIN — animated WebPs will be skipped.\n")

    if not focus_smite_window():
        sys.exit(1)

    try:
        if args.all_gods:
            process_all_gods(dry_run=args.dry_run, no_spin=args.no_spin)
        else:
            process_current_god(dry_run=args.dry_run, no_spin=args.no_spin)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
