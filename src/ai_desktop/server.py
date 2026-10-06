"""MCP server that lets Claude Code see the user's Windows desktop."""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from ai_desktop import capture, control, inputs
from ai_desktop.annotate import REFRESH_LABEL, VIEWER_TITLE_PREFIX
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta, encode_jpeg, select_window, shrink
from ai_desktop.pointer import Pointer, Spot
from ai_desktop.viewer import Viewer

INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels); pass wait_seconds to a capture to let an animation or a \
tooltip settle first. The input tools below only send input and return what they did as text, \
with no image: capture the window again when you want to see the result (you can call an input \
tool and then a capture with wait_seconds in one turn). To read something that only appears \
while the cursor rests on it (a tooltip, hover text, the description of an icon), call move_mouse \
with a capture's captureId and a point on that image, then capture again: it leaves the user's \
real cursor there and never clicks, so use it when the user is not using the mouse. \
When the user has turned on "Claude に操作を任せる" on the viewer page, you may left-click \
the window shown there with click (capture_id, x, y and a short what describing the target), \
and after every click you must tell the user in the chat what you clicked. If it is off, ask \
the user to click or to turn it on. With the same permission, drag (capture_id, from_x, from_y, \
to_x, to_y and what) presses on one point, moves to the other and releases there, for things a \
hand would drag (a card, a box selection, a zone), and scroll (capture_id, x, y, amount and what) \
turns the mouse wheel there, amount notches up when positive and down when negative; tell the \
user in the chat what you dragged or scrolled as well. \
To point at things on screen, call \
show_annotated with the capture's captureId and HTML positioned in that image's pixel \
coordinates; it shows in the user's browser, reusing the open viewer tab, and the user \
can click on the page to click the real screen. The page can also be a way for the \
user to send you messages without leaving it: pass buttons (fixed replies such as \
"done" or a choice) and/or message_box=true (free text, for when the user may need to \
tell you something the buttons cannot, like what they see or a question), plus an \
explanation, then call wait_for_message; you get the message (and whether it came from \
a button or the text box) plus a fresh capture of the same target, so react to it and, \
to keep going, show the page again and wait again. Such a page always has a built-in 更新 (refresh) button too, so never put 更新 in buttons; a message with via "refresh" means the user wants you to look again, so read the fresh capture and show the current step again. If wait_for_message returns {"message": null}, call it again, but after five nulls in a row stop waiting and tell the user in the chat how to resume. When you stop taking messages on the page (the user is done, chose to stop, or talks about something else), call show_annotated once without buttons or message_box (html may be omitted) so the page leaves its thinking state."""

mcp = MCPServer("ai-desktop", instructions=INSTRUCTIONS)
BACKGROUND_JPEG_QUALITY = 90
CAPTURE_WAIT_MAX_SECONDS = 5.0
# after a click, drag or scroll the cursor stays on the point this long before it goes back, for
# apps that read where the cursor is once a frame rather than from the input itself
AFTER_INPUT_SECONDS = 0.3
MAX_SCROLL_NOTCHES = 20
MAX_WHAT_CHARS = 60
# Apps where Claude Code itself runs (editors, terminals, the Claude app): Claude must not press
# its own permission dialogs there, so click refuses them (the viewer browser is refused by title).
PROTECTED_APPS = frozenset({
    "code.exe", "code - insiders.exe", "cursor.exe", "windsurf.exe", "windowsterminal.exe",
    "openconsole.exe", "conhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "claude.exe",
    "mintty.exe", "wezterm-gui.exe", "alacritty.exe", "tabby.exe", "hyper.exe", "warp.exe",
    "zed.exe", "idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe", "goland64.exe",
    "clion64.exe", "phpstorm64.exe", "rustrover64.exe",
})
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


def _wait_before_capture(wait_seconds: float) -> None:
    wait = min(CAPTURE_WAIT_MAX_SECONDS, float(wait_seconds))
    if wait > 0:
        _sleep(wait)


def _target_field(target: Target) -> dict:
    """Where an input went, so the model knows what to capture to see the result."""
    return {"windowId": target.id} if target.kind == "window" else {"monitorId": target.id}


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
def capture_monitor(monitor_id: int | None = None, wait_seconds: float = 0) -> list[Image | str]:
    """Capture a whole monitor of the user's desktop (the primary monitor when monitor_id
    is omitted). Use this when the user asks you to look at their screen or desktop.
    wait_seconds: wait this long before capturing (0-5, default 0), e.g. after a click for an
    animation or a tooltip to settle.
    Returns a JPEG and JSON metadata; screen coordinates = origin + image coordinates / scale."""
    _wait_before_capture(wait_seconds)
    with _reported():
        image, monitor = capture.capture_monitor(monitor_id)
    return _capture_result(
        image, f"monitor:{monitor.id} {monitor.name}", monitor.x, monitor.y, Target("monitor", monitor.id)
    )


@mcp.tool()
def capture_window(
    window_id: int | None = None, title: str | None = None, wait_seconds: float = 0
) -> list[Image | str]:
    """Capture one window, even when other windows cover it. Pass exactly one of window_id
    or title (a case-insensitive part of the window title). Try title first; if several
    windows match, the error lists candidates, so retry with window_id. Minimized windows
    cannot be captured. wait_seconds: wait this long before capturing (0-5, default 0), e.g.
    after a click for an animation or a tooltip to settle. Returns a JPEG and JSON metadata;
    screen coordinates = origin + image coordinates / scale."""
    if (window_id is None) == (title is None):
        raise ToolError("window_id と title のどちらか一方だけを指定してください。")
    if title is not None and not title.strip():
        raise ToolError("title が空です。ウィンドウのタイトルの一部を指定してください。")
    _wait_before_capture(wait_seconds)
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
    title: optional page title. explanation: optional plain text shown below the
    image. buttons and message_box are the page's ways for the user to send you a message:
    buttons are labels (up to 6, 30 chars each) shown in the reply bar at the bottom of the page, each sending its own
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


@mcp.tool(structured_output=False)
def move_mouse(capture_id: str, x: float, y: float) -> str:
    """Move the mouse cursor to a point of one of your captures and leave it there, to show what
    only appears while the cursor is on something (tooltips, hover text, descriptions of icons);
    then capture again to read it (pass wait_seconds to the capture if it takes a moment to
    appear). It never clicks and needs no permission. For a window capture it brings that window
    to the front and leaves it there; on a monitor capture, a viewer browser covering the point is
    minimized and stays down (the next show_annotated brings the page back). It moves the user's
    real cursor, so use it when the user is not using the mouse.

    capture_id: the captureId from a capture's metadata (the latest 20 are kept).
    x, y: the point in that capture's image pixels (imageWidth x imageHeight).
    Returns JSON text, no image: "moved" (the point and the captureId it was on) and "windowId"
    or "monitorId" (what to capture next). A window capture shows only that window, so a tooltip
    drawn as a separate popup appears only in a monitor capture."""
    with _reported():
        target = captures.target(capture_id)
        with pointer.at(capture_id, x, y, return_focus=False, restore_browser=False) as spot:
            inputs.move(*spot.screen)
    return json.dumps(
        {"moved": {"x": x, "y": y, "captureId": capture_id}, **_target_field(target)}, ensure_ascii=False
    )


def _ensure_clickable(window_id: int) -> None:
    """Raise CaptureError unless Claude may click this window: it must still exist, its app must be
    known (an unknown one could be where Claude Code runs), and it must not be where Claude Code runs
    or the viewer page itself."""
    window = next((w for w in capture.list_windows() if w.id == window_id), None)
    if window is None:
        raise CaptureError("対象のウィンドウが見つかりません。撮影し直してください。")
    if not window.app:
        raise CaptureError("このウィンドウのアプリを確かめられないため、Claude には押させません。ユーザーが押してください。")
    if window.app.lower() in PROTECTED_APPS or window.title.startswith(VIEWER_TITLE_PREFIX):
        raise CaptureError(
            f"このウィンドウ（{window.app}）は Claude には押させません。"
            "Claude Code が動くアプリと注釈ページは、ユーザーが押してください。"
        )


@mcp.tool(structured_output=False)
def click(capture_id: str, x: float, y: float, what: str) -> str:
    """Left-click once on a point of the window the user's viewer page is showing. It works only
    while the user has turned on "Claude に操作を任せる" on that page, and only for that window (a
    newer capture of the same window is fine; a monitor capture is not). Showing a different window
    or a monitor on the page turns the switch off, so the user has to turn it on again for the new
    window. It presses the user's real screen, so use it only for what the user asked you to do. It
    cannot right-click or double-click; to drag, use drag; to turn the wheel, use scroll. Windows
    where Claude Code runs (editors, terminals, the Claude app), windows whose app cannot be
    identified and the viewer browser are refused: the user presses those. Put what you press in
    what, and after every click you must tell the user in the chat what you clicked. When the
    switch is off it returns an error: ask the user to click, or to turn it on. The clicked window
    stays in front. The cursor rests on the point a moment, then goes back. It does not capture:
    call capture_window (with wait_seconds for an animation) when you want to see the result.

    capture_id: the captureId from a capture's metadata (the latest 20 are kept).
    x, y: the point in that capture's image pixels (imageWidth x imageHeight).
    what: what you press, 1-60 characters (e.g. "OK ボタン"); it is shown to the user on the page.
    Returns JSON text, no image: "clicked" (the point, the captureId it was on, and what) and
    "windowId" (what to capture next)."""
    what = _short_what(what)
    target = _operate(capture_id, (x, y), None, lambda spot: inputs.click(*spot.screen), recorded=what)
    clicked = {"x": x, "y": y, "captureId": capture_id, "what": what}
    return json.dumps({"clicked": clicked, **_target_field(target)}, ensure_ascii=False)


@mcp.tool(structured_output=False)
def drag(capture_id: str, from_x: float, from_y: float, to_x: float, to_y: float, what: str) -> str:
    """Left-drag from one point to another on the window the user's viewer page is showing (press
    on the first point, move to the second in small steps, release there). Use it to move things a
    hand would drag: a card or an item to another place, a box selection, a zone drawn on a map. It
    needs the same permission as click ("Claude に操作を任せる" on the page, for that window only) and
    refuses the same windows; both points must be on that window and not under another one, or
    nothing is pressed. Put what you drag and where in what, and after every drag you must tell the
    user in the chat what you dragged. The window stays in front. The cursor rests on the end a
    moment, then goes back. It does not capture: call capture_window to see the result.

    capture_id: the captureId from a capture's metadata (the latest 20 are kept).
    from_x, from_y: where the drag starts, in that capture's image pixels.
    to_x, to_y: where it ends, in the same image's pixels.
    what: what you drag and where, 1-60 characters (e.g. "左のジョーカーを右端へ"); it is shown on the page.
    Returns JSON text, no image: "dragged" (fromX, fromY, toX, toY, the captureId they were on, and
    what) and "windowId"."""
    what = _short_what(what)
    target = _operate(
        capture_id, (from_x, from_y), (to_x, to_y), lambda spot: inputs.drag(spot.screen, spot.end),
        recorded=f"{what}（ドラッグ）",
    )
    dragged = {"fromX": from_x, "fromY": from_y, "toX": to_x, "toY": to_y, "captureId": capture_id, "what": what}
    return json.dumps({"dragged": dragged, **_target_field(target)}, ensure_ascii=False)


@mcp.tool(structured_output=False)
def scroll(capture_id: str, x: float, y: float, amount: int, what: str) -> str:
    """Turn the mouse wheel on a point of the window the user's viewer page is showing: amount
    notches up (away from the user, usually toward the top of a list) when positive, down when
    negative. Use it for lists, pages and maps that move with the wheel. The wheel can change
    things too (a value under the cursor, the zoom of a map), so it needs the same permission as
    click ("Claude に操作を任せる" on the page, for that window only) and refuses the same windows;
    the point must be on that window and not under another one. Put what you scroll in what, and
    after every scroll you must tell the user in the chat what you scrolled. The window stays in
    front. The cursor rests on the point a moment, then goes back. It does not capture: call
    capture_window to see the result.

    capture_id: the captureId from a capture's metadata (the latest 20 are kept).
    x, y: the point in that capture's image pixels (imageWidth x imageHeight).
    amount: notches to turn, -20 to 20 and not 0 (one notch is one click of a wheel).
    what: what you scroll, 1-60 characters (e.g. "カードの一覧を下へ"); it is shown on the page.
    Returns JSON text, no image: "scrolled" (the point, amount, the captureId it was on, and what)
    and "windowId"."""
    if amount == 0 or abs(amount) > MAX_SCROLL_NOTCHES:
        raise ToolError(f"amount は -{MAX_SCROLL_NOTCHES}〜{MAX_SCROLL_NOTCHES} の 0 以外の整数で指定してください。")
    what = _short_what(what)
    target = _operate(
        capture_id, (x, y), None, lambda spot: inputs.scroll(*spot.screen, amount), recorded=f"{what}（スクロール）"
    )
    scrolled = {"x": x, "y": y, "amount": amount, "captureId": capture_id, "what": what}
    return json.dumps({"scrolled": scrolled, **_target_field(target)}, ensure_ascii=False)


def _short_what(what: str) -> str:
    what = what.strip()
    if not 1 <= len(what) <= MAX_WHAT_CHARS:
        raise ToolError(f"what に、何を押すかを 1〜{MAX_WHAT_CHARS} 文字で書いてください。")
    return what


def _operate(
    capture_id: str,
    point: tuple[float, float],
    to: tuple[float, float] | None,
    press: Callable[[Spot], None],
    recorded: str,
) -> Target:
    """What click, drag and scroll share: check the permission and the window, send the input, log
    it on the page, let the cursor rest on the point a moment and put it back. Returns the target."""
    with _reported():
        target = captures.target(capture_id)
        viewer.authorize_click(capture_id)
        _ensure_clickable(target.id)
        with pointer.at(capture_id, *point, return_focus=False, must_hit_target=True, to=to) as spot:
            viewer.authorize_click(capture_id)  # the user may have switched it off while we got ready
            try:
                press(spot)
                viewer.record_click(recorded)
                _sleep(AFTER_INPUT_SECONDS)
            finally:
                with contextlib.suppress(CaptureError):
                    inputs.move(*spot.cursor)
    return target


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    capture.enable_dpi_awareness()
    mcp.run()
