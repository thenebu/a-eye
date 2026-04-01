"""Shared image-opening helper with RAW format support.

Tries Pillow first (handles JPEG, PNG, TIFF, BMP, WebP, HEIC, AVIF, DNG).
Falls back to rawpy for camera RAW formats (CR2, NEF, ARW, ORF, RW2, etc.).
"""
from __future__ import annotations

import logging
from pathlib import Path

import rawpy
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_RAW_EXTENSIONS = {
    ".raw", ".cr2", ".nef", ".arw", ".dng", ".orf", ".rw2",
    ".pef", ".srw", ".raf", ".cr3", ".3fr", ".kdc", ".mrw",
}


def open_image(path: Path) -> Image.Image:
    """Open an image file, with automatic RAW fallback.

    Returns a PIL Image in RGB mode with EXIF orientation applied.
    The caller is responsible for closing the image when done.
    """
    try:
        img = Image.open(path)
        img.load()  # Force read so errors surface here
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img
    except Exception:
        # If Pillow can't open it, try rawpy for RAW formats
        if path.suffix.lower() not in _RAW_EXTENSIONS:
            raise

    logger.debug("Pillow can't open %s, trying rawpy", path.name)
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False)
    img = Image.fromarray(rgb)
    return img
