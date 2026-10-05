"""MCP server that lets Claude Code see the user's Windows desktop."""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from ai_desktop import capture, control, inputs
from ai_desktop.annotate import REFRESH_LABEL
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta, encode_jpeg, select_window, shrink
from ai_desktop.pointer import Pointer
from ai_desktop.viewer import Viewer

INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels). To read something that only appears while the cursor rests on it (a tooltip, hover text, \
the description of an icon), call move_mouse with a capture's captureId and a point on that \
image: it moves the user's real cursor there, waits, captures the same target again and puts \
the cursor back, and it never clicks, so use it when the user is not using the mouse. \
To point at things on screen, call \
show_annotated with the capture's captureId and HTML positioned in that image's pixel \
coordinates; it shows in the user's browser, reusing the open viewer tab, and the user \
can click on the page to click the real screen. The page can also be a way for the \
user to send you messages without leaving it: pass buttons (fixed replies such as \
"done" or a choice) and/or message_box=true (free text, for when the user may need to \
tell you something the buttons cannot, like what they see or a question), plus an \
explanation, then call wait_for_message; you get the message (and whether it came from \
a button or the text box) plus a fresh capture of the same target, so react to it and, \
to keep going, show the page again and wait again. Such a page always has a built-in 更新 (refresh) button too, so never put 更新 in buttons; a message with via "refresh" means the user wants you to look again, so read the fresh capture and show the current step again. If it returns {"message": null}, call it again, but after five nulls in a row stop waiting and tell the user in the chat how to resume. When you stop taking messages on the page (the user is done, chose to stop, or talks about something else), call show_annotated once without buttons or message_box (html may be omitted) so the page leaves its thinking state."""

mcp = MCPServer("ai-desktop", instructions=INSTRUCTIONS)
BACKGROUND_JPEG_QUALITY = 90
MOVE_WAIT_DEFAULT_SECONDS = 0.5
MOVE_WAIT_MAX_SECONDS = 5.0
_sleep = time.sleep  # replaced in tests
captures = CaptureStore()
MAX_HTML_CHARS = 100_000
MAX_BUTTONS = 6
MAX_BUTTON_CHARS = 30
WAIT_DEFAULT_SECONDS = 90
WAIT_MAX_SECONDS = 110


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


def _recapture(target: Target) -> tuple[PILImage.Image, dict]:
    """Capture the same monitor or window again; returns (shrunk image, meta)."""
    if target.kind == "monitor":
        image, monitor = capture.capture_monitor(target.id)
        source, origin = f"monitor:{monitor.id} {monitor.name}", (monitor.x, monitor.y)
    else:
        image, window = capture.capture_window(target.id)
        source, origin = f"window:{window.id} {window.title}", (window.x, window.y)
    return _store_capture(image, source, *origin, target)


def _clean_buttons(buttons: list[str] | None) -> list[str]:
    labels = [label.strip() for label in buttons or [] if label.strip()]
    if REFRESH_LABEL in labels:
        raise ToolError(f"「{REFRESH_LABEL}」はページに常に出ているので、buttons に入れないでください。")
    if len(labels) > MAX_BUTTONS:
        raise ToolError(f"buttons は {MAX_BUTTONS} 個までです（{len(labels)} 個）。")
    too_long = [label for label in labels if len(label) > MAX_BUTTON_CHARS]
    if too_long:
        raise ToolError(f"ボタン名は {MAX_BUTTON_CHARS} 文字までです: {too_long[0]}")
    if len(set(labels)) != len(labels):
        raise ToolError("同じ名前のボタンがあります。名前は重ならないようにしてください。")
    return labels


def _capture_result(
    image: PILImage.Image, source: str, origin_x: int, origin_y: int, target: Target
) -> list[Image | str]:
    shrunk, meta = _store_capture(image, source, origin_x, origin_y, target)
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(meta, ensure_ascii=False)]


pointer = Pointer(captures, control)
viewer = Viewer(captures, control, pointer=pointer)


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
def show_annotated(
    capture_id: str,
    html: str = "",
    title: str | None = None,
    explanation: str | None = None,
    buttons: list[str] | None = None,
    message_box: bool = False,
) -> str:
    """Show the user one of your captures with your annotations drawn on top, in their
    default browser. Use it when pointing at places on screen makes your advice clearer.
    An open viewer tab is reused. The user can click or double-click on the page to click
    the real screen at that spot; the page itself is not refreshed (annotations stay),
    so capture again to see the result.

    capture_id: the captureId from a capture's metadata (the latest 20 are kept).
    html: elements positioned absolutely with style left/top in that capture's image
    pixels (imageWidth x imageHeight, i.e. the image you saw). Helper classes:
    .box (outline; left/top/width/height), .badge (numbered circle; left/top is its
    center), .note (callout; left/top is its top-left corner), and for arrows
    <svg class="layer"><line class="arrow" x1=".." y1=".." x2=".." y2=".."/></svg>
    (svg.layer covers the image, in image pixels). Scripts and external resources are
    blocked. Omit it (or pass "") for a page with no annotations, e.g. to end a conversation on the page.
    title: optional page title. explanation: optional plain text shown beside the
    image. buttons and message_box are the page's ways for the user to send you a message:
    buttons are labels (up to 6, 30 chars each) shown above the image, each sending its own
    label; message_box=true adds a text box (Enter sends, Shift+Enter breaks the line) for
    free text. With either, call wait_for_message next to receive what the user sends.
    A page with buttons or message_box also gets a built-in 更新 (refresh) button; never put 更新 in buttons."""
    if len(html) > MAX_HTML_CHARS:
        raise ToolError(f"html が長すぎます（{len(html)} 文字）。{MAX_HTML_CHARS} 文字以内にしてください。")
    labels = _clean_buttons(buttons)
    with _reported():
        _, meta = captures.get(capture_id)
        try:
            delivered = viewer.publish(
                capture_id, html, title or meta["source"], explanation or "", labels, message_box
            )
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


@mcp.tool()
def wait_for_message(timeout_seconds: int = WAIT_DEFAULT_SECONDS) -> list[Image | str]:
    """Wait until the user sends you a message from the page shown by show_annotated (call
    it right after showing buttons or a message box). Returns {"message": "<text>",
    "via": "button" | "text" | "refresh", ...metadata} plus a fresh JPEG of the same window or monitor,
    taken at that moment: via "button" means the message is the label of the pressed
    button; via "text" means the user typed it, so treat it like a chat message from them.
    via "refresh" means the user pressed the page's built-in 更新 button (message is ""): read the fresh capture again and show the current step again.
    Returns {"message": null} after timeout_seconds (1-110, default 90); then just call it
    again. Errors if no page or no way to send a message is shown, or if the re-capture fails."""
    timeout = max(1, min(WAIT_MAX_SECONDS, int(timeout_seconds)))
    with _reported():
        reply = viewer.wait_for_message(timeout)
        if reply is None:
            return [json.dumps({"message": None})]
        shrunk, meta = viewer.recapture_current(_recapture)
    result = {**reply, **meta}
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(result, ensure_ascii=False)]


@mcp.tool()
def move_mouse(
    capture_id: str,
    x: float,
    y: float,
    wait_seconds: float = MOVE_WAIT_DEFAULT_SECONDS,
    restore_cursor: bool = True,
) -> list[Image | str]:
    """Rest the mouse cursor on a point of one of your captures, wait, and capture the same
    window or monitor again, to read what only appears while the cursor is on something
    (tooltips, hover text, descriptions of icons). It never clicks. For a window capture it brings that
    window to the front first; a viewer browser covering a monitor capture is minimized for the
    moment and put back, and focus returns to the window that had it. It moves the user's real
    cursor for a moment, so use it when the user is not using the mouse.

    capture_id: the captureId from a capture's metadata (the latest 20 are kept).
    x, y: the point in that capture's image pixels (imageWidth x imageHeight).
    wait_seconds: how long the cursor rests before the capture (0-5, default 0.5).
    restore_cursor: put the cursor back where it was afterwards (default true).
    Returns a JPEG and JSON metadata like the capture tools, with a new captureId, plus
    "hover" (the point and the captureId it was on) and "cursorRestored". A window capture
    shows only that window, so a tooltip drawn as a separate popup appears only in a
    monitor capture."""
    wait = max(0.0, min(MOVE_WAIT_MAX_SECONDS, float(wait_seconds)))
    with _reported():
        target = captures.target(capture_id)
        with pointer.at(capture_id, x, y, keep_clear="capture") as spot:
            try:
                inputs.move(*spot.screen)
                _sleep(wait)
                shrunk, meta = _recapture(target)
            except BaseException:
                if restore_cursor:
                    with contextlib.suppress(CaptureError):
                        inputs.move(*spot.cursor)
                raise
            else:
                if restore_cursor:
                    inputs.move(*spot.cursor)
    result = {**meta, "hover": {"x": x, "y": y, "captureId": capture_id}, "cursorRestored": restore_cursor}
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(result, ensure_ascii=False)]


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    capture.enable_dpi_awareness()
    mcp.run()
