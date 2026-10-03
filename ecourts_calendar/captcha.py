"""Captcha solving: offline OCR (ddddocr) with a fallback to asking you in the terminal."""
import re
import sys

from . import config

_ocr = None
# Only the `sync` CLI command asks you in the terminal; scheduled runs never block on input.
INTERACTIVE = False


def _ocr_solve(image_bytes):
    global _ocr
    try:
        import ddddocr
    except ImportError:
        return None
    if _ocr is None:
        _ocr = ddddocr.DdddOcr(show_ad=False)
    text = _ocr.classification(image_bytes) or ""
    return re.sub(r"[^0-9A-Za-z]", "", text) or None


def _ask_user(image_path):
    if not (INTERACTIVE and sys.stdin.isatty()):
        return None
    print(f"\nCaptcha image saved to: {image_path}")
    return input("Type the captcha you see (blank to skip): ").strip() or None


def solve(image_bytes, attempt):
    """Return captcha text, or None if it can't be solved this attempt."""
    config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    image_path = config.DEBUG_DIR / f"captcha_attempt{attempt}.png"
    image_path.write_bytes(image_bytes)

    if config.CAPTCHA_MODE in ("auto", "ocr"):
        text = _ocr_solve(image_bytes)
        if text:
            return text
    if config.CAPTCHA_MODE in ("auto", "manual"):
        return _ask_user(image_path)
    return None
