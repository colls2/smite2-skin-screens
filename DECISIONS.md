# Architecture Decision Records

## ADR-001: Python as the implementation language

**Decision:** Use Python 3.11+.

**Reasons:**
- Strong ecosystem for screen automation (pyautogui), image processing (Pillow, OpenCV), and OCR (pytesseract)
- Fast iteration for a scripting/automation tool

---

## ADR-002: uv for dependency management and script execution

**Decision:** Use [uv](https://docs.astral.sh/uv/) instead of pip/virtualenv/poetry.

**Reasons:**
- Single tool for both dependency management and running scripts
- Supports PEP 723 inline script metadata (`# /// script ... ///`), letting scripts declare their own deps and be run with `uv run script.py` without manual venv setup
- Fast and reproducible

---

## ADR-003: pyautogui for screen automation

**Decision:** Use pyautogui for mouse clicks and keyboard input.

**Reasons:**
- Simple cross-platform API
- Sufficient for clicking through a game UI at human-like speeds
- Pairs well with Pillow for screenshot capture

---

## ADR-004: Pillow for image capture and processing

**Decision:** Use Pillow (PIL) as the primary image library.

**Reasons:**
- Built-in screenshot support via `ImageGrab`
- Easy cropping, saving, and format conversion
- Widely supported and stable

---

## ADR-005: pytesseract + OpenCV for OCR

**Decision:** Use pytesseract (Tesseract wrapper) with OpenCV for preprocessing.

**Reasons:**
- Tesseract is the most accessible open-source OCR engine
- OpenCV allows contrast/threshold tuning to improve accuracy on stylized game fonts
- rapidfuzz can be added later for fuzzy correction against a known god/skin list

---

## ADR-006: Configuration via YAML

**Decision:** Store all tunable values (screen regions, delays, output paths) in a `config.yaml` file.

**Reasons:**
- Easy to edit without touching code
- Regions will need recalibration when game UI changes; keeping them out of code makes that straightforward

---

## ADR-007: Output folder structure

**Decision:** Save images as `output/<GodName>/<SkinName>.png`.

**Reasons:**
- Mirrors the conceptual hierarchy (god → skin)
- Easy to browse, diff, and upload incrementally

---

## Note: Smite 2 UI fonts (from game files via FModel)

Found in `StyleGuide/Fonts`:

| Font | Role |
|------|------|
| **TitanForged** | Display font — god names, skin names. Stylized; most likely to cause OCR errors. |
| **Oswald** | Condensed sans-serif — likely secondary headings. |
| **TrajanPro3 / TrajanasSans** | Serif — decorative headings. |
| **Lato** | Clean sans-serif — UI body text. Tesseract handles well. |
| **NotoSans / NotoSansJapanese** | General-purpose UI text. Tesseract handles well. |

If OCR accuracy on name regions is poor, training a custom Tesseract model on rendered TitanForged samples is the recommended next step (the font files are available from the game assets).
