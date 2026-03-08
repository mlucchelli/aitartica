from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PIL import Image, ImageOps

from agent.config.loader import Config

logger = logging.getLogger(__name__)

# EXIF orientation tag
_EXIF_ORIENTATION = 0x0112


class ImagePreprocessingService:
    """
    Prepares a photo for vision analysis:
    1. Correct EXIF orientation (rotate/flip so pixels match visual orientation)
    2. Resize so the longest side is between vision_min_dimension and vision_max_dimension
    3. Save as JPEG preview — original is never modified

    Returns a PreprocessResult with the preview path and metadata.
    """

    def __init__(self, config: Config) -> None:
        self._cfg = config.image_preprocessing
        self._preview_dir = Path(config.photo_pipeline.vision_preview_dir)
        self._preview_dir.mkdir(parents=True, exist_ok=True)

    def process(self, source_path: str | Path) -> "PreprocessResult":
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source image not found: {source}")

        with Image.open(source) as img:
            original_width, original_height = img.size

            rotated = False
            if self._cfg.correct_exif_orientation:
                corrected = _apply_exif_orientation(img)
                rotated = corrected is not img
                img = corrected

            resized = _resize(img, self._cfg.vision_min_dimension, self._cfg.vision_max_dimension)
            was_resized = resized.size != (original_width, original_height)
            img = resized

            preview_width, preview_height = img.size
            preview_path = self._preview_dir / (source.stem + "_preview.jpg")

            if not rotated and not was_resized:
                # No changes — copy original to avoid re-encoding inflation
                import shutil
                shutil.copy2(source, preview_path)
            else:
                img.save(
                    preview_path,
                    format=self._cfg.vision_preview_format.upper(),
                    quality=self._cfg.vision_preview_quality,
                    optimize=True,
                )

        sha256 = _sha256(source)

        logger.info(
            "Preprocessed %s: %dx%d → %dx%d → %s",
            source.name, original_width, original_height,
            preview_width, preview_height, preview_path.name,
        )

        return PreprocessResult(
            source_path=source,
            preview_path=preview_path,
            original_width=original_width,
            original_height=original_height,
            preview_width=preview_width,
            preview_height=preview_height,
            sha256=sha256,
        )


class PreprocessResult:
    def __init__(
        self,
        source_path: Path,
        preview_path: Path,
        original_width: int,
        original_height: int,
        preview_width: int,
        preview_height: int,
        sha256: str,
    ) -> None:
        self.source_path = source_path
        self.preview_path = preview_path
        self.original_width = original_width
        self.original_height = original_height
        self.preview_width = preview_width
        self.preview_height = preview_height
        self.sha256 = sha256


def _apply_exif_orientation(img: Image.Image) -> Image.Image:
    """Rotate/flip image so visual orientation matches pixel data."""
    try:
        exif = img._getexif()  # type: ignore[attr-defined]
        if exif is None:
            return img
        orientation = exif.get(_EXIF_ORIENTATION)
        if orientation is None:
            return img
    except (AttributeError, Exception):
        return img

    return ImageOps.exif_transpose(img)


def _resize(img: Image.Image, min_dim: int, max_dim: int) -> Image.Image:
    """Resize so longest side is within [min_dim, max_dim]. Preserves aspect ratio."""
    w, h = img.size
    longest = max(w, h)

    if longest <= max_dim and longest >= min_dim:
        return img  # already in range

    target = max_dim if longest > max_dim else min_dim
    scale = target / longest
    new_w = round(w * scale)
    new_h = round(h * scale)

    return img.resize((new_w, new_h), Image.LANCZOS)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
