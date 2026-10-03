"""Pure image and geometry helpers.

Nothing here touches Win32, so all of it is unit-testable on any machine.
"""

from __future__ import annotations

import io

from PIL import Image

MAX_EDGE = 1568
JPEG_QUALITY = 85


def fit_size(width: int, height: int, max_edge: int = MAX_EDGE) -> tuple[int, int, float]:
    """Size that fits within max_edge on the long side, never upscaling."""
    scale = min(1.0, max_edge / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale)), scale


def shrink(image: Image.Image, max_edge: int = MAX_EDGE) -> tuple[Image.Image, float]:
    """Downscale per fit_size; returns the image unchanged when it already fits."""
    width, height, scale = fit_size(image.width, image.height, max_edge)
    if scale >= 1.0:
        return image, 1.0
    return image.resize((width, height), Image.LANCZOS), scale


def encode_jpeg(image: Image.Image, quality: int = JPEG_QUALITY) -> bytes:
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def build_meta(
    source: str,
    origin_x: int,
    origin_y: int,
    original_size: tuple[int, int],
    image_size: tuple[int, int],
    scale: float,
) -> dict:
    """Coordinate metadata returned next to every capture (spec §5.3)."""
    return {
        "source": source,
        "originX": origin_x,
        "originY": origin_y,
        "originalWidth": original_size[0],
        "originalHeight": original_size[1],
        "imageWidth": image_size[0],
        "imageHeight": image_size[1],
        "scale": scale,
    }


def image_to_screen(meta: dict, x: float, y: float) -> tuple[int, int]:
    """Map a point on the returned image back to physical screen coordinates."""
    return (
        round(meta["originX"] + x / meta["scale"]),
        round(meta["originY"] + y / meta["scale"]),
    )
