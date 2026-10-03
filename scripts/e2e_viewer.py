"""Real-machine end-to-end check of the viewer, run against the real MCP server over stdio.

1. show_annotated opens a browser tab, and a second call reuses it.
2. A click and a double-click sent the way the page sends them reach a real window.
3. Page buttons: wait_for_button returns the pressed label plus a fresh capture, and
   {"pressed": null} on timeout. A screenshot of the viewer is saved to smoke-out/.

Opens one browser tab and a small test window (closed at the end)."""

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from control_smoke import latest, start_target  # noqa: E402

from click_target import TITLE  # noqa: E402


def post_json(url: str, path: str, body: dict) -> dict:
    """POST to the viewer the way its page does (token header + same Origin)."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    token = parse_qs(parts.query)["t"][0]
    request = urllib.request.Request(
        f"{origin}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-AI-Desktop-Token": token, "Origin": origin},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def post_click(url: str, capture_id: str, x: float, y: float, double: bool) -> dict:
    return post_json(url, "/click", {"captureId": capture_id, "x": x, "y": y, "double": double})


def save_viewer_screenshot(name: str) -> None:
    from ai_desktop import capture, control

    capture.enable_dpi_awareness()
    hwnd = control.find_window("ai-desktop | ")
    if hwnd is None:
        print("viewer window not found for screenshot")
        return
    image, info = capture.capture_window(hwnd)
    image.thumbnail((1400, 1400))
    out = HERE.parent / "smoke-out"
    out.mkdir(exist_ok=True)
    image.save(out / name)
    print("saved", out / name, info.title)


async def run(lines) -> None:
    params = StdioServerParameters(command="uv", args=["run", "ai-desktop"], cwd=str(HERE.parent))
    async with Client(params) as client:
        result = await client.call_tool("capture_window", {"title": TITLE})
        meta = json.loads(result.content[1].text)
        print("captured:", meta["source"], meta["captureId"], (meta["imageWidth"], meta["imageHeight"]))

        box = '<div class="box" style="left:20px;top:20px;width:200px;height:80px"></div>'
        first = (await client.call_tool("show_annotated", {"capture_id": meta["captureId"], "html": box, "title": "e2e"})).content[0].text
        print("first show:", first)
        assert first.startswith("ブラウザで開きました: "), first
        url = first.split(": ", 1)[1]
        time.sleep(4)  # let the tab load and connect

        second = (await client.call_tool("show_annotated", {"capture_id": meta["captureId"], "html": box, "title": "e2e 2"})).content[0].text
        print("second show:", second)
        assert second == "既存のタブを更新しました。", second

        center = (meta["imageWidth"] / 2, meta["imageHeight"] / 2)
        clicked = await asyncio.to_thread(post_click, url, meta["captureId"], *center, False)
        print("click:", clicked, latest(lines, 1.0))
        assert clicked.get("ok"), clicked
        doubled = await asyncio.to_thread(post_click, url, meta["captureId"], *center, True)
        state = latest(lines, 1.0)
        print("double:", doubled, state)
        assert doubled.get("ok"), doubled
        assert state.get("single", 0) >= 1 and state.get("double", 0) >= 1, state

        shown = (await client.call_tool("show_annotated", {
            "capture_id": meta["captureId"], "html": box, "title": "e2e buttons",
            "explanation": "e2e: ボタンの確認です。\n「分からない」を押します。",
            "buttons": ["できた", "分からない"],
        })).content[0].text
        print("buttons show:", shown)
        timed_out = await client.call_tool("wait_for_button", {"timeout_seconds": 1})
        print("timeout wait:", timed_out.content[0].text)
        assert json.loads(timed_out.content[0].text) == {"pressed": None}

        waiter = asyncio.create_task(client.call_tool("wait_for_button", {"timeout_seconds": 30}))
        await asyncio.sleep(1.5)  # the tool is now waiting
        await asyncio.to_thread(save_viewer_screenshot, "viewer-buttons-waiting.png")
        pressed = await asyncio.to_thread(post_json, url, "/press", {"button": "分からない"})
        print("press:", pressed)
        assert pressed == {"ok": True}, pressed
        result = await waiter
        answer = json.loads(result.content[1].text)
        print("wait result:", result.content[0].type, answer["pressed"], answer["captureId"], answer["source"])
        assert result.content[0].type == "image" and answer["pressed"] == "分からない"
        again = await asyncio.to_thread(post_json, url, "/press", {"button": "できた"})
        print("press while not waiting:", again)
        assert "待ち受けていません" in again.get("error", "")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    app, lines = start_target()
    try:
        time.sleep(1.0)
        latest(lines, 0.5)  # drain the initial 0/0 line
        asyncio.run(run(lines))
        print("E2E OK")
    finally:
        app.terminate()


if __name__ == "__main__":
    main()
