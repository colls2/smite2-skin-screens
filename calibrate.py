# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pillow",
#   "pywin32",
#   "pyyaml",
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
    ("grid_area",   "Scrollable skin card grid — draw around the entire grid container"),
    ("first_card",  "First card in the grid (top-left) — used for card size"),
    # _second_card is a calibration-only helper: used to compute gap_x/gap_y, not saved
    ("_second_card", "Card immediately to the RIGHT of the first — used to compute card gap"),
]

# Keys prefixed with _ are calibration helpers: not written to regions in config
_HELPER_KEYS = {"_second_card"}

COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6"]


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8")


def focus_smite_window():
    if not HAS_WIN32:
        return
    results = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and "smite 2" in win32gui.GetWindowText(hwnd).lower():
            results.append(hwnd)
    win32gui.EnumWindows(cb, None)
    if results:
        win32gui.ShowWindow(results[0], win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(results[0])
        time.sleep(0.3)


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

        # Scale down if the screenshot is very large so it fits on screen
        sw, sh = screenshot.size
        max_w, max_h = 1600, 900
        scale = min(max_w / sw, max_h / sh, 1.0)
        self.scale = scale
        display_w = int(sw * scale)
        display_h = int(sh * scale)
        display_img = screenshot.resize((display_w, display_h), Image.LANCZOS)

        self.root = tk.Tk()
        self.root.title("Region Calibration")
        self.root.resizable(False, False)

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

        self._update_prompt()

    def _draw_existing_regions(self):
        for i, (key, _) in enumerate(self.regions_order):
            if key in _HELPER_KEYS:
                continue
            region = self.results.get(key, [0, 0, 0, 0])
            if region and any(v != 0 for v in region):
                l, t, w, h = region
                x1 = int(l * self.scale)
                y1 = int(t * self.scale)
                x2 = int((l + w) * self.scale)
                y2 = int((t + h) * self.scale)
                color = COLORS[i % len(COLORS)]
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, dash=(4, 2))
                self.canvas.create_text(x1 + 4, y1 + 4, anchor="nw", text=key,
                                        fill=color, font=("Segoe UI", 9, "bold"))

    def _update_prompt(self):
        if self.index >= len(self.regions_order):
            self.status_var.set("All regions done! Close this window to save.")
            return
        key, label = self.regions_order[self.index]
        color = COLORS[self.index % len(COLORS)]
        self.status_var.set(
            f"[{self.index + 1}/{len(self.regions_order)}]  Draw: {label}  (key: {key})  "
            f"| Right-click to skip"
        )
        self.canvas.config(highlightbackground=color, highlightthickness=3)

    def _on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.dragging = True

    def _on_drag(self, event):
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
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        # Convert back to real pixel coordinates
        s = self.scale
        real = [int(x1 / s), int(y1 / s), int((x2 - x1) / s), int((y2 - y1) / s)]

        key, _ = self.regions_order[self.index]
        self.results[key] = real
        print(f"  {key}: {real}")

        # Lock in the drawn rect with a label
        color = COLORS[self.index % len(COLORS)]
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

    def run(self) -> dict:
        self.root.mainloop()
        return self.results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Focusing Smite 2 window...")
    focus_smite_window()

    print("Taking screenshot...")
    screenshot = take_screenshot()
    print(f"  Screen size: {screenshot.size}")

    cfg = load_config()
    existing_regions = cfg.get("regions", {r: [0, 0, 0, 0] for r, _ in REGIONS_ORDER
                                             if r not in _HELPER_KEYS})

    print("\nOpening calibration window.")
    print("  Left-drag  → define region")
    print("  Right-click → skip (keep current value)\n")

    calibrator = Calibrator(screenshot, REGIONS_ORDER, existing_regions)
    raw = calibrator.run()

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

    # Strip helper keys before saving regions
    cfg["regions"] = {k: v for k, v in raw.items() if k not in _HELPER_KEYS}

    save_config(cfg)
    print(f"Saved to {CONFIG_PATH}")
