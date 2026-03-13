# s2-skin-screenshotter

Automates capturing skin screenshots from Smite 2 for use on the community wiki.

The tool navigates the in-game cosmetics UI, reads god and skin names via OCR, and saves cropped screenshots organized by god and skin name.

## Prerequisites

### uv

Install [uv](https://docs.astral.sh/uv/) for Python and dependency management.

### Tesseract OCR

Tesseract is a native binary and must be installed separately.

1. Download the installer from the [UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki) (the official Windows builds) — grab the latest `tesseract-ocr-w64-setup-*.exe`
2. Run the installer; the default path is `C:\Program Files\Tesseract-OCR`
3. Add Tesseract to your PATH:
   - Open Start → search **"Edit the system environment variables"**
   - Click **Environment Variables** → under *System variables* select `Path` → **Edit**
   - Add `C:\Program Files\Tesseract-OCR`
   - Click OK and restart your terminal

## Usage

Run the smoke test to verify all dependencies:

```bash
uv run check_deps.py
```

## Status

Early development — see [plan.md](plan.md) for the task breakdown.

## Copyright

All game assets, images, and content captured by this tool are the property of **Hi-Rez Studios** and **Smite 2**. This tool is a fan-made utility for the community wiki and is not affiliated with or endorsed by Hi-Rez Studios. Screenshots are used under fair use for non-commercial, informational purposes.
