from __future__ import annotations

import io

import pytest
from PIL import Image, PngImagePlugin

from turfhelm.branding.images import ImageValidationError, validate_logo


def image_bytes(
    image_format: str,
    *,
    size: tuple[int, int] = (20, 10),
    mode: str = "RGB",
    **save_options: object,
) -> bytes:
    image = Image.new(mode, size, (10, 20, 30, 128) if mode == "RGBA" else (10, 20, 30))
    output = io.BytesIO()
    image.save(output, format=image_format, **save_options)
    return output.getvalue()


@pytest.mark.parametrize(
    ("image_format", "expected_type", "expected_format"),
    [("PNG", "image/png", "PNG"), ("JPEG", "image/jpeg", "JPEG")],
)
def test_valid_png_and_jpeg_are_canonically_reencoded(
    image_format: str,
    expected_type: str,
    expected_format: str,
) -> None:
    result = validate_logo(image_bytes(image_format))

    assert result.content_type == expected_type
    assert result.width == 20
    assert result.height == 10
    assert result.byte_size == len(result.data)
    assert len(result.sha256) == 64
    with Image.open(io.BytesIO(result.data)) as decoded:
        assert decoded.format == expected_format
        assert decoded.mode in {"RGB", "RGBA"}
        decoded.load()


def test_validation_ignores_filename_extensions_by_accepting_only_bytes() -> None:
    result = validate_logo(image_bytes("PNG"))
    assert result.content_type == "image/png"


def test_png_metadata_is_stripped() -> None:
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "secret metadata")

    result = validate_logo(image_bytes("PNG", pnginfo=metadata))

    with Image.open(io.BytesIO(result.data)) as decoded:
        assert "Comment" not in decoded.info


@pytest.mark.parametrize(
    "payload",
    [
        b"not an image",
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>',
        image_bytes("PNG")[:20],
    ],
)
def test_non_images_svg_and_truncated_images_are_rejected(payload: bytes) -> None:
    with pytest.raises(ImageValidationError):
        validate_logo(payload)


def test_input_over_two_mib_is_rejected_before_decode() -> None:
    with pytest.raises(ImageValidationError, match="too large"):
        validate_logo(b"x" * ((2 * 1024 * 1024) + 1))


@pytest.mark.parametrize("size", [(4097, 1), (1, 4097), (4096, 4096)])
def test_excessive_dimensions_or_pixels_are_rejected(size: tuple[int, int]) -> None:
    with pytest.raises(ImageValidationError, match="dimensions"):
        validate_logo(image_bytes("PNG", size=size))


def test_animated_png_is_rejected() -> None:
    first = Image.new("RGB", (2, 2), "red")
    second = Image.new("RGB", (2, 2), "blue")
    output = io.BytesIO()
    first.save(output, format="PNG", save_all=True, append_images=[second])

    with pytest.raises(ImageValidationError, match="static"):
        validate_logo(output.getvalue())
