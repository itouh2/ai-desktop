import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta
from ai_desktop.viewer import TOKEN_HEADER, Viewer

BROWSER = 777


class FakeControl:
    """Records every control call in order instead of touching the real desktop."""

    def __init__(self, browser=BROWSER, origin=(100, 200), fail_origin=False):
        self.calls = []
        self.browser = browser
        self.origin = origin
        self.fail_origin = fail_origin

    def find_window(self, fragment):
        self.calls.append(("find_window", fragment))
        return self.browser

    def cursor_pos(self):
        self.calls.append(("cursor_pos",))
        return (5, 6)

    def minimize(self, hwnd):
        self.calls.append(("minimize", hwnd))

    def bring_to_front(self, hwnd):
        self.calls.append(("bring_to_front", hwnd))
        return True

    def window_origin(self, hwnd):
        self.calls.append(("window_origin", hwnd))
        if self.fail_origin:
            raise CaptureError("操作対象のウィンドウが見つかりません。撮影し直してください。")
        return self.origin

    def click(self, x, y, double):
        self.calls.append(("click", x, y, double))

    def set_cursor(self, x, y):
        self.calls.append(("set_cursor", x, y))

    def restore(self, hwnd):
        self.calls.append(("restore", hwnd))


MONITOR_META = build_meta("monitor:1 DISPLAY1", 0, 0, (3200, 1600), (1568, 784), 0.49)
WINDOW_META = build_meta("window:42 Book1 - Excel", -100, 50, (800, 600), (800, 600), 1.0)


@pytest.fixture
def store():
    store = CaptureStore()
    store.add(b"monitor-jpeg", MONITOR_META, Target("monitor", 1))  # c1
    store.add(b"window-jpeg", WINDOW_META, Target("window", 42))  # c2
    return store


@pytest.fixture
def control():
    return FakeControl()


@pytest.fixture
def viewer(store, control):
    def recapture(target):
        meta = WINDOW_META if target.kind == "window" else MONITOR_META
        return store.add(b"fresh-jpeg", meta, target)

    viewer = Viewer(store, recapture, control, settle_seconds=0, ack_timeout=1.0, heartbeat_seconds=0.2)
    yield viewer
    viewer.close()


# --- perform_click ----------------------------------------------------------------------------


def test_click_on_window_capture_follows_the_window(viewer, control):
    new_id = viewer.perform_click("c2", 10, 20, False)
    assert new_id == "c3"
    assert control.calls == [
        ("find_window", "ai-desktop | "),
        ("cursor_pos",),
        ("minimize", BROWSER),
        ("bring_to_front", 42),
        ("window_origin", 42),
        ("click", 110, 220, False),
        ("set_cursor", 5, 6),
        ("restore", BROWSER),
    ]
    assert viewer.next_view(0, 0)["captureId"] == "c3"
    assert viewer.next_view(0, 0)["html"] == ""


def test_double_click_on_monitor_capture_uses_capture_origin(viewer, control):
    viewer.perform_click("c1", 49, 98, True)
    assert ("click", 100, 200, True) in control.calls
    assert not any(call[0] in ("bring_to_front", "window_origin") for call in control.calls)


def test_failed_click_still_restores_cursor_and_browser(viewer, control):
    control.fail_origin = True
    with pytest.raises(CaptureError, match="操作対象のウィンドウが見つかりません"):
        viewer.perform_click("c2", 10, 20, False)
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]
    assert not any(call[0] == "click" for call in control.calls)


def test_click_outside_the_image_is_rejected(viewer, control):
    with pytest.raises(CaptureError, match="画像の外"):
        viewer.perform_click("c2", 800, 10, False)
    assert control.calls == []


def test_click_on_the_viewer_browser_itself_is_rejected(viewer, control):
    control.browser = 42
    with pytest.raises(CaptureError, match="同じウィンドウ"):
        viewer.perform_click("c2", 10, 20, False)
    assert not any(call[0] in ("minimize", "click") for call in control.calls)


def test_only_one_operation_at_a_time(viewer):
    viewer._operating.acquire()
    try:
        with pytest.raises(CaptureError, match="ほかの操作を実行中"):
            viewer.perform_click("c2", 10, 20, False)
    finally:
        viewer._operating.release()


# --- HTTP ------------------------------------------------------------------------------------


def get(viewer, path, token=None):
    token = viewer.token if token is None else token
    separator = "&" if "?" in path else "?"
    try:
        with urllib.request.urlopen(f"{viewer.origin}{path}{separator}t={token}", timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def post(viewer, path, body, token=None, origin=None):
    request = urllib.request.Request(
        f"{viewer.origin}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            TOKEN_HEADER: viewer.token if token is None else token,
            "Origin": viewer.origin if origin is None else origin,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_page_requires_token_and_sends_strict_headers(viewer):
    viewer.ensure_started()
    status, _, _ = get(viewer, "/", token="wrong")
    assert status == 403
    status, headers, body = get(viewer, "/")
    assert status == 200
    csp = headers["Content-Security-Policy"]
    assert "connect-src 'self'" in csp
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">'.encode() in body
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"


def test_image_serves_the_stored_background(viewer):
    viewer.ensure_started()
    status, headers, body = get(viewer, "/image/c2")
    assert (status, headers["Content-Type"], body) == (200, "image/jpeg", b"window-jpeg")
    assert get(viewer, "/image/c99")[0] == 404


def test_click_requires_token_and_same_origin(viewer, control):
    viewer.ensure_started()
    body = {"captureId": "c2", "x": 10, "y": 20, "double": False}
    assert post(viewer, "/click", body, token="wrong")[0] == 403
    assert post(viewer, "/click", body, origin="https://example.com")[0] == 403
    assert control.calls == []
    status, result = post(viewer, "/click", body)
    assert (status, result) == (200, {"ok": True, "captureId": "c3"})
    assert ("click", 110, 220, False) in control.calls


def test_click_errors_come_back_as_messages(viewer):
    viewer.ensure_started()
    status, result = post(viewer, "/click", {"captureId": "c2", "x": 5000, "y": 1})
    assert status == 200
    assert "画像の外" in result["error"]
    assert post(viewer, "/click", {"x": 1})[0] == 400


def test_publish_without_an_open_tab_reports_not_delivered(viewer):
    assert viewer.publish("c2", "<div></div>", "Excel") is False


def test_publish_reaches_an_open_tab_that_acknowledges(viewer):
    viewer.ensure_started()
    received = []
    connected = threading.Event()

    def tab():
        connection = http.client.HTTPConnection("127.0.0.1", int(viewer.origin.rsplit(":", 1)[1]), timeout=5)
        connection.request("GET", f"/events?t={viewer.token}")
        response = connection.getresponse()
        connected.set()
        while len(received) < 1:
            line = response.fp.readline().decode("utf-8")
            if line.startswith("data: "):
                view = json.loads(line[len("data: "):])
                received.append(view)
                post(viewer, "/ack", {"version": view["version"]})
        connection.close()

    thread = threading.Thread(target=tab, daemon=True)
    thread.start()
    assert connected.wait(5)
    for _ in range(50):  # wait until the server has registered the tab
        if viewer._clients:
            break
        time.sleep(0.02)
    assert viewer.publish("c2", '<div class="box"></div>', "Excel") is True
    thread.join(5)
    assert received[0]["captureId"] == "c2"
    assert received[0]["html"] == '<div class="box"></div>'
    assert (received[0]["width"], received[0]["height"]) == (800, 600)
