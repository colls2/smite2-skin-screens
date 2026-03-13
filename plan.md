# Smite 2 Skin Screenshotter — Task Plan

## Phase 1: Setup & Foundations

- [ ] Initialize Python project with `pyproject.toml` or `requirements.txt` (pyautogui, pillow, pytesseract, opencv-python)
- [ ] Verify pyautogui can detect and focus the Smite 2 game window on Windows
- [ ] Create a config file (`config.yaml` or similar) to store screen region coordinates, paths, delays, and other tunables
- [ ] Write a small utility to capture and save a full screenshot — smoke test that screen capture works

## Phase 2: Region Calibration

- [ ] Manually identify and document the screen regions of interest:
    - God name text area
    - Skin name text area
    - Skin card/portrait area (the region to screenshot for the wiki)
    - Navigation buttons (next god, next skin, confirm, etc.)
- [ ] Store all region coordinates in the config file with clear labels
- [ ] Write a calibration helper script that draws overlays (colored rectangles) on a screenshot so regions can be visually verified and adjusted

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
