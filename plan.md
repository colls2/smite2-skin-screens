# Smite 2 Skin Screenshotter — Task Plan

## Phase 1: Setup & Foundations

- [x] ~~Initialize Python project with `pyproject.toml` or `requirements.txt`~~ — using uv inline script deps instead
- [x] Verify pyautogui can detect and focus the Smite 2 game window on Windows — `find_window.py`
- [x] Create a config file (`config.yaml` or similar) to store screen region coordinates, paths, delays, and other tunables
- [x] Write a small utility to capture and save a full screenshot — done in Phase 0 (`check_deps.py`)

## Phase 2: Region Calibration

- [x] Manually identify and document the screen regions of interest (`calibrate.py`):
    - God name text area
    - Skin name / details panel
    - Model view (3D model display, changes on card click)
    - Grid area + first card (card size + gap for grid math)
    - Next/prev god buttons
- [x] Store all region coordinates in the config file with clear labels
- [x] Write a calibration helper script that draws overlays (colored rectangles) on a screenshot so regions can be visually verified and adjusted — `calibrate.py`

## Phase 3: UI Navigation

- [ ] Write a function to click a screen coordinate with a configurable delay (to let the UI settle after each click)
- [ ] Write a function to navigate to the god selection / loadout screen from the main menu
- [ ] Write a function to cycle through all gods (detect end-of-list or iterate a known count)
- [ ] Write a function to cycle through all skins for the currently selected god
- [ ] Add waits/polling to confirm the UI has finished animating before proceeding (compare successive screenshots or wait a fixed delay)

## Phase 4: Name Extraction (OCR)

- [ ] Integrate pytesseract; write a function that crops a region and returns cleaned OCR text
- [ ] Test OCR accuracy on the god name region and skin name region
- [ ] Add post-processing to sanitize OCR output into valid filenames (strip special chars, normalize spaces, handle misreads)
- [ ] Build a mapping/lookup for known god names to correct common OCR errors (optional fuzzy matching with rapidfuzz)

## Phase 5: Screenshot Capture & Storage

- [ ] Write a function to capture a specific screen region and return a Pillow image
- [ ] Decide on output folder structure: e.g. `output/<GodName>/<SkinName>.png`
- [ ] Write a function to save a captured image using the OCR-derived name, with collision handling (skip if exists, or overwrite with flag)
- [ ] Add a dry-run mode that logs what would be saved without writing files

## Phase 6: Main Automation Loop

- [ ] Wire everything together: for each god → for each skin → OCR names → capture region → save file
- [ ] Add progress logging (current god, skin, files written)
- [ ] Add resume support: skip gods/skins whose output file already exists
- [ ] Handle edge cases: default skin, locked skins, loading screens, unexpected popups

## Phase 7: QA & Hardening

- [ ] Run a full pass and manually review output images and filenames for accuracy
- [ ] Fix any systematic OCR errors by tuning preprocessing (contrast, scale, binarization)
- [ ] Add retry logic for navigation steps that sometimes fail silently
- [ ] Write a validation script that checks output folder for missing gods/skins against a known list

## Phase 8: Extensions (future)

- [ ] Capture additional regions per skin (e.g. card art, loading screen splash, in-game ability icons)
- [ ] Scrape or maintain a manifest of all gods + skins with metadata (release date, rarity, set)
- [ ] Upload images to the wiki automatically via wiki API (MediaWiki API or SMW)
- [ ] Upload images to an image host or S3 bucket as an alternative
- [ ] GUI or CLI with flags (`--god "Anubis"`, `--overwrite`, `--dry-run`)
- [ ] Diff mode: detect newly added skins since last run and only capture those
- [ ] **Animated capture** — record a short clip per skin instead of (or in addition to) a static screenshot:
    - Option A: 5-second screen recording of the model view → animated WebP or GIF
    - Option B: click-drag to rotate the model (front → side → back sweep), record ~2s → animated WebP
    - Animated WebP preferred over GIF (smaller, supports transparency, wiki-compatible)

## Before production run

- [ ] Increase `after_skin_select` in `config.yaml` from `0.5`s to `3.0`s so the 3D model has time to fully load before the screenshot is taken
