"""OCR layer.

Every supplied policy is a scanned-image PDF (no text layer), so extraction
starts with OCR. We render each page, boost contrast (the fixtures print
de-identified fields like the registration number in a faint grey that plain
OCR drops), then run Tesseract.

Results are cached on disk keyed by file content hash, because OCR is the
slow part of the pipeline and the source PDFs never change.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator

import pdfplumber
import pytesseract
from PIL import Image, ImageEnhance

_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".ocr_cache")
_RESOLUTION = 400

# The scans print fields at different grey levels,
# and no single Tesseract config reads them all. We run several passes and
# concatenate the results so a parser can grep whichever pass captured a field:
#   (contrast, psm)
#   3.0 / 6  - two-column premium tables (label stays on the value's line)
#   3.0 / 3  - faint light-grey de-identified fields (e.g. registration number)
#   1.0 / 3  - mid-grey fields that high contrast erases (e.g. RTO/zone cells)
_PASSES = [(3.0, 6), (3.0, 3), (1.0, 3)]


def _digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:16]


def render_pages(path: str, resolution: int = _RESOLUTION) -> Iterator[Image.Image]:
    """Rasterize PDF pages to PIL images one at a time (page 1 first).

    A generator, not a list: a 400-DPI page is ~45MB, so yielding caps peak
    memory to one page on the 512MB tier and lets an early-stopping caller skip
    the rest.
    """
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            yield pg.to_image(resolution=resolution).original


def page_texts(path: str) -> list[str]:
    """Return OCR text for every page of the PDF (index 0 == page 1)."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache = os.path.join(_CACHE_DIR, f"{_digest(path)}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)

    pages: list[str] = []
    for page in render_pages(path):
        gray = page.convert("L")
        parts = []
        for contrast, psm in _PASSES:
            img = ImageEnhance.Contrast(gray).enhance(contrast)
            parts.append(pytesseract.image_to_string(img, config=f"--psm {psm}"))
        pages.append("\n".join(parts))
    with open(cache, "w") as f:
        json.dump(pages, f)
    return pages
