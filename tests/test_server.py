import asyncio
import json
from dataclasses import asdict

import pytest
from mcp import Client
from PIL import Image

from ai_desktop import capture, server
from ai_desktop.imaging import CaptureError, MonitorInfo, WindowInfo

MONITOR = MonitorInfo(id=1, name=r"\.\DISPLAY1", primary=True, x=0, y=0, width=3200, height=1600)
WINDOW = WindowInfo(
    id=42, title="Book1 - Excel", app="EXCEL.EXE", x=-100, y=50, width=800, height=600,
    minimized=False, focused=True,
)


def call(name: str, arguments: dict | None = None):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments or {})

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def fake_capture(monkeypatch):
    def fake_capture_monitor(monitor_id):
        if monitor_id not in (None, MONITOR.id):
            raise CaptureError(f"monitor_id {monitor_id} は存在しません。有効な id: 1")
        return Image.new("RGB", (MONITOR.width, MONITOR.height)), MONITOR

    def fake_capture_window(hwnd):
        if hwnd != WINDOW.id:
            raise CaptureError(f"window_id {hwnd} のウィンドウは存在しません。")
        return Image.new("RGB", (WINDOW.width, WINDOW.height)), WINDOW

    monkeypatch.setattr(capture, "list_monitors", lambda: [MONITOR])
    monkeypatch.setattr(capture, "list_windows", lambda: [WINDOW])
    monkeypatch.setattr(capture, "capture_monitor", fake_capture_monitor)
    monkeypatch.setattr(capture, "capture_window", fake_capture_window)


def test_exposes_four_tools():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(run()).tools}
    assert names == {"list_monitors", "list_windows", "capture_monitor", "capture_window"}


def test_list_monitors_returns_json():
    result = call("list_monitors")
    assert not result.is_error
    assert json.loads(result.content[0].text) == [asdict(MONITOR)]


def test_list_windows_returns_json():
    result = call("list_windows")
    assert not result.is_error
    assert json.loads(result.content[0].text) == [asdict(WINDOW)]


def test_capture_monitor_returns_jpeg_and_meta():
    result = call("capture_monitor")
    assert not result.is_error
    image, text = result.content
    assert image.type == "image"
    assert image.mime_type == "image/jpeg"
    assert json.loads(text.text) == {
        "source": r"monitor:1 \.\DISPLAY1",
        "originX": 0,
        "originY": 0,
        "originalWidth": 3200,
        "originalHeight": 1600,
        "imageWidth": 1568,
        "imageHeight": 784,
        "scale": 0.49,
    }


def test_capture_window_by_title():
    result = call("capture_window", {"title": "excel"})
    assert not result.is_error
    meta = json.loads(result.content[1].text)
    assert meta["source"] == "window:42 Book1 - Excel"
    assert (meta["originX"], meta["originY"]) == (-100, 50)
    assert (meta["imageWidth"], meta["scale"]) == (800, 1.0)


@pytest.mark.parametrize("arguments", [{}, {"window_id": 42, "title": "excel"}])
def test_capture_window_needs_exactly_one_selector(arguments):
    result = call("capture_window", arguments)
    assert result.is_error
    assert "どちらか一方" in result.content[0].text


def test_capture_error_message_reaches_the_model():
    result = call("capture_window", {"window_id": 7})
    assert result.is_error
    assert "window_id 7 のウィンドウは存在しません" in result.content[0].text
