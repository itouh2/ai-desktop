"""Pure image and geometry helpers.

Nothing here touches Win32, so all of it is unit-testable on any machine.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

MAX_EDGE = 1568
JPEG_QUALITY = 85

MAX_CANDIDATES = 20


class CaptureError(Exception):
    """A capture problem whose message is written for the model to read."""


@dataclass(frozen=True)
class MonitorInfo:
    id: int
    name: str
    primary: bool
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class WindowInfo:
    id: int
    title: str
    app: str
    x: int
    y: int
    width: int
    height: int
    minimized: bool
    focused: bool


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
    """Encode as JPEG bytes, converting to RGB first when needed."""
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


def select_window(windows: list[WindowInfo], title: str) -> WindowInfo:
    """Pick the one window whose title contains `title`, ignoring case (spec §6.2)."""
    needle = title.casefold()
    matches = [w for w in windows if needle in w.title.casefold()]
    if not matches:
        raise CaptureError(
            f"タイトルに「{title}」を含むウィンドウがありません。list_windows で確認してください。"
        )
    if len(matches) == 1:
        return matches[0]
    exact = [w for w in matches if w.title.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    lines = [f"- id={w.id} title={w.title}" for w in matches[:MAX_CANDIDATES]]
    if len(matches) > MAX_CANDIDATES:
        lines.append(f"…ほか {len(matches) - MAX_CANDIDATES} 件")
    raise CaptureError(
        f"タイトルに「{title}」を含むウィンドウが {len(matches)} 件あります。"
        "window_id を指定して撮り直してください。\n" + "\n".join(lines)
    )
