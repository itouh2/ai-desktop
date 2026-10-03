"""MCP server that lets Claude Code see the user's Windows desktop."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from ai_desktop import capture, control
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta, encode_jpeg, select_window, shrink
from ai_desktop.viewer import Viewer

INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels). To point at things on screen, call \
show_annotated with the capture's captureId and HTML positioned in that image's pixel \
coordinates; it shows in the user's browser, reusing the open viewer tab, and the user \
can click on the page to click the real screen."""

mcp = MCPServer("ai-desktop", instructions=INSTRUCTIONS)
BACKGROUND_JPEG_QUALITY = 90
captures = CaptureStore()
MAX_HTML_CHARS = 100_000


@contextmanager
def _reported() -> Iterator[None]:
    """Surface CaptureError text to the model; other exceptions get masked by MCPServer."""
    try:
        yield
    except CaptureError as error:
        raise ToolError(str(error)) from error


def _store_capture(
    image: PILImage.Image, source: str, origin_x: int, origin_y: int, target: Target
) -> tuple[PILImage.Image, dict]:
    """Shrink for the model, keep the full-resolution background, and return (shrunk, meta)."""
    shrunk, scale = shrink(image)
    meta = build_meta(source, origin_x, origin_y, image.size, shrunk.size, scale)
    meta["captureId"] = captures.add(encode_jpeg(image, quality=BACKGROUND_JPEG_QUALITY), meta, target)
    return shrunk, meta


def _capture_result(
    image: PILImage.Image, source: str, origin_x: int, origin_y: int, target: Target
) -> list[Image | str]:
    shrunk, meta = _store_capture(image, source, origin_x, origin_y, target)
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(meta, ensure_ascii=False)]


def _recapture(target: Target) -> str:
    """Capture the same monitor or window again; returns the new captureId."""
    if target.kind == "monitor":
        image, monitor = capture.capture_monitor(target.id)
        source, origin = f"monitor:{monitor.id} {monitor.name}", (monitor.x, monitor.y)
    else:
        image, window = capture.capture_window(target.id)
        source, origin = f"window:{window.id} {window.title}", (window.x, window.y)
    return _store_capture(image, source, *origin, target)[1]["captureId"]


viewer = Viewer(captures, _recapture, control)


@mcp.tool(structured_output=False)
def list_monitors() -> str:
    """List the user's monitors: id, device name, primary flag, and position/size in
    physical pixels. Pass an id to capture_monitor."""
    with _reported():
        return json.dumps([asdict(m) for m in capture.list_monitors()], ensure_ascii=False)


@mcp.tool(structured_output=False)
def list_windows() -> str:
    """List visible top-level windows, front-most first: id, title, app exe, position/size
    in physical pixels, minimized, focused. Pass an id to capture_window as window_id."""
    with _reported():
        return json.dumps([asdict(w) for w in capture.list_windows()], ensure_ascii=False)


@mcp.tool()
def capture_monitor(monitor_id: int | None = None) -> list[Image | str]:
    """Capture a whole monitor of the user's desktop (the primary monitor when monitor_id
    is omitted). Use this when the user asks you to look at their screen or desktop.
    Returns a JPEG and JSON metadata; screen coordinates = origin + image coordinates / scale."""
    with _reported():
        image, monitor = capture.capture_monitor(monitor_id)
    return _capture_result(
        image, f"monitor:{monitor.id} {monitor.name}", monitor.x, monitor.y, Target("monitor", monitor.id)
    )


@mcp.tool()
def capture_window(window_id: int | None = None, title: str | None = None) -> list[Image | str]:
    """Capture one window, even when other windows cover it. Pass exactly one of window_id
    or title (a case-insensitive part of the window title). Try title first; if several
    windows match, the error lists candidates, so retry with window_id. Minimized windows
    cannot be captured. Returns a JPEG and JSON metadata; screen coordinates = origin +
    image coordinates / scale."""
    if (window_id is None) == (title is None):
        raise ToolError("window_id と title のどちらか一方だけを指定してください。")
    if title is not None and not title.strip():
        raise ToolError("title が空です。ウィンドウのタイトルの一部を指定してください。")
    with _reported():
        if window_id is None:
            window_id = select_window(capture.list_windows(), title).id
        image, window = capture.capture_window(window_id)
    return _capture_result(
        image, f"window:{window.id} {window.title}", window.x, window.y, Target("window", window.id)
    )


@mcp.tool(structured_output=False)
def show_annotated(capture_id: str, html: str, title: str | None = None) -> str:
    """Show the user one of your captures with your annotations drawn on top, in their
    default browser. Use it when pointing at places on screen makes your advice clearer.
    An open viewer tab is reused. The user can click or double-click on the page to click
    the real screen at that spot; the page then shows a fresh capture without annotations.

    capture_id: the captureId from a capture's metadata (the latest 10 are kept).
    html: elements positioned absolutely with style left/top in that capture's image
    pixels (imageWidth x imageHeight, i.e. the image you saw). Helper classes:
    .box (outline; left/top/width/height), .badge (numbered circle; left/top is its
    center), .note (callout; left/top is its top-left corner), and for arrows
    <svg class="layer"><line class="arrow" x1=".." y1=".." x2=".." y2=".."/></svg>
    (svg.layer covers the image, in image pixels). Scripts and external resources are
    blocked. title: optional page title."""
    if not html.strip():
        raise ToolError("html が空です。枠や注釈の HTML を指定してください。")
    if len(html) > MAX_HTML_CHARS:
        raise ToolError(f"html が長すぎます（{len(html)} 文字）。{MAX_HTML_CHARS} 文字以内にしてください。")
    with _reported():
        _, meta = captures.get(capture_id)
        try:
            delivered = viewer.publish(capture_id, html, title or meta["source"])
        except OSError as error:
            raise ToolError(f"表示用のローカルサーバーを起動できませんでした: {error}") from error
    if delivered:
        viewer.focus_browser()
        return "既存のタブを更新しました。"
    try:
        viewer.open_browser()
    except OSError as error:
        raise ToolError(f"ブラウザで開けませんでした: {viewer.url}（{error}）") from error
    return f"ブラウザで開きました: {viewer.url}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    capture.enable_dpi_awareness()
    mcp.run()
