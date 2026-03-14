# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pillow",
#   "pywin32",
#   "pyyaml",
#   "pyautogui",
# ]
# ///

"""
Interactive region calibration tool.

Focuses the Smite 2 window, takes a screenshot, then lets you drag rectangles
to define each region of interest. Results are written to config.yaml.

Run with: uv run calibrate.py
Controls:
  - Click and drag to draw a region
  - Right-click to skip the current region (keep existing value)
  - Regions are prompted one at a time in order
"""

import sys
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw
import yaml
import time
import pyautogui

# ── win32 imports (optional; graceful fallback if game not running) ──────────
try:
    import win32gui, win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

CONFIG_PATH = Path("config.yaml")

REGIONS_ORDER = [
    ("god_name",    "God name text area"),
    ("skin_name",   "Skin name / details panel (updates when a card is clicked)"),
    ("model_view",  "3D model display area (updates when a card is clicked)"),
    ("btn_next_god", "Next-god button"),
    ("btn_prev_god", "Previous-god button"),
    ("grid_area",      "Scrollable skin card grid — draw around the entire grid container"),
    ("scrollbar_track", "Scrollbar track — the thin vertical strip on the right edge of the grid (full height, thumb+track)"),
    ("first_card",     "First card in the grid (top-left) — used for card size"),
    # _second_card is a calibration-only helper: used to compute gap_x/gap_y, not saved
    ("_second_card", "Card immediately to the RIGHT of the first — used to compute card gap"),
    # Prism navigation — only visible in the skin details panel when a skin has prism recolors
    ("prism_counter",  "Prism counter — the 'X / Y' text between the ◄ ► arrows (bottom of skin panel)"),
    ("btn_prism_prev", "Prism ◄ button — left arrow to go to previous prism"),
    ("btn_prism_next", "Prism ► button — right arrow to go to next prism"),
    # Point keys — single click to set, saved at top level of config (not inside regions)
    ("mouse_park",  "Mouse park — click anywhere OUTSIDE the model view; cursor hides here during captures"),
]

# Keys prefixed with _ are calibration helpers: not written to regions in config
_HELPER_KEYS = {"_second_card"}
# Point keys: single click (not drag), saved as [x, y] at top level of config
_POINT_KEYS = {"mouse_park"}

COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6"]


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8")


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
    time.sleep(0.3)
    return True


def take_screenshot() -> Image.Image:
    from PIL import ImageGrab
    return ImageGrab.grab()


# ── Calibration UI ────────────────────────────────────────────────────────────

class Calibrator:
    def __init__(self, screenshot: Image.Image, regions_order: list, existing: dict):
        self.screenshot = screenshot
        self.regions_order = regions_order
        self.existing = existing  # current config regions dict
        self.results = dict(existing)  # will be updated in-place

        self.index = 0
        self.start_x = self.start_y = 0
        self.rect_id = None
        self.dragging = False

        # Scale the screenshot to fill as much of the screen as possible
        sw, sh = screenshot.size
        tmp = tk.Tk(); tmp.withdraw()
        max_w = tmp.winfo_screenwidth() - 20
        # Reserve space for: title bar (~30), status bar (~30), button bar (~44), taskbar (~48) + extra
        max_h = tmp.winfo_screenheight() - 210
        tmp.destroy()
        scale = min(max_w / sw, max_h / sh, 1.0)
        self.scale = scale
        display_w = int(sw * scale)
        display_h = int(sh * scale)
        display_img = screenshot.resize((display_w, display_h), Image.LANCZOS)

        self.saved = False

        self.root = tk.Tk()
        self.root.title("Region Calibration")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_discard)

        # Status bar
        self.status_var = tk.StringVar()
        status = tk.Label(self.root, textvariable=self.status_var, anchor="w",
                          font=("Segoe UI", 11), bg="#2c2c2c", fg="white", padx=8, pady=4)
        status.pack(fill="x", side="top")

        # Canvas
        self.canvas = tk.Canvas(self.root, width=display_w, height=display_h, cursor="crosshair")
        self.canvas.pack()

        self.tk_img = ImageTk.PhotoImage(display_img)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)

        # Draw already-configured regions as semi-transparent overlays
        self._draw_existing_regions()

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-3>", self._on_skip)

        # Button bar
        btn_bar = tk.Frame(self.root, bg="#1e1e1e", pady=6)
        btn_bar.pack(fill="x", side="bottom")
        tk.Button(btn_bar, text="Save & Close", command=self._on_save,
                  bg="#27ae60", fg="white", font=("Segoe UI", 10, "bold"),
                  padx=16, pady=4, relief="flat", cursor="hand2").pack(side="right", padx=8)
        tk.Button(btn_bar, text="Discard & Close", command=self._on_discard,
                  bg="#c0392b", fg="white", font=("Segoe UI", 10),
                  padx=16, pady=4, relief="flat", cursor="hand2").pack(side="right", padx=0)

        self._update_prompt()

    def _draw_existing_regions(self):
        for i, (key, _) in enumerate(self.regions_order):
            if key in _HELPER_KEYS:
                continue
            color = COLORS[i % len(COLORS)]
            if key in _POINT_KEYS:
                pt = self.results.get(key)
                if pt and len(pt) == 2 and any(v != 0 for v in pt):
                    px = int(pt[0] * self.scale)
                    py = int(pt[1] * self.scale)
                    r = 6
                    self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                            outline=color, width=2, dash=(4, 2))
                    self.canvas.create_line(px - r - 4, py, px + r + 4, py, fill=color, width=1)
                    self.canvas.create_line(px, py - r - 4, px, py + r + 4, fill=color, width=1)
                    self.canvas.create_text(px + r + 4, py, anchor="w", text=key,
                                            fill=color, font=("Segoe UI", 9, "bold"))
            else:
                region = self.results.get(key, [0, 0, 0, 0])
                if region and any(v != 0 for v in region):
                    l, t, w, h = region
                    x1 = int(l * self.scale)
                    y1 = int(t * self.scale)
                    x2 = int((l + w) * self.scale)
                    y2 = int((t + h) * self.scale)
                    self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, dash=(4, 2))
                    self.canvas.create_text(x1 + 4, y1 + 4, anchor="nw", text=key,
                                            fill=color, font=("Segoe UI", 9, "bold"))

    def _on_save(self):
        self.saved = True
        self.root.destroy()

    def _on_discard(self):
        self.saved = False
        self.root.destroy()

    def _update_prompt(self):
        if self.index >= len(self.regions_order):
            self.status_var.set("All regions done! Click 'Save & Close' to write config.yaml.")
            return
        key, label = self.regions_order[self.index]
        color = COLORS[self.index % len(COLORS)]
        action = "Click" if key in _POINT_KEYS else "Draw"
        self.status_var.set(
            f"[{self.index + 1}/{len(self.regions_order)}]  {action}: {label}  (key: {key})  "
            f"| Right-click to skip"
        )
        self.canvas.config(highlightbackground=color, highlightthickness=3)

    def _on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.dragging = True

    def _on_drag(self, event):
        if self.index >= len(self.regions_order):
            return
        key, _ = self.regions_order[self.index]
        if key in _POINT_KEYS:
            return  # no rubber-band for point keys
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        color = COLORS[self.index % len(COLORS)]
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline=color, width=2
        )

    def _on_release(self, event):
        if not self.dragging or self.index >= len(self.regions_order):
            return
        self.dragging = False

        key, _ = self.regions_order[self.index]
        color = COLORS[self.index % len(COLORS)]
        s = self.scale

        if key in _POINT_KEYS:
            # Single-click point: use the press position
            px, py = self.start_x, self.start_y
            real = [int(px / s), int(py / s)]
            self.results[key] = real
            print(f"  {key}: {real}")
            r = 6
            self.canvas.create_oval(px - r, py - r, px + r, py + r, outline=color, width=2)
            self.canvas.create_line(px - r - 4, py, px + r + 4, py, fill=color, width=1)
            self.canvas.create_line(px, py - r - 4, px, py + r + 4, fill=color, width=1)
            self.canvas.create_text(px + r + 4, py, anchor="w", text=key,
                                    fill=color, font=("Segoe UI", 9, "bold"))
        else:
            x1 = min(self.start_x, event.x)
            y1 = min(self.start_y, event.y)
            x2 = max(self.start_x, event.x)
            y2 = max(self.start_y, event.y)
            real = [int(x1 / s), int(y1 / s), int((x2 - x1) / s), int((y2 - y1) / s)]
            self.results[key] = real
            print(f"  {key}: {real}")
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2)
            self.canvas.create_text(x1 + 4, y1 + 4, anchor="nw", text=key,
                                    fill=color, font=("Segoe UI", 9, "bold"))

        self.index += 1
        self._update_prompt()

    def _on_skip(self, _event):
        if self.index >= len(self.regions_order):
            return
        key, _ = self.regions_order[self.index]
        print(f"  {key}: skipped (keeping existing: {self.results.get(key)})")
        self.index += 1
        self._update_prompt()

    def run(self) -> dict | None:
        """Run the calibration UI. Returns results dict if saved, None if discarded."""
        self.root.mainloop()
        return self.results if self.saved else None


# ── Spin calibration ──────────────────────────────────────────────────────────

def _show_comparison(before: Image.Image, after: Image.Image, drag_px: int, duration: float):
    """Show before/after model frames side by side in a blocking tkinter window."""
    pad = 8
    label_h = 28
    thumb_w = min(before.width, 600)
    scale = thumb_w / before.width
    thumb_h = int(before.height * scale)

    win_w = thumb_w * 2 + pad * 3
    win_h = thumb_h + label_h + pad * 2

    root = tk.Tk()
    root.title(f"Spin test — drag_px={drag_px}  duration={duration:.1f}s")
    root.resizable(False, False)
    root.configure(bg="#1e1e1e")

    b_img = ImageTk.PhotoImage(before.resize((thumb_w, thumb_h), Image.LANCZOS))
    a_img = ImageTk.PhotoImage(after.resize((thumb_w, thumb_h), Image.LANCZOS))

    tk.Label(root, text="BEFORE", fg="#aaaaaa", bg="#1e1e1e",
             font=("Segoe UI", 10, "bold")).place(x=pad, y=pad)
    tk.Label(root, text="AFTER (should match if 360°)", fg="#aaaaaa", bg="#1e1e1e",
             font=("Segoe UI", 10, "bold")).place(x=thumb_w + pad * 2, y=pad)

    tk.Label(root, image=b_img, bg="#1e1e1e").place(x=pad, y=label_h + pad)
    tk.Label(root, image=a_img, bg="#1e1e1e").place(x=thumb_w + pad * 2, y=label_h + pad)

    root.geometry(f"{win_w}x{win_h}")
    root.mainloop()


def calibrate_spin():
    """Interactive spin calibration: drag the model, compare before/after, tune until 360°."""
    cfg = load_config()
    model_view = cfg.get("regions", {}).get("model_view")
    if not model_view:
        print("Error: model_view region not set. Run calibrate.py (without --spin) first.")
        sys.exit(1)

    l, t, w, h = model_view
    cx = l + w // 2
    cy = t + h // 2

    drag_px  = cfg.get("spin_drag_px",    800)
    duration = cfg.get("spin_duration_s", 3.0)

    print("\nSpin calibration")
    print("  Drags the model right, then checks if the pose matches the start (= 360°).")
    print("  Adjust drag_px and duration until BEFORE and AFTER look the same.\n")
    print(f"  model_view center: ({cx}, {cy})")

    while True:
        print(f"\n  Current: drag_px={drag_px}  duration={duration:.1f}s")
        print("  Commands:  t=test   p=set drag_px   d=set duration   s=save & quit   q=quit")
        cmd = input("  > ").strip().lower()

        if cmd == "q":
            break

        elif cmd == "s":
            cfg["spin_drag_px"]    = drag_px
            cfg["spin_duration_s"] = duration
            save_config(cfg)
            print(f"  Saved: spin_drag_px={drag_px}  spin_duration_s={duration:.1f}s  → {CONFIG_PATH}")
            break

        elif cmd == "p":
            try:
                drag_px = int(input("  New drag_px: ").strip())
            except ValueError:
                print("  Invalid number.")

        elif cmd == "d":
            try:
                duration = float(input("  New duration (seconds): ").strip())
            except ValueError:
                print("  Invalid number.")

        elif cmd == "t":
            print(f"  Focusing game in 2 seconds — don't touch the mouse...")
            time.sleep(2)
            if not focus_smite_window():
                print("  Skipping test — launch the game first.")
                continue
            time.sleep(0.5)

            from PIL import ImageGrab
            park = cfg.get("mouse_park")
            if park:
                pyautogui.moveTo(park[0], park[1], duration=0.1)
                time.sleep(0.1)
            before = ImageGrab.grab(bbox=(l, t, l + w, t + h))

            print(f"  Dragging {drag_px}px over {duration:.1f}s ...")
            pyautogui.mouseDown(cx, cy, button="left")
            pyautogui.moveRel(drag_px, 0, duration=duration)
            pyautogui.mouseUp()
            time.sleep(0.3)
            if park:
                pyautogui.moveTo(park[0], park[1], duration=0.1)
                time.sleep(0.1)
            after = ImageGrab.grab(bbox=(l, t, l + w, t + h))

            # Drag back to restore start pose (important so repeated tests start from same position)
            pyautogui.mouseDown(cx, cy, button="left")
            pyautogui.moveRel(-drag_px, 0, duration=duration)
            pyautogui.mouseUp()
            time.sleep(0.3)

            print("  Opening comparison window (close it to continue)...")
            _show_comparison(before, after, drag_px, duration)

        else:
            print("  Unknown command.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Calibrate screen regions for the Smite 2 skin screenshotter.",
        epilog="Run without flags to calibrate regions. Use --spin to tune the rotation animation.",
    )
    p.add_argument("--spin", action="store_true",
                   help="Calibrate spin animation drag distance and duration")
    args = p.parse_args()

    if args.spin:
        calibrate_spin()
        sys.exit(0)

    print("Focusing Smite 2 window...")
    if not focus_smite_window():
        sys.exit(1)

    print("Taking screenshot...")
    screenshot = take_screenshot()
    print(f"  Screen size: {screenshot.size}")

    cfg = load_config()
    # Seed existing values: region keys from cfg["regions"], point keys from cfg top level
    existing = {r: [0, 0, 0, 0] for r, _ in REGIONS_ORDER
                if r not in _HELPER_KEYS and r not in _POINT_KEYS}
    existing.update(cfg.get("regions", {}))
    for key in _POINT_KEYS:
        if key in cfg:
            existing[key] = cfg[key]

    print("\nOpening calibration window.")
    print("  Left-drag   → define region")
    print("  Left-click  → set point (for click-type entries)")
    print("  Right-click → skip (keep current value)\n")

    calibrator = Calibrator(screenshot, REGIONS_ORDER, existing)
    raw = calibrator.run()

    if raw is None:
        print("\nDiscarded — config.yaml not changed.")
        sys.exit(0)

    # Compute gap from first_card and _second_card if both were drawn
    first  = raw.get("first_card",   [0, 0, 0, 0])
    second = raw.get("_second_card", [0, 0, 0, 0])
    if any(v != 0 for v in first) and any(v != 0 for v in second):
        gap_x = second[0] - (first[0] + first[2])
        gap_y = gap_x  # assume uniform grid; user can adjust manually
        cfg.setdefault("grid", {})
        cfg["grid"]["gap_x"] = gap_x
        cfg["grid"]["gap_y"] = gap_y
        print(f"\nComputed card gap: gap_x={gap_x}px, gap_y={gap_y}px (assumed equal)")
    else:
        print("\nSkipped gap computation (first_card or _second_card not drawn).")

    # Region keys go into cfg["regions"]; point keys go at top level of cfg
    cfg["regions"] = {k: v for k, v in raw.items()
                      if k not in _HELPER_KEYS and k not in _POINT_KEYS}
    for key in _POINT_KEYS:
        if key in raw:
            cfg[key] = raw[key]

    save_config(cfg)
    print(f"Saved to {CONFIG_PATH}")

    # Save grayscale template crops for buttons that benefit from template matching
    _TEMPLATE_BUTTON_KEYS = {"btn_prism_prev", "btn_prism_next"}
    for key in _TEMPLATE_BUTTON_KEYS:
        region = raw.get(key, [0, 0, 0, 0])
        if region and any(v != 0 for v in region):
            l, t, w, h = region
            crop = screenshot.crop((l, t, l + w, t + h)).convert("L")
            tmpl_path = CONFIG_PATH.parent / f"{key}_template.png"
            crop.save(str(tmpl_path))
            print(f"  saved template: {tmpl_path.name}")
