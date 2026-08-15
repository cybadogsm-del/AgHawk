from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_WIDTH = 4096
MAX_HEIGHT = 4096
MAX_PIXELS = 16_000_000
_ALLOWED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}


class ImageValidationError(ValueError):
    """The submitted bytes are not an acceptable static logo image."""


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    data: bytes
    content_type: str
    byte_size: int
    width: int
    height: int
    sha256: str


def validate_logo(payload: bytes) -> ValidatedImage:
    """Decode, constrain, normalize, and canonically re-encode a logo."""

    if not isinstance(payload, bytes) or not payload:
        raise ImageValidationError("logo must contain image bytes")
    if len(payload) > MAX_INPUT_BYTES:
        raise ImageValidationError("logo is too large")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as opened:
                image_format = opened.format
                if image_format not in _ALLOWED_FORMATS:
                    raise ImageValidationError("logo format is not allowed")
                if getattr(opened, "n_frames", 1) != 1 or getattr(opened, "is_animated", False):
                    raise ImageValidationError("logo must be a static image")
                _check_dimensions(*opened.size)
                opened.load()
                normalized = ImageOps.exif_transpose(opened)
                normalized.load()
                _check_dimensions(*normalized.size)
                mode = "RGBA" if image_format == "PNG" and "A" in normalized.getbands() else "RGB"
                canonical_image = normalized.convert(mode)

            output = io.BytesIO()
            if image_format == "PNG":
                canonical_image.save(output, format="PNG", optimize=True)
            else:
                canonical_image.save(
                    output,
                    format="JPEG",
                    quality=90,
                    optimize=True,
                    progressive=False,
                )
    except ImageValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageValidationError("logo dimensions are too large") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageValidationError("logo is malformed or truncated") from exc

    canonical = output.getvalue()
    if not canonical or len(canonical) > MAX_INPUT_BYTES:
        raise ImageValidationError("canonical logo is too large")
    width, height = canonical_image.size
    return ValidatedImage(
        data=canonical,
        content_type=_ALLOWED_FORMATS[image_format],
        byte_size=len(canonical),
        width=width,
        height=height,
        sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _check_dimensions(width: int, height: int) -> None:
    if width > MAX_WIDTH or height > MAX_HEIGHT or width * height > MAX_PIXELS:
        raise ImageValidationError("logo dimensions are too large")
