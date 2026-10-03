"""Real-machine end-to-end check of the viewer, run against the real MCP server over stdio.

1. show_annotated opens a browser tab, and a second call reuses it.
2. A click and a double-click sent the way the page sends them reach a real window.

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


def post_click(url: str, capture_id: str, x: float, y: float, double: bool) -> dict:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    token = parse_qs(parts.query)["t"][0]
    request = urllib.request.Request(
        f"{origin}/click",
        data=json.dumps({"captureId": capture_id, "x": x, "y": y, "double": double}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-AI-Desktop-Token": token, "Origin": origin},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


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
