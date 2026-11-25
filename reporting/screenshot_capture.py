"""Screenshot evidence helpers (supporting evidence only — never a data-validation source).

- Page screenshots are captured by the Playwright driver during live extraction.
- ``crop_visual`` cuts an approximate visual region using the VisualDescriptor layout
  (x/y/width/height in report coordinates scaled to the rendered container). This is
  approximate: page scaling/zoom can shift regions, so crops are labelled approximate.
- ``ocr_text`` uses Tesseract via pytesseract if both are installed (optional).
- Pixel comparison is intentionally NOT used to decide data mismatches.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PIL import Image


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def crop_visual(page_png: Path, layout: dict, page_size: tuple[int, int] | None, out: Path) -> Path | None:
    """Crop a visual region. ``page_size`` is the report page's logical size (defaultSize)."""
    if not layout or not all(k in layout for k in ("x", "y", "width", "height")):
        return None
    with Image.open(page_png) as img:
        sx = img.width / page_size[0] if page_size else 1.0
        sy = img.height / page_size[1] if page_size else 1.0
        box = (int(layout["x"] * sx), int(layout["y"] * sy),
               int((layout["x"] + layout["width"]) * sx), int((layout["y"] + layout["height"]) * sy))
        box = (max(0, box[0]), max(0, box[1]), min(img.width, box[2]), min(img.height, box[3]))
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        img.crop(box).save(out)
    return out


def ocr_text(image_path: Path) -> str | None:
    """Optional OCR. Returns None when pytesseract/Tesseract are not installed."""
    try:
        import pytesseract  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(image_path) as img:
            return pytesseract.image_to_string(img)
    except Exception:
        return None


def cleanup_old(directory: Path, max_age_days: int) -> int:
    """Retention policy: delete PNGs older than ``max_age_days``."""
    if not directory.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    n = 0
    for p in directory.glob("*.png"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            n += 1
    return n
