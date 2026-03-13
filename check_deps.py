# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyautogui",
#   "pillow",
#   "pytesseract",
#   "opencv-python",
#   "rapidfuzz",
#   "pyyaml",
# ]
# ///

"""
Smoke test: verify all project dependencies import and show basic info.
Run with: uv run check_deps.py
"""

import sys


def check(label: str, fn):
    try:
        result = fn()
        print(f"  [OK] {label}: {result}")
    except Exception as e:
        print(f"  [FAIL] {label}: {e}")


print(f"Python {sys.version}\n")
print("Checking dependencies...")

check("Pillow", lambda: __import__("PIL").__version__)
check("pyautogui", lambda: __import__("pyautogui").__version__)
check("pytesseract", lambda: __import__("pytesseract").get_tesseract_version())
check("opencv-python", lambda: __import__("cv2").__version__)
check("rapidfuzz", lambda: __import__("rapidfuzz").__version__)
check("pyyaml", lambda: __import__("yaml").__version__)

print("\nScreenshot test...")
check(
    "PIL.ImageGrab screenshot",
    lambda: __import__("PIL.ImageGrab", fromlist=["ImageGrab"]).ImageGrab.grab().size,
)

print("\nDone.")
