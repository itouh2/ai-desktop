"""Real-machine end-to-end check of move_mouse, run against the real MCP server over stdio.

1. On the primary monitor: capture_window the test window, rest the cursor on its middle,
   and check the returned image shows the hover color, the window saw the cursor come and
   go, and the cursor is back where it was.
2. With two or more monitors: the same on a non-primary monitor with capture_monitor.

Opens a small test window (closed at the end). Do not touch the mouse while it runs."""

import asyncio
import base64
import io
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from mcp import Client, StdioServerParameters
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from click_target import HOVER_COLOR, TITLE  # noqa: E402

from ai_desktop import capture, control  # noqa: E402


def start_target(geometry: str) -> tuple[subprocess.Popen, queue.Queue]:
    app = subprocess.Popen(
        [sys.executable, str(HERE / "click_target.py"), geometry],
        stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(json.loads(line)) for line in app.stdout], daemon=True).start()
    return app, lines


def latest(lines: queue.Queue, wait: float) -> dict:
    deadline, state = time.monotonic() + wait, {}
    while time.monotonic() < deadline:
        try:
            state = lines.get(timeout=0.1)
        except queue.Empty:
            pass
    return state


def target_window():
    return next((w for w in capture.list_windows() if w.title == TITLE), None)


def is_hover_color(rgb: tuple[int, int, int]) -> bool:
    expected = tuple(int(HOVER_COLOR[i : i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= 24 for a, b in zip(rgb, expected))  # JPEG drifts a little


async def check(client: Client, lines: queue.Queue, tool: str, arguments: dict, point_of) -> None:
    window = target_window()
    assert window is not None, "test window not found"
    away = (window.x - 40, window.y - 40)  # just outside the window, so the hover must start and end
    control.set_cursor(*away)
    latest(lines, 0.5)

    shot = await client.call_tool(tool, arguments)
    meta = json.loads(shot.content[1].text)
    x, y = point_of(meta, window, 0.5)
    result = await client.call_tool("move_mouse", {"capture_id": meta["captureId"], "x": x, "y": y})
    assert not result.is_error, result.content[0].text
    hover_meta = json.loads(result.content[1].text)
    image = Image.open(io.BytesIO(base64.b64decode(result.content[0].data))).convert("RGB")
    sample_x, sample_y = point_of(meta, window, 0.15)
    pixel = image.getpixel((round(sample_x), round(sample_y)))
    state = latest(lines, 1.0)
    print(tool, "->", hover_meta["captureId"], "pixel", pixel, "state", state, "cursor", control.cursor_pos())
    assert is_hover_color(pixel), f"the capture does not show the hover color: {pixel}"
    assert state.get("enter", 0) >= 1 and state.get("leave", 0) >= 1, state
    assert state.get("single", 0) == 0 and state.get("double", 0) == 0, state
    assert control.cursor_pos() == away, (control.cursor_pos(), away)
    assert hover_meta["cursorRestored"] is True


def window_middle(meta: dict, window, fraction: float = 0.5) -> tuple[float, float]:
    return meta["imageWidth"] * fraction, meta["imageHeight"] * fraction


def window_middle_on_monitor(meta: dict, window, fraction: float = 0.5) -> tuple[float, float]:
    scale = meta["scale"]
    return (
        (window.x - meta["originX"] + window.width * fraction) * scale,
        (window.y - meta["originY"] + window.height * fraction) * scale,
    )


async def run_on(geometry: str, tool: str, arguments: dict, point_of) -> None:
    app, lines = start_target(geometry)
    try:
        time.sleep(1.5)  # let the window appear
        params = StdioServerParameters(command="uv", args=["run", "--no-sync", "ai-desktop"], cwd=str(HERE.parent))
        async with Client(params) as client:
            await check(client, lines, tool, arguments, point_of)
    finally:
        app.terminate()
        app.wait(timeout=5)


async def main() -> None:
    capture.enable_dpi_awareness()
    await run_on("520x320+240+240", "capture_window", {"title": TITLE}, window_middle)
    others = [m for m in capture.list_monitors() if not m.primary]
    if others:
        monitor = others[0]
        geometry = f"520x320+{monitor.x + 200}+{monitor.y + 200}"
        print("secondary monitor:", monitor.id, monitor.name, (monitor.x, monitor.y))
        await run_on(geometry, "capture_monitor", {"monitor_id": monitor.id}, window_middle_on_monitor)
    else:
        print("only one monitor: skipped the secondary-monitor check")
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
