import asyncio
import base64
import io
import json
from dataclasses import asdict

import pytest
from mcp import Client
from PIL import Image

from ai_desktop import capture, server
from ai_desktop.captures import CaptureStore, Target
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
    monkeypatch.setattr(server, "captures", CaptureStore())


def test_exposes_six_tools():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(run()).tools}
    assert names == {
        "list_monitors", "list_windows", "capture_monitor", "capture_window", "show_annotated",
        "wait_for_message",
    }


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
    decoded = Image.open(io.BytesIO(base64.b64decode(image.data)))
    assert decoded.format == "JPEG"
    meta = json.loads(text.text)
    assert decoded.size == (meta["imageWidth"], meta["imageHeight"])
    assert meta == {
        "source": r"monitor:1 \.\DISPLAY1",
        "originX": 0,
        "originY": 0,
        "originalWidth": 3200,
        "originalHeight": 1600,
        "imageWidth": 1568,
        "imageHeight": 784,
        "scale": 0.49,
        "captureId": "c1",
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


def test_capture_monitor_unknown_id_is_reported():
    result = call("capture_monitor", {"monitor_id": 9})
    assert result.is_error
    assert "monitor_id 9 は存在しません" in result.content[0].text


@pytest.mark.parametrize("title", ["", "  "])
def test_capture_window_rejects_empty_title(title):
    result = call("capture_window", {"title": title})
    assert result.is_error
    assert "title が空です" in result.content[0].text


def test_captures_are_stored_with_sequential_ids():
    first = json.loads(call("capture_monitor").content[1].text)
    second = json.loads(call("capture_window", {"title": "excel"}).content[1].text)
    assert (first["captureId"], second["captureId"]) == ("c1", "c2")
    background, meta = server.captures.get("c1")
    assert Image.open(io.BytesIO(background)).size == (3200, 1600)
    assert meta == first


def test_captures_record_their_target():
    call("capture_monitor")
    call("capture_window", {"title": "excel"})
    assert server.captures.target("c1") == Target("monitor", 1)
    assert server.captures.target("c2") == Target("window", 42)


class FakeViewer:
    """Stands in for ai_desktop.viewer.Viewer: records publishes instead of serving pages."""

    url = "http://127.0.0.1:5555/?t=token"

    def __init__(self):
        self.delivered = False
        self.start_error = None
        self.open_error = None
        self.published = []
        self.opened = 0
        self.focused = 0
        self.reply = None
        self.waited = []
        self.target = Target("window", 42)

    def publish(self, capture_id, html, title, explanation="", buttons=None, message_box=False):
        if self.start_error is not None:
            raise self.start_error
        self.published.append((capture_id, html, title))
        self.last_extras = (explanation, buttons, message_box)
        return self.delivered

    def wait_for_message(self, timeout):
        self.waited.append(timeout)
        return self.reply

    def recapture_current(self, recapture):
        return recapture(self.target)

    def open_browser(self):
        if self.open_error is not None:
            raise self.open_error
        self.opened += 1

    def focus_browser(self):
        self.focused += 1


@pytest.fixture
def viewer(monkeypatch):
    fake = FakeViewer()
    monkeypatch.setattr(server, "viewer", fake)
    return fake


def test_show_annotated_opens_browser_when_no_tab_is_open(viewer):
    call("capture_window", {"title": "excel"})
    badge = '<div class="badge" style="left:5px;top:5px">1</div>'
    result = call("show_annotated", {"capture_id": "c1", "html": badge})
    assert not result.is_error
    assert result.content[0].text == "ブラウザで開きました: http://127.0.0.1:5555/?t=token"
    assert viewer.published == [("c1", badge, "window:42 Book1 - Excel")]
    assert (viewer.opened, viewer.focused) == (1, 0)


def test_show_annotated_reuses_the_open_tab(viewer):
    viewer.delivered = True
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": "<div></div>", "title": "設定画面"})
    assert result.content[0].text == "既存のタブを更新しました。"
    assert viewer.published == [("c1", "<div></div>", "設定画面")]
    assert (viewer.opened, viewer.focused) == (0, 1)


def test_show_annotated_unknown_capture_is_reported(viewer):
    result = call("show_annotated", {"capture_id": "c99", "html": "<div></div>"})
    assert result.is_error
    assert "c99" in result.content[0].text
    assert viewer.published == []


@pytest.mark.parametrize("html", ["", "   "])
def test_show_annotated_rejects_empty_html(viewer, html):
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": html})
    assert result.is_error
    assert "html が空です" in result.content[0].text
    assert viewer.published == []


@pytest.mark.parametrize("length, expected_error", [(100_000, False), (100_001, True)])
def test_show_annotated_html_length_limit(viewer, length, expected_error):
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": "x" * length})
    assert result.is_error is expected_error
    if expected_error:
        assert "html が長すぎます" in result.content[0].text
        assert viewer.published == []
    else:
        assert len(viewer.published) == 1


def test_show_annotated_reports_server_start_failure(viewer):
    viewer.start_error = OSError("address in use")
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": "<div></div>"})
    assert result.is_error
    assert "表示用のローカルサーバーを起動できませんでした" in result.content[0].text
    assert "address in use" in result.content[0].text


def test_show_annotated_reports_browser_failure(viewer):
    viewer.open_error = OSError("no association")
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": "<div></div>"})
    assert result.is_error
    text = result.content[0].text
    assert "ブラウザで開けませんでした: http://127.0.0.1:5555/?t=token" in text
    assert "no association" in text


def test_instructions_are_one_paragraph():
    assert "\n" not in server.INSTRUCTIONS
    assert "show_annotated" in server.INSTRUCTIONS
    assert "five nulls" in server.INSTRUCTIONS
    assert "without buttons or message_box" in server.INSTRUCTIONS


def test_show_annotated_passes_explanation_and_buttons(viewer):
    call("capture_monitor")
    call("show_annotated", {
        "capture_id": "c1", "html": "<div></div>", "explanation": "設定を開く",
        "buttons": [" できた ", "", "分からない"],
    })
    assert viewer.last_extras == ("設定を開く", ["できた", "分からない"], False)


def test_show_annotated_passes_the_message_box_flag(viewer):
    call("capture_monitor")
    call("show_annotated", {"capture_id": "c1", "html": "<div></div>", "message_box": True})
    assert viewer.last_extras == ("", [], True)


def test_show_annotated_defaults_to_no_explanation_or_buttons(viewer):
    call("capture_monitor")
    call("show_annotated", {"capture_id": "c1", "html": "<div></div>"})
    assert viewer.last_extras == ("", [], False)


@pytest.mark.parametrize("buttons, message", [
    (["a", "b", "c", "d", "e", "f", "g"], "6 個まで"),
    (["x" * 31], "30 文字まで"),
    (["できた", "できた"], "同じ名前"),
])
def test_show_annotated_rejects_bad_buttons(viewer, buttons, message):
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": "<div></div>", "buttons": buttons})
    assert result.is_error
    assert message in result.content[0].text
    assert viewer.published == []


def test_wait_for_message_returns_a_button_label_and_fresh_capture(viewer):
    call("capture_window", {"title": "excel"})
    viewer.reply = {"message": "分からない", "via": "button"}
    result = call("wait_for_message", {})
    assert not result.is_error
    image, text = result.content
    assert image.type == "image"
    meta = json.loads(text.text)
    assert (meta["message"], meta["via"]) == ("分からない", "button")
    assert meta["captureId"] == "c2"
    assert meta["source"] == "window:42 Book1 - Excel"
    assert viewer.waited == [90]


def test_wait_for_message_returns_a_typed_message_and_fresh_capture(viewer):
    call("capture_window", {"title": "excel"})
    viewer.reply = {"message": "ブラー+ を引いた", "via": "text"}
    result = call("wait_for_message", {})
    assert not result.is_error
    image, text = result.content
    assert image.type == "image"
    meta = json.loads(text.text)
    assert (meta["message"], meta["via"]) == ("ブラー+ を引いた", "text")
    assert meta["captureId"] == "c2"


def test_wait_for_message_timeout_returns_null(viewer):
    result = call("wait_for_message", {"timeout_seconds": 5})
    assert not result.is_error
    assert [c.type for c in result.content] == ["text"]
    assert json.loads(result.content[0].text) == {"message": None}


@pytest.mark.parametrize("asked, used", [(500, 110), (0, 1), (30, 30)])
def test_wait_for_message_clamps_the_timeout(viewer, asked, used):
    call("wait_for_message", {"timeout_seconds": asked})
    assert viewer.waited == [used]


def test_wait_for_message_reports_viewer_errors(viewer, monkeypatch):
    def no_buttons(timeout):
        raise CaptureError("表示中のページにボタンがありません。")

    monkeypatch.setattr(viewer, "wait_for_message", no_buttons)
    result = call("wait_for_message", {})
    assert result.is_error
    assert "ボタンがありません" in result.content[0].text


def test_recapture_takes_the_same_target_again():
    call("capture_window", {"title": "excel"})
    shrunk, meta = server._recapture(Target("window", 42))
    assert meta["captureId"] == "c2"
    assert server.captures.target("c2") == Target("window", 42)
    assert meta["source"] == "window:42 Book1 - Excel"
    assert shrunk.size == (800, 600)
