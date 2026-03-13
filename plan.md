# Smite 2 Skin Screenshotter — Task Plan

## Phase 1: Setup & Foundations

- [x] Initialize Python project — using uv inline script deps (PEP 723)
- [x] Verify pyautogui can detect and focus the Smite 2 game window on Windows — `find_window.py`
- [x] Create `config.yaml` for screen region coordinates, delays, and tunables
- [x] Write a small utility to capture and save a full screenshot — `check_deps.py`

## Phase 2: Region Calibration

- [x] Manually identify and document all screen regions of interest (`calibrate.py`):
    - God name text area
    - Skin name / details panel
    - Model view (3D model display)
    - Grid area + first card (card size + gap for grid math)
    - Next/prev god buttons
    - Scrollbar track
    - Prism counter, prev/next prism buttons
- [x] Store all regions in `config.yaml`
- [x] Calibration helper script with colored overlay rectangles — `calibrate.py`
- [x] `mouse_park` point calibration — single click (not drag) in main calibration UI; saved at top level of config; crosshair marker drawn

## Phase 3: UI Navigation

- [x] `click_at(x, y, delay)` with configurable post-click delay
- [x] Cycle through all gods via `btn_next_god` (wraps; stop on first repeat in seen-set)
- [x] Iterate all skin cards in the grid per god, scrolling as needed
- [x] Scroll detection: name-comparison oracle (first card before/after scroll click)
- [x] Scrollability detection: click row 1 vs row 3 top; name change = scrollable
- [x] Cursor detection: hover card slot, check for hand cursor (IDC_HAND) to skip empty slots
- [x] Prism navigation: `get_prism_info()` OCRs X/Y counter; `navigate_to_first_prism()` takes shortest direction (wrapping supported)
- [x] Fresh-skin reset: click card 2 → card 1 before processing each god to force a model reload and prevent idle animation drift
- [ ] **Revisit scroll logic** — grid has a known small number of rows (1–6); could use row-count-aware paging instead of generic scroll-until-no-change (e.g. detect row count once, compute exact scroll steps needed)

## Phase 4: Name Extraction (OCR)

- [x] pytesseract integration with upscale + Otsu threshold preprocessing (`--psm 7`)
- [x] OCR of god name, skin name, prism counter regions
- [x] `make_id()` slug: lowercase, strip non-alphanum, spaces→hyphens, collapse `--+`
- [ ] OCR accuracy pass — TitanForged font may need Tesseract custom training or config tuning
- [ ] Fuzzy matching / known-name correction for common misreads (optional, `rapidfuzz`)

## Phase 5: Screenshot Capture & Storage

- [x] Capture region → Pillow image (`ImageGrab.grab`)
- [x] Output format: flat filenames `make_id(god + " " + skin).webp` in `output/`
- [x] Save as lossy WebP (configurable quality, default 90) via Pillow
- [x] Skip-if-exists (resume support)
- [x] `--dry-run` mode
- [x] `before_screenshot` delay (default 3.0s) so the 3D model fully loads before capture
- [x] Global `output/manifest.json` — initialized with `{meta, gods:[]}` at run start; merged per-god, structured as `{gods: [{name, skins: [{name, file, spin_file, prisms: [{name, index, file, spin_file}]}]}]}`

## Phase 6: Main Automation Loop

- [x] Full loop: all gods → all skins → OCR → prisms → capture → save → manifest
- [x] Progress logging (god name, skin name, save/skip status, scroll mode, prism index)
- [x] `--all-gods` flag to iterate all gods; default processes only the current god
- [ ] Handle edge cases: loading screens, unexpected popups, OCR returning empty string for a skin name

## Phase 7: Animated Capture (WebP)

Smite 2 model viewer rotates on **click + drag** (horizontal drag = rotation). Speed affects rotation amount, so duration must be fixed during calibration.

- [x] **Calibrate rotation drag distance** — `calibrate.py --spin` interactive loop: test drag, compare before/after frames side by side, adjust `drag_px` and `duration`, save to `config.yaml`.
    - Calibrated values: `spin_drag_px: 372`, `spin_duration_s: 3.0`
- [x] **`mouse_park` position** — cursor hides here during still frames and drag starts here (avoids model jump from moving to model center)
- [x] **Implement `capture_spin_webp(dest)`**:
    1. Park mouse; capture `spin_still_s` seconds of still frames (default 2.0s)
    2. `mouseDown` at park position; start frame-capture thread
    3. Single `moveRel(drag_px, 0, duration=spin_dur)` — drag is exactly `spin_dur` seconds; thread captures frames concurrently at `spin_fps` fps
    4. Stop thread; `mouseUp`
    5. Save all frames as animated WebP (`save_all=True`, `append_images`, `duration`, `loop=0`)
    - Threading decouples drag timing from frame-capture overhead, so `spin_duration_s` matches calibration exactly
- [x] **Frame rate** — `spin_fps: 15` (configurable); `ImageGrab` on a ~934×1344px region takes ~15–40ms, leaving headroom at 15fps (67ms/frame). Higher rates are possible but tight.
- [x] **Resolution scaling** — `spin_scale: 0.33` (configurable); frames are resized with LANCZOS before saving to keep file sizes manageable
- [x] **Output both static + animated** per skin:
    - Static: `{slug}.webp` (taken with `before_screenshot` delay, model fully loaded)
    - Animated: `{slug}-spin.webp`
    - Manifest includes both `file` and `spin_file` fields for every skin and prism recolor

## Phase 8: QA & Hardening

- [ ] Full production run — manually review output images and filenames
- [ ] Fix systematic OCR errors (contrast, scale, binarization tuning)
- [ ] Retry logic for navigation steps that fail silently
- [ ] Validation script: check output folder against a known god/skin list for gaps

## Phase 9: Extensions (future)

- [ ] Upload images to the wiki via MediaWiki API
- [ ] Diff mode: detect newly added skins since last run, capture only those
- [ ] Capture additional regions per skin (card art, loading screen splash, ability icons)
- [ ] GUI or richer CLI (`--god "Anubis"`, `--overwrite`, etc.)
