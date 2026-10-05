"""Real-machine end-to-end check of click, run against the real MCP server over stdio.

1. capture_window the test window and show it with show_annotated (this opens a browser tab,
   which must stay open: the permission turns off when no page tab is connected).
2. With the page's "Claude に操作を任せる" off (POST /agent {"enabled": false}), click is refused
   with a message saying it is off, and the test window sees no click.
3. With it on, the same click presses the middle of the window exactly once (no double-click),
   leaves the window in front and puts the cursor back where it was, and returns what was pressed.
4. Turns the permission off again and closes the test window.

Opens one browser tab and a small test window (closed at the end). Do not touch the mouse while
it runs."""

import asyncio
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from click_target import TITLE  # noqa: E402
from e2e_viewer import post_json  # noqa: E402

from ai_desktop import capture, control  # noqa: E402

GEOMETRY = "520x320+240+240"
WHAT = "試験用ウィンドウの中央"
NO_CLICKS = {"single": 0, "double": 0, "enter": 0, "leave": 0}


def start_target(geometry: str) -> tuple[subprocess.Popen, queue.Queue]:
    app = subprocess.Popen(
        [sys.executable, str(HERE / "click_target.py"), geometry],
        stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(json.loads(line)) for line in app.stdout], daemon=True).start()
    return app, lines


def latest(lines: queue.Queue, wait: float, last: dict) -> dict:
    """The newest state the test window printed within `wait` seconds, or `last` if it printed none."""
    deadline, state = time.monotonic() + wait, last
    while time.monotonic() < deadline:
        try:
            state = lines.get(timeout=0.1)
        except queue.Empty:
            pass
    return state


def target_window():
    return next((w for w in capture.list_windows() if w.title == TITLE), None)


async def set_agent(url: str, enabled: bool) -> None:
    answer = await asyncio.to_thread(post_json, url, "/agent", {"enabled": enabled})
    assert answer == {"ok": True}, answer


async def run(lines: queue.Queue) -> None:
    window = target_window()
    assert window is not None, "test window not found"
    params = StdioServerParameters(command="uv", args=["run", "--no-sync", "ai-desktop"], cwd=str(HERE.parent))
    async with Client(params) as client:
        shot = await client.call_tool("capture_window", {"title": TITLE})
        assert not shot.is_error, shot.content[0].text
        meta = json.loads(shot.content[1].text)
        capture_id = meta["captureId"]
        center = (meta["imageWidth"] / 2, meta["imageHeight"] / 2)
        print("captured:", meta["source"], capture_id, (meta["imageWidth"], meta["imageHeight"]))

        shown = (await client.call_tool("show_annotated", {"capture_id": capture_id, "html": "", "title": "e2e click"})).content[0].text
        print("show:", shown)
        assert shown.startswith("ブラウザで開きました: "), shown
        url = shown.split(": ", 1)[1]
        await asyncio.sleep(4)  # let the tab load and connect; it must stay open from here on

        try:
            away = (window.x - 40, window.y - 40)  # just outside the window, so the cursor's return is visible
            control.set_cursor(*away)
            before = await asyncio.to_thread(latest, lines, 0.5, dict(NO_CLICKS))
            print("before:", before, "cursor", control.cursor_pos())
            assert control.cursor_pos() == away, (control.cursor_pos(), away)

            await set_agent(url, False)
            refused = await client.call_tool("click", {"capture_id": capture_id, "x": center[0], "y": center[1], "what": WHAT})
            text = refused.content[0].text
            state = await asyncio.to_thread(latest, lines, 1.0, before)
            print("switch off:", text, "state", state, "cursor", control.cursor_pos())
            assert refused.is_error, "click was not refused while the switch is off"
            assert "オフです" in text, text
            assert state["single"] == before["single"], f"the window got a click while the switch was off: {state}"
            assert control.cursor_pos() == away, (control.cursor_pos(), away)

            await set_agent(url, True)
            result = await client.call_tool("click", {"capture_id": capture_id, "x": center[0], "y": center[1], "what": WHAT})
            assert not result.is_error, result.content[0].text
            assert result.content[0].type == "image", result.content[0].type
            clicked = json.loads(result.content[1].text)
            state = await asyncio.to_thread(latest, lines, 1.0, state)
            print("switch on:", clicked["clicked"], "state", state, "cursor", control.cursor_pos())
            assert state["single"] == before["single"] + 1, f"expected exactly one click: {before} -> {state}"
            assert state["double"] == 0, f"expected no double-click: {state}"
            assert control.foreground_window() == window.id, (control.foreground_window(), window.id)
            assert control.cursor_pos() == away, (control.cursor_pos(), away)
            assert clicked["clicked"]["what"] == WHAT, clicked["clicked"]
            assert clicked["clicked"]["captureId"] == capture_id, clicked["clicked"]
        finally:
            try:
                await set_agent(url, False)  # leave the permission off however the checks went
            except Exception as error:  # noqa: BLE001 - do not hide the real failure
                print("could not turn the switch off:", error)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.enable_dpi_awareness()
    app, lines = start_target(GEOMETRY)
    try:
        time.sleep(1.5)  # let the window appear
        asyncio.run(run(lines))
    finally:
        app.terminate()
        app.wait(timeout=5)
    print("OK")


if __name__ == "__main__":
    main()
