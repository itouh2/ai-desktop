import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from fakes import BROWSER, FakeControl

from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta
from ai_desktop.viewer import TOKEN_HEADER, Viewer

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
    viewer = Viewer(
        store, control, settle_seconds=0, after_click_seconds=0, ack_timeout=1.0, heartbeat_seconds=0.2
    )
    yield viewer
    viewer.close()


# --- perform_click ----------------------------------------------------------------------------


def test_click_on_window_capture_follows_the_window(viewer, control):
    assert viewer.perform_click("c2", 10, 20, False) is None
    assert control.calls == [
        ("find_window", "ai-desktop | "),
        ("cursor_pos",),
        ("foreground_window",),
        ("bring_to_front", 42),
        ("window_origin", 42),
        ("click", 110, 220, False),
        ("set_cursor", 5, 6),
        ("restore", BROWSER),
    ]
    assert viewer.next_view(0, 0) is None  # nothing published


def test_cursor_and_browser_wait_after_the_click(store, control):
    viewer = Viewer(
        store, control, settle_seconds=0, after_click_seconds=0.2, ack_timeout=1.0, heartbeat_seconds=0.2
    )
    try:
        viewer.perform_click("c2", 10, 20, False)
    finally:
        viewer.close()
    # time.monotonic() ticks at ~16 ms on Windows, so allow a little slack under the 0.2 s wait.
    assert control.times["set_cursor"] - control.times["click"] >= 0.15
    calls = control.calls
    assert calls.index(("set_cursor", 5, 6)) > calls.index(("click", 110, 220, False))


def test_monitor_click_under_the_browser_minimizes_it(viewer, control):
    viewer.perform_click("c1", 49, 98, True)
    assert ("click", 100, 200, True) in control.calls
    assert control.calls.index(("minimize", BROWSER)) < control.calls.index(("click", 100, 200, True))
    assert not any(call[0] in ("bring_to_front", "window_origin") for call in control.calls)


def test_click_is_skipped_when_the_browser_cannot_be_minimized(viewer, control):
    control.minimize_ok = False
    with pytest.raises(CaptureError, match="最小化できなかった"):
        viewer.perform_click("c1", 49, 98, False)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)
    assert control.calls[-1] == ("restore", BROWSER)


def test_failed_browser_rect_still_restores(viewer, control):
    control.fail_rect = True
    with pytest.raises(CaptureError, match="位置を取得できませんでした"):
        viewer.perform_click("c1", 49, 98, False)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)
    assert control.calls[-1] == ("restore", BROWSER)


def test_monitor_click_beside_the_browser_does_not_minimize_it(viewer, control):
    control.browser_rect = (3840, 0, 7680, 2160)
    viewer.perform_click("c1", 49, 98, False)
    assert not any(call[0] == "minimize" for call in control.calls)
    assert ("click", 100, 200, False) in control.calls
    assert control.calls[-1] == ("restore", BROWSER)


def test_failed_click_still_restores_cursor_and_browser(viewer, control):
    control.fail_origin = True
    with pytest.raises(CaptureError, match="操作対象のウィンドウが見つかりません"):
        viewer.perform_click("c2", 10, 20, False)
    assert control.calls[-1] == ("restore", BROWSER)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)


def test_click_is_skipped_when_the_target_cannot_be_brought_to_front(viewer, control):
    control.front_ok = False
    with pytest.raises(CaptureError, match="前面に出せませんでした"):
        viewer.perform_click("c2", 10, 20, False)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)
    assert control.calls[-1] == ("restore", BROWSER)


def test_click_that_fails_after_moving_restores_the_cursor(viewer, control, monkeypatch):
    def broken_click(x, y, double):
        control.calls.append(("click", x, y, double))
        raise CaptureError("入力を送れませんでした（Win32 エラー 5）。")

    monkeypatch.setattr(control, "click", broken_click)
    with pytest.raises(CaptureError, match="入力を送れませんでした"):
        viewer.perform_click("c2", 10, 20, False)
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]


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
    viewer._pointer.lock.acquire()
    try:
        with pytest.raises(CaptureError, match="ほかの操作を実行中"):
            viewer.perform_click("c2", 10, 20, False)
    finally:
        viewer._pointer.lock.release()


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
    assert (status, result) == (200, {"ok": True})
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
        event = None
        while len(received) < 1:
            line = response.fp.readline().decode("utf-8")
            if line.startswith("event: "):
                event = line[len("event: "):].strip()
            elif line.startswith("data: ") and event == "view":
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


# --- malformed requests ----------------------------------------------------------------------


def test_non_ascii_query_token_is_forbidden_not_a_dropped_connection(viewer):
    viewer.ensure_started()
    status, _, _ = get(viewer, "/", token="%E3%81%82")
    assert status == 403


def test_non_ascii_header_token_is_forbidden(viewer, control):
    viewer.ensure_started()
    body = {"captureId": "c2", "x": 10, "y": 20, "double": False}
    assert post(viewer, "/click", body, token="é")[0] == 403
    assert control.calls == []


def test_invalid_content_length_is_a_bad_request(viewer):
    viewer.ensure_started()
    connection = http.client.HTTPConnection("127.0.0.1", int(viewer.origin.rsplit(":", 1)[1]), timeout=5)
    try:
        connection.putrequest("POST", "/ack")
        connection.putheader("Content-Length", "abc")
        connection.putheader("Origin", viewer.origin)
        connection.putheader(TOKEN_HEADER, viewer.token)
        connection.endheaders()
        assert connection.getresponse().status == 400
    finally:
        connection.close()


def test_ack_with_a_malformed_body_is_a_bad_request(viewer):
    viewer.ensure_started()
    assert post(viewer, "/ack", [1])[0] == 400
    assert post(viewer, "/ack", {"version": "x"})[0] == 400


# --- page messages: buttons ------------------------------------------------------------------


def wait_in_background(viewer, timeout=5.0):
    """Start wait_for_message on a thread; returns (thread, results list)."""
    results = []
    thread = threading.Thread(target=lambda: results.append(viewer.wait_for_message(timeout)), daemon=True)
    thread.start()
    for _ in range(100):  # until the viewer is waiting
        if viewer._state == "waiting":
            break
        time.sleep(0.01)
    return thread, results


def test_publish_carries_explanation_and_buttons(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "説明" * 2500, ["できた", "分からない"])
    view = viewer.next_view(0, 0)
    assert view["explanation"] == ("説明" * 2500)[:4000]
    assert view["buttons"] == ["できた", "分からない"]


def test_press_without_a_waiter_is_rejected(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    with pytest.raises(CaptureError, match="待ち受けていません"):
        viewer.press("できた")
    assert viewer._state == "idle"


def test_wait_requires_a_page_with_buttons(viewer):
    with pytest.raises(CaptureError, match="表示中のページがありません"):
        viewer.wait_for_message(1)
    viewer.publish("c2", "<div></div>", "Excel")
    with pytest.raises(CaptureError, match="入口がありません"):
        viewer.wait_for_message(1)


def test_pressing_a_shown_button_wakes_the_waiter(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた", "分からない"])
    thread, results = wait_in_background(viewer)
    with pytest.raises(CaptureError, match="使えません"):
        viewer.press("やめる")
    viewer.press("分からない")
    thread.join(5)
    assert results == [{"message": "分からない", "via": "button"}]
    assert viewer._state == "thinking"


def test_wait_times_out_back_to_idle(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    assert viewer.wait_for_message(0.05) is None
    assert viewer._state == "idle"


def test_a_newer_wait_cancels_the_older_one(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    first, first_results = wait_in_background(viewer)
    second, second_results = wait_in_background(viewer)
    first.join(5)
    assert first_results == [None]
    viewer.press("できた")
    second.join(5)
    assert second_results == [{"message": "できた", "via": "button"}]


def test_failed_recapture_sets_error_until_the_next_page(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])

    def failing(target):
        assert target == Target("window", 42)
        raise CaptureError("ウィンドウが閉じられました")

    with pytest.raises(CaptureError):
        viewer.recapture_current(failing)
    assert viewer._state == "error"
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    assert viewer._state == "idle"


def test_recapture_current_uses_the_shown_target(viewer):
    viewer.publish("c1", "<div></div>", "Monitor", "", ["できた"])
    assert viewer.recapture_current(lambda target: target) == Target("monitor", 1)


def test_monitor_recapture_moves_the_browser_out_of_the_way(viewer, control):
    viewer.publish("c1", "<div></div>", "Monitor", "", ["できた"])
    assert viewer.recapture_current(lambda target: "shot") == "shot"
    calls = [call for call in control.calls if call[0] in ("minimize", "is_minimized", "restore")]
    assert calls == [("minimize", BROWSER), ("is_minimized", BROWSER), ("restore", BROWSER)]


def test_monitor_recapture_leaves_a_browser_on_another_monitor(viewer, control):
    control.browser_rect = (3840, 0, 7680, 2160)
    viewer.publish("c1", "<div></div>", "Monitor", "", ["できた"])
    assert viewer.recapture_current(lambda target: "shot") == "shot"
    assert not [call for call in control.calls if call[0] == "minimize"]


def test_window_recapture_does_not_touch_the_browser(viewer, control):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    assert viewer.recapture_current(lambda target: "shot") == "shot"
    assert not [call for call in control.calls if call[0] == "find_window"]


def test_monitor_recapture_aborts_when_the_browser_will_not_minimize(store):
    control = FakeControl(minimize_ok=False)
    viewer = Viewer(store, control, settle_seconds=0, after_click_seconds=0, ack_timeout=1.0)
    try:
        viewer.publish("c1", "<div></div>", "Monitor", "", ["できた"])
        recapture_calls = []
        with pytest.raises(CaptureError, match="最小化できなかった"):
            viewer.recapture_current(lambda target: recapture_calls.append(target))
        assert recapture_calls == []
        assert ("restore", BROWSER) in control.calls
        assert viewer._state == "error"
    finally:
        viewer.close()


def test_unexpected_recapture_failure_becomes_a_capture_error(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])

    def failing(target):
        raise OSError("boom")

    with pytest.raises(CaptureError, match="撮り直しに失敗しました"):
        viewer.recapture_current(failing)
    assert viewer._state == "error"


def test_publishing_without_buttons_ends_a_wait(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    thread, results = wait_in_background(viewer)
    for _ in range(100):
        if viewer._state == "waiting":
            break
        time.sleep(0.02)
    viewer.publish("c2", "<div></div>", "Excel", "", None)
    thread.join(5)
    assert results == [None]
    assert viewer._state == "idle"


def test_publishing_after_a_press_leaves_the_thinking_state(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    thread, results = wait_in_background(viewer)
    for _ in range(100):
        if viewer._state == "waiting":
            break
        time.sleep(0.02)
    viewer.press("できた")
    thread.join(5)
    assert viewer._state == "thinking"
    viewer.publish("c2", "<div></div>", "Excel")
    assert viewer._state == "idle"


def test_press_with_a_wrong_host_is_forbidden(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    body = json.dumps({"button": "できた"}, ensure_ascii=False).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", int(viewer.origin.rsplit(":", 1)[1]), timeout=5)
    connection.putrequest("POST", "/press", skip_host=True)
    connection.putheader("Host", "evil.example:80")
    connection.putheader(TOKEN_HEADER, viewer.token)
    connection.putheader("Origin", viewer.origin)
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders(body)
    response = connection.getresponse()
    response.read()
    connection.close()
    assert response.status == 403


def test_press_endpoint_checks_auth_and_state(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    assert post(viewer, "/press", {"button": "できた"}, token="wrong")[0] == 403
    assert post(viewer, "/press", {"button": "できた"}, origin="https://example.com")[0] == 403
    status, result = post(viewer, "/press", {"button": "できた"})
    assert status == 200 and "待ち受けていません" in result["error"]
    assert post(viewer, "/press", {"button": 1})[0] == 400
    thread, results = wait_in_background(viewer)
    assert post(viewer, "/press", {"button": "できた"}) == (200, {"ok": True})
    thread.join(5)
    assert results == [{"message": "できた", "via": "button"}]


def test_events_send_the_state_right_after_connecting(viewer):
    viewer.ensure_started()
    connection = http.client.HTTPConnection("127.0.0.1", int(viewer.origin.rsplit(":", 1)[1]), timeout=5)
    connection.request("GET", f"/events?t={viewer.token}")
    response = connection.getresponse()
    lines = [response.fp.readline().decode("utf-8").strip() for _ in range(2)]
    connection.close()
    assert lines[0] == "event: state"
    assert json.loads(lines[1][len("data: "):])["state"] == "idle"


# --- page messages: message box --------------------------------------------------------------


def test_publish_carries_the_message_box_flag(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", None, True)
    assert viewer.next_view(0, 0)["messageBox"] is True
    viewer.publish("c2", "<div></div>", "Excel")
    assert viewer.next_view(1, 0)["messageBox"] is False


def test_a_message_box_alone_is_enough_to_wait(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", None, True)
    thread, results = wait_in_background(viewer)
    viewer.send_message("  ブラー+ を引いた\n次は？  ")
    thread.join(5)
    assert results == [{"message": "ブラー+ を引いた\n次は？", "via": "text"}]
    assert viewer._state == "thinking"


def test_a_page_without_a_message_box_rejects_typed_messages(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    thread, results = wait_in_background(viewer)
    with pytest.raises(CaptureError, match="入力欄を使えません"):
        viewer.send_message("こんにちは")
    viewer.press("できた")
    thread.join(5)
    assert results == [{"message": "できた", "via": "button"}]


def test_message_without_a_waiter_is_rejected(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"], True)
    with pytest.raises(CaptureError, match="待ち受けていません"):
        viewer.send_message("こんにちは")


@pytest.mark.parametrize("text, message", [("   ", "空です"), ("あ" * 1001, "1000 文字まで")])
def test_empty_or_long_messages_are_rejected(viewer, text, message):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"], True)
    thread, results = wait_in_background(viewer)
    with pytest.raises(CaptureError, match=message):
        viewer.send_message(text)
    assert viewer._state == "waiting"
    viewer.send_message("あ" * 1000)
    thread.join(5)
    assert results == [{"message": "あ" * 1000, "via": "text"}]


def test_publishing_without_any_way_to_send_ends_a_wait(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", None, True)
    thread, results = wait_in_background(viewer)
    viewer.publish("c2", "<div></div>", "Excel")
    thread.join(5)
    assert results == [None]
    assert viewer._state == "idle"


def test_message_endpoint_checks_auth_and_state(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"], True)
    assert post(viewer, "/message", {"text": "やあ"}, token="wrong")[0] == 403
    assert post(viewer, "/message", {"text": "やあ"}, origin="https://example.com")[0] == 403
    status, result = post(viewer, "/message", {"text": "やあ"})
    assert status == 200 and "待ち受けていません" in result["error"]
    assert post(viewer, "/message", {"text": 1})[0] == 400
    thread, results = wait_in_background(viewer)
    assert post(viewer, "/message", {"text": "あ" * 1000}) == (200, {"ok": True})
    thread.join(5)
    assert results == [{"message": "あ" * 1000, "via": "text"}]
