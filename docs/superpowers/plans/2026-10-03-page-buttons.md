# 注釈ページのボタン（AI が反応する汎用の仕組み） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `show_annotated` で Claude が決めたボタンと説明文を注釈ページに出し、ユーザーが押すと、押されたボタン名と撮り直した画面が `wait_for_button` ツールの結果として Claude に届くようにする。

**Architecture:** ビューアー（`viewer.py`）が状態（idle / waiting / thinking / error）を持ち、SSE の `state` イベントでページに送る。`wait_for_button` はビューアーの待ちにブロックし、ページの POST `/press` で起こされると、MCP サーバーが表示中と同じ対象を撮り直して返す。ページ（`annotate.py`）はボタン欄・状態欄・説明欄を `textContent` で描く。

**Tech Stack:** Python 3.12 / uv / mcp 2.x（`MCPServer`）/ http.server + SSE / pytest

**Global Constraints:**
- 仕様書: `docs/superpowers/specs/2026-10-03-page-buttons-design.md`
- ボタンは最大 6 個、1 つ 30 文字まで、重複不可（前後の空白は除き、空は捨てる）。説明文は 4,000 文字で切り詰める。
- `wait_for_button` の待ちは既定 90 秒、1〜110 秒に丸める（Claude Code の 2 分の自動バックグラウンド化より前に戻すため）。時間切れは `{"pressed": null}`、押されたら `{"pressed": "<ボタン名>", ...撮影メタデータ}` ＋ JPEG。
- 新しい待ちは古い待ちを取り消す（古い方は `None`）。撮り直しはクリックと同じ排他（`_operating`）の中で行う。撮り直し失敗で状態 `error`、次の `show_annotated` で `idle`。
- POST `/press` は既存の `/click` と同じく Host・トークン・Origin を確認する。待ち受けていない／表示中にないボタン名は `{"error": ...}`（日本語）。
- 説明文とボタン名はページで `textContent` を使い、HTML として解釈しない。CSP は変えない。
- ツールのエラーは `ToolError`（`CaptureError` は `_reported()` で変換）。標準出力は MCP 専用。
- テストは `uv run --no-sync pytest`（動いている MCP サーバーが `ai-desktop.exe` を使用中だと、同期付きの `uv run` が失敗するため）。
- コミットメッセージの末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。`.superpowers/`、`smoke-out/`、未追跡の `docs/superpowers/reviews/`、`*.tasks.json` はステージしない。

**User decisions (already made):**
- 「つぎやること」に限定せず、ボタンを押すと AI が反応できる汎用の設計にする。
- ボタンは Claude が `show_annotated` のたびに決める（固定のボタン群・自由入力欄は採らない）。
- 反応を考えるのはチャットの Claude（待ちツールで待つ。追加料金なし。やりとりの間チャットは実行中になる）。
- 撮り直しは MCP サーバーが表示中と同じ対象で行う。説明文はページにも出す。
- 待ちは 1 回 90 秒（上限 110 秒）にする。

**参考実装について:** この計画のコードは、スクラッチの作業ツリーで実装し、pytest 99 件（10 回連続で全件通過）と、MCP サーバー経由の通しテスト（ボタン付き表示 → `wait_for_button` → `/press` → ボタン名と撮り直し画像が返る、時間切れで null、待ち受けていないときの押下はエラー）で確認済みのものをそのまま載せている。

---

## ファイル構成

| パス | 責務 |
|---|---|
| `src/ai_desktop/viewer.py`（変更） | 状態、`wait_for_button`、`press`、`recapture_current`、SSE の `state`、POST `/press`、表示内容の `explanation` と `buttons` |
| `src/ai_desktop/annotate.py`（変更） | ボタン欄・状態欄・説明欄の HTML／CSS／スクリプト |
| `src/ai_desktop/server.py`（変更） | `_recapture` の復活、`show_annotated` の `explanation` と `buttons`、`wait_for_button` ツール、INSTRUCTIONS |
| `scripts/e2e_viewer.py`（変更） | ボタンの通しテストを追加 |
| `README.md`（変更） | 新しいツールと既知の制限 |
| `tests/test_viewer.py`、`tests/test_annotate.py`、`tests/test_server.py`（変更） | 各タスク参照 |

コマンドはすべて `C:\Works\2026\ai-desktop` で実行する（Bash ツールでは `cd /c/Works/2026/ai-desktop`）。作業ブランチは `feature/next-step`。開始時点のテストは 76 件。ファイル全体を置き換える指示は Write ツールで行う（シェルのヒアドキュメントはバックスラッシュを壊すことがある）。

---

### Task 1: ビューアーの状態とボタン待ち

**Goal:** ビューアーに状態（idle / waiting / thinking / error）、ボタン待ち `wait_for_button`、押下 `press`、表示中の対象の撮り直し `recapture_current`、SSE の `state` イベント、POST `/press`、表示内容の `explanation` と `buttons` を加える。

**Files:**
- Modify: `src/ai_desktop/viewer.py`（ファイル全体を置き換え）
- Test: `tests/test_viewer.py`（ファイル全体を置き換え）

**Acceptance Criteria:**
- [ ] `publish(..., explanation, buttons)` が表示内容に `explanation`（4,000 文字で切り詰め）と `buttons` を載せる
- [ ] 待ち受けていないときの `press` は「待ち受けていません」の `CaptureError` で、状態は `idle` のまま
- [ ] 表示中のページがない／ボタンがないときの `wait_for_button` は待たずに `CaptureError`
- [ ] 待ち中に表示中のボタンを押すと待ちが解除されてボタン名が返り、状態が `thinking` になる。表示中にない名前は「使えません」
- [ ] 時間切れで `None` が返り、状態が `idle` に戻る。新しい待ちは古い待ちを `None` で終わらせる
- [ ] 撮り直し失敗で状態が `error` になり、次の `publish` で `idle` に戻る。`recapture_current` は表示中の撮影の `Target` を渡す
- [ ] POST `/press` は不正なトークン・Origin を 403、ボタン名が文字列でなければ 400、待ち中なら `{"ok": true}`
- [ ] SSE は接続直後に `event: state`（`idle`）を送る。既存の SSE テストはイベント種別を見て `view` だけを読む
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync pytest -q` → `86 passed`（`tests/test_viewer.py` を 5 回続けて実行しても全件 PASS）

**Steps:**

- [ ] **Step 1: テストを書く（ファイル全体を置き換える）**

`tests/test_viewer.py` を次の内容に置き換える（既存のテストはすべて含まれている）。

````python
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

    def __init__(
        self,
        browser=BROWSER,
        origin=(100, 200),
        fail_origin=False,
        front_ok=True,
        browser_rect=(0, 0, 1000, 1000),
        minimize_ok=True,
        fail_rect=False,
    ):
        self.calls = []
        self.times = {}
        self.minimize_ok = minimize_ok
        self.fail_rect = fail_rect
        self.browser_rect = browser_rect
        self.front_ok = front_ok
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

    def is_minimized(self, hwnd):
        self.calls.append(("is_minimized", hwnd))
        return self.minimize_ok

    def bring_to_front(self, hwnd):
        self.calls.append(("bring_to_front", hwnd))
        return self.front_ok

    def window_origin(self, hwnd):
        self.calls.append(("window_origin", hwnd))
        if self.fail_origin:
            raise CaptureError("操作対象のウィンドウが見つかりません。撮影し直してください。")
        return self.origin

    def window_rect(self, hwnd):
        self.calls.append(("window_rect", hwnd))
        if self.fail_rect:
            raise CaptureError("ブラウザのウィンドウの位置を取得できませんでした。")
        return self.browser_rect

    def click(self, x, y, double):
        self.calls.append(("click", x, y, double))
        self.times["click"] = time.monotonic()

    def set_cursor(self, x, y):
        self.calls.append(("set_cursor", x, y))
        self.times["set_cursor"] = time.monotonic()

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
    assert not any(call[0] == "click" for call in control.calls)
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]


def test_failed_browser_rect_still_restores(viewer, control):
    control.fail_rect = True
    with pytest.raises(CaptureError, match="位置を取得できませんでした"):
        viewer.perform_click("c1", 49, 98, False)
    assert not any(call[0] == "click" for call in control.calls)
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]


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
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]
    assert not any(call[0] == "click" for call in control.calls)


def test_click_is_skipped_when_the_target_cannot_be_brought_to_front(viewer, control):
    control.front_ok = False
    with pytest.raises(CaptureError, match="前面に出せませんでした"):
        viewer.perform_click("c2", 10, 20, False)
    assert not any(call[0] == "click" for call in control.calls)
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


# --- page buttons ----------------------------------------------------------------------------


def wait_in_background(viewer, timeout=5.0):
    """Start wait_for_button on a thread; returns (thread, results list)."""
    results = []
    thread = threading.Thread(target=lambda: results.append(viewer.wait_for_button(timeout)), daemon=True)
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
        viewer.wait_for_button(1)
    viewer.publish("c2", "<div></div>", "Excel")
    with pytest.raises(CaptureError, match="ボタンがありません"):
        viewer.wait_for_button(1)


def test_pressing_a_shown_button_wakes_the_waiter(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた", "分からない"])
    thread, results = wait_in_background(viewer)
    with pytest.raises(CaptureError, match="使えません"):
        viewer.press("やめる")
    viewer.press("分からない")
    thread.join(5)
    assert results == ["分からない"]
    assert viewer._state == "thinking"


def test_wait_times_out_back_to_idle(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    assert viewer.wait_for_button(0.05) is None
    assert viewer._state == "idle"


def test_a_newer_wait_cancels_the_older_one(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    first, first_results = wait_in_background(viewer)
    second, second_results = wait_in_background(viewer)
    first.join(5)
    assert first_results == [None]
    viewer.press("できた")
    second.join(5)
    assert second_results == ["できた"]


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
    assert results == ["できた"]


def test_events_send_the_state_right_after_connecting(viewer):
    viewer.ensure_started()
    connection = http.client.HTTPConnection("127.0.0.1", int(viewer.origin.rsplit(":", 1)[1]), timeout=5)
    connection.request("GET", f"/events?t={viewer.token}")
    response = connection.getresponse()
    lines = [response.fp.readline().decode("utf-8").strip() for _ in range(2)]
    connection.close()
    assert lines[0] == "event: state"
    assert json.loads(lines[1][len("data: "):])["state"] == "idle"
````

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run --no-sync pytest -q tests/test_viewer.py`
Expected: FAIL（新しいテストが `AttributeError: 'Viewer' object has no attribute 'wait_for_button'` などで失敗する。既存のテストは通る）

- [ ] **Step 3: 実装する（ファイル全体を置き換える）**

`src/ai_desktop/viewer.py` を次の内容に置き換える。

````python
"""Local viewer: shows the annotated capture in one reused browser tab and turns its clicks into real ones."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ai_desktop.annotate import VIEWER_TITLE_PREFIX, content_security_policy, render_shell
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, image_to_screen

_log = logging.getLogger(__name__)

ACK_TIMEOUT_SECONDS = 1.5
HEARTBEAT_SECONDS = 15.0
SETTLE_SECONDS = 0.15  # after minimizing the browser, before the click arrives
AFTER_CLICK_SECONDS = 0.3  # games handle a click on a later frame; keep focus and cursor until then
MAX_BODY_BYTES = 1024
TOKEN_HEADER = "X-AI-Desktop-Token"
MAX_EXPLANATION_CHARS = 4000
NOT_WAITING_MESSAGE = "Claude が待ち受けていません。チャットで、ボタンで進めたいと頼んでください。"
UNKNOWN_BUTTON_MESSAGE = "そのボタンは今は使えません。"


def _token_matches(candidate: str, token: str) -> bool:
    return secrets.compare_digest(candidate.encode("utf-8"), token.encode("utf-8"))


class _ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001 - stdlib signature
        _log.exception("viewer request from %s failed", client_address)


class Viewer:
    """Serves the current view to browser tabs over SSE and performs clicks sent back from them.

    control is the ai_desktop.control module in production; tests pass a fake with the same
    functions (find_window, cursor_pos, minimize, is_minimized, bring_to_front, window_origin,
    window_rect, click, set_cursor, restore)."""

    def __init__(
        self,
        store: CaptureStore,
        control: Any,
        settle_seconds: float = SETTLE_SECONDS,
        after_click_seconds: float = AFTER_CLICK_SECONDS,
        ack_timeout: float = ACK_TIMEOUT_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self._store = store
        self._control = control
        self._settle_seconds = settle_seconds
        self._after_click_seconds = after_click_seconds
        self._ack_timeout = ack_timeout
        self.heartbeat_seconds = heartbeat_seconds
        self.token = secrets.token_urlsafe(24)
        self._server: ThreadingHTTPServer | None = None
        self._changed = threading.Condition()
        self._view: dict | None = None
        self._version = 0
        self._acked = 0
        self._clients = 0
        self._operating = threading.Lock()
        self._state = "idle"
        self._state_version = 1  # new tabs receive the current state right away
        self._wait_generation = 0
        self._pressed: str | None = None

    # --- lifecycle -------------------------------------------------------------------------

    def ensure_started(self) -> None:
        with self._changed:
            if self._server is not None:
                return
            server = _ViewerServer(("127.0.0.1", 0), _handler_for(self))
            threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.05}, name="ai-desktop-viewer", daemon=True
            ).start()
            self._server = server

    def close(self) -> None:
        with self._changed:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    @property
    def origin(self) -> str:
        assert self._server is not None, "viewer is not started"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def url(self) -> str:
        return f"{self.origin}/?t={self.token}"

    # --- showing ---------------------------------------------------------------------------

    def publish(
        self, capture_id: str, html: str, title: str, explanation: str = "", buttons: list[str] | None = None
    ) -> bool:
        """Make this the current view; True when an open tab confirmed it within the timeout."""
        _, meta = self._store.get(capture_id)
        self.ensure_started()
        with self._changed:
            self._version += 1
            version = self._version
            self._view = {
                "version": version,
                "captureId": capture_id,
                "width": meta["imageWidth"],
                "height": meta["imageHeight"],
                "html": html,
                "title": title,
                "explanation": explanation[:MAX_EXPLANATION_CHARS],
                "buttons": list(buttons or []),
            }
            if self._state in ("thinking", "error"):
                self._set_state("idle")
            self._changed.notify_all()
            if self._clients == 0:
                return False
            return self._changed.wait_for(lambda: self._acked >= version, timeout=self._ack_timeout)

    def focus_browser(self) -> None:
        hwnd = self._control.find_window(VIEWER_TITLE_PREFIX)
        if hwnd is not None:
            self._control.bring_to_front(hwnd)

    def open_browser(self) -> None:
        os.startfile(self.url)

    # --- page buttons ----------------------------------------------------------------------

    def wait_for_button(self, timeout: float) -> str | None:
        """Block until a page button is pressed; its label, or None on timeout.

        A newer wait cancels an older one, which then returns None, so a wait left over
        from an interrupted turn cannot block the next one."""
        with self._changed:
            if self._view is None:
                raise CaptureError("表示中のページがありません。先に show_annotated で表示してください。")
            if not self._view["buttons"]:
                raise CaptureError("表示中のページにボタンがありません。show_annotated に buttons を付けてください。")
            self._wait_generation += 1
            generation = self._wait_generation
            self._pressed = None
            self._set_state("waiting")
            done = lambda: self._pressed is not None or self._wait_generation != generation  # noqa: E731
            self._changed.wait_for(done, timeout=timeout)
            if self._wait_generation != generation:
                return None
            if self._pressed is not None:
                label, self._pressed = self._pressed, None
                return label
            self._set_state("idle")
            return None

    def press(self, label: str) -> None:
        """A page button was pressed; wakes the waiting tool call."""
        with self._changed:
            if self._state != "waiting":
                raise CaptureError(NOT_WAITING_MESSAGE)
            if self._view is None or label not in self._view["buttons"]:
                raise CaptureError(UNKNOWN_BUTTON_MESSAGE)
            self._pressed = label
            self._set_state("thinking")

    def recapture_current(self, recapture: Callable[[Target], Any]) -> Any:
        """Capture the target of the view on screen again (waits for a click in progress)."""
        with self._operating:
            with self._changed:
                if self._view is None:
                    raise CaptureError("表示中のページがありません。先に show_annotated で表示してください。")
                capture_id = self._view["captureId"]
            try:
                return recapture(self._store.target(capture_id))
            except CaptureError:
                with self._changed:
                    self._set_state("error")
                raise

    def _set_state(self, state: str) -> None:
        """Caller holds self._changed."""
        self._state = state
        self._state_version += 1
        self._changed.notify_all()

    # --- clicking --------------------------------------------------------------------------

    def perform_click(self, capture_id: str, x: float, y: float, double: bool) -> None:
        """Click the real screen where (x, y) is on the capture. The page is left as it is."""
        if not self._operating.acquire(blocking=False):
            raise CaptureError("ほかの操作を実行中です。終わるまで待ってください。")
        try:
            _, meta = self._store.get(capture_id)
            target = self._store.target(capture_id)
            if not (0 <= x < meta["imageWidth"] and 0 <= y < meta["imageHeight"]):
                raise CaptureError("クリック位置が画像の外です。")
            browser = self._control.find_window(VIEWER_TITLE_PREFIX)
            if target.kind == "window" and target.id == browser:
                raise CaptureError(
                    "表示中のブラウザと同じウィンドウは操作できません。対象のタブを別のウィンドウに分けてください。"
                )
            cursor = self._control.cursor_pos()
            try:
                origin = None
                if target.kind == "window":
                    # Bringing the target to the front also lifts it above the browser.
                    if not self._control.bring_to_front(target.id):
                        raise CaptureError("対象のウィンドウを前面に出せませんでした。もう一度クリックしてください。")
                    origin = self._control.window_origin(target.id)
                screen_x, screen_y = image_to_screen(meta, x, y, origin)
                if browser is not None and target.kind == "monitor":
                    left, top, right, bottom = self._control.window_rect(browser)
                    if left <= screen_x < right and top <= screen_y < bottom:
                        self._control.minimize(browser)
                        time.sleep(self._settle_seconds)
                        if not self._control.is_minimized(browser):
                            raise CaptureError("ブラウザを最小化できなかったため、クリックしませんでした。")
                self._control.click(screen_x, screen_y, double)
                time.sleep(self._after_click_seconds)
            finally:
                self._control.set_cursor(*cursor)
                if browser is not None:
                    self._control.restore(browser)
        finally:
            self._operating.release()

    # --- used by the request handler -------------------------------------------------------

    def background(self, capture_id: str) -> bytes:
        return self._store.get(capture_id)[0]

    def register_client(self) -> None:
        with self._changed:
            self._clients += 1

    def unregister_client(self) -> None:
        with self._changed:
            self._clients -= 1

    def acknowledge(self, version: int) -> None:
        with self._changed:
            if version > self._acked:
                self._acked = version
                self._changed.notify_all()

    def next_update(self, seen_view: int, seen_state: int, timeout: float) -> tuple[dict | None, dict | None]:
        """(view, state) entries newer than the versions seen, or (None, None) after timeout."""
        with self._changed:

            def changed() -> bool:
                newer_view = self._view is not None and self._view["version"] > seen_view
                return newer_view or self._state_version > seen_state

            if not self._changed.wait_for(changed, timeout=timeout):
                return None, None
            view = dict(self._view) if self._view is not None and self._view["version"] > seen_view else None
            state = (
                {"version": self._state_version, "state": self._state} if self._state_version > seen_state else None
            )
            return view, state

    def next_view(self, seen_version: int, timeout: float) -> dict | None:
        """The current view once it is newer than seen_version, or None after timeout."""
        with self._changed:
            newer = lambda: self._view is not None and self._view["version"] > seen_version  # noqa: E731
            if self._changed.wait_for(newer, timeout=timeout):
                return dict(self._view)
            return None


def _handler_for(viewer: Viewer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            _log.debug(format, *args)

        def do_GET(self) -> None:  # noqa: N802 - stdlib name
            parts = urlsplit(self.path)
            token = parse_qs(parts.query).get("t", [""])[0]
            if not (self._host_ok() and _token_matches(token, viewer.token)):
                self._send(403, "text/plain; charset=utf-8", b"forbidden")
            elif parts.path == "/":
                nonce = secrets.token_urlsafe(16)
                page = render_shell(nonce).encode("utf-8")
                self._send(200, "text/html; charset=utf-8", page, content_security_policy(nonce))
            elif parts.path == "/events":
                self._stream_events()
            elif parts.path.startswith("/image/"):
                try:
                    data = viewer.background(parts.path[len("/image/"):])
                except CaptureError:
                    self._send(404, "text/plain; charset=utf-8", b"not found")
                else:
                    self._send(200, "image/jpeg", data)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            path = urlsplit(self.path).path
            raw_length = (self.headers.get("Content-Length") or "0").strip()
            if not (raw_length.isascii() and raw_length.isdigit()):
                self.close_connection = True
                self._send_json(400, {"error": "要求の形式が正しくありません。"})
                return
            length = int(raw_length)
            if length > MAX_BODY_BYTES:
                self.close_connection = True
                self._send_json(413, {"error": "要求が大きすぎます。"})
                return
            raw = self.rfile.read(length)  # read before replying, even to reject
            token_ok = _token_matches(self.headers.get(TOKEN_HEADER, ""), viewer.token)
            if not (self._host_ok() and token_ok and self.headers.get("Origin") == viewer.origin):
                self._send_json(403, {"error": "forbidden"})
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._send_json(400, {"error": "要求の形式が正しくありません。"})
                return
            if not isinstance(body, dict):
                self._send_json(400, {"error": "要求の形式が正しくありません。"})
                return
            if path == "/ack":
                version = body.get("version", 0)
                if not isinstance(version, int) or isinstance(version, bool):
                    self._send_json(400, {"error": "要求の形式が正しくありません。"})
                    return
                viewer.acknowledge(version)
                self._send_json(200, {"ok": True})
            elif path == "/click":
                self._click(body)
            elif path == "/press":
                label = body.get("button")
                if not isinstance(label, str):
                    self._send_json(400, {"error": "要求の形式が正しくありません。"})
                    return
                try:
                    viewer.press(label)
                except CaptureError as error:
                    self._send_json(200, {"error": str(error)})
                else:
                    self._send_json(200, {"ok": True})
            else:
                self._send_json(404, {"error": "not found"})

        def _click(self, body: dict) -> None:
            try:
                viewer.perform_click(
                    str(body["captureId"]), float(body["x"]), float(body["y"]), bool(body.get("double", False))
                )
            except CaptureError as error:
                self._send_json(200, {"error": str(error)})
            except (KeyError, TypeError, ValueError):
                self._send_json(400, {"error": "要求の形式が正しくありません。"})
            except Exception:
                _log.exception("click failed")
                self._send_json(500, {"error": "操作中に予期しないエラーが起きました。"})
            else:
                self._send_json(200, {"ok": True})

        def _stream_events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self._common_headers()
            self.end_headers()
            viewer.register_client()
            try:
                seen_view = seen_state = 0
                while True:
                    view, state = viewer.next_update(seen_view, seen_state, viewer.heartbeat_seconds)
                    if view is None and state is None:
                        self.wfile.write(b": ping\n\n")
                    if view is not None:
                        seen_view = view["version"]
                        data = json.dumps(view, ensure_ascii=False)
                        self.wfile.write(f"event: view\ndata: {data}\n\n".encode("utf-8"))
                    if state is not None:
                        seen_state = state["version"]
                        data = json.dumps(state, ensure_ascii=False)
                        self.wfile.write(f"event: state\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except OSError:
                pass  # the tab was closed
            finally:
                viewer.unregister_client()

        def _host_ok(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_address[1]}"

        def _common_headers(self, csp: str | None = None) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            if csp is not None:
                self.send_header("Content-Security-Policy", csp)

        def _send(self, status: int, content_type: str, body: bytes, csp: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._common_headers(csp)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body)

    return Handler
````

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run --no-sync pytest -q`
Expected: `86 passed`

- [ ] **Step 5: 安定性を確認する**

Run: `for i in $(seq 5); do uv run --no-sync pytest -q tests/test_viewer.py | tail -1; done`
Expected: 5 回とも全件 PASS

- [ ] **Step 6: コミットする**

````bash
git add src/ai_desktop/viewer.py tests/test_viewer.py
git commit -F - <<'EOF'
feat: add page-button state, waiting and /press to the viewer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
````

---

### Task 2: ページのボタン欄と説明欄

**Goal:** 注釈ページに、Claude のボタンを並べる上部のバー（状態の文言つき）と、画像の横の説明欄を加え、SSE の `state` に応じてボタンを有効・無効にし、押したら POST `/press` を送る。

**Files:**
- Modify: `src/ai_desktop/annotate.py`（ファイル全体を置き換え）
- Test: `tests/test_annotate.py`（ファイル全体を置き換え）

**Acceptance Criteria:**
- [ ] シェルに `<div id="bar" hidden><span id="buttons"></span><span id="bar-state"></span></div>` と `<aside id="side" hidden></aside>` がある
- [ ] ボタン名は `button.textContent = label;`、説明は `side.textContent = next.explanation || "";` で入れる（HTML として解釈しない）
- [ ] 押すと `post("/press", {button: label})` を送り、`state` イベントで表示を更新する
- [ ] ボタンがないときはバーを、説明が空のときは説明欄を隠す。画像の拡大縮小は `#viewport` の幅を基準にする
- [ ] CSP（`content_security_policy`）は変わらない
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync pytest -q` → `87 passed`

**Steps:**

- [ ] **Step 1: テストを書く（ファイル全体を置き換える）**

`tests/test_annotate.py` を次の内容に置き換える（既存のテストはすべて含まれている）。

````python
from ai_desktop.annotate import VIEWER_TITLE_PREFIX, content_security_policy, render_shell


def test_viewer_csp_allows_only_own_script_and_same_origin():
    assert content_security_policy("n0nce") == (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        "script-src 'nonce-n0nce'; connect-src 'self'"
    )


def test_viewer_shell_has_nonce_script_and_empty_stage():
    page = render_shell("n0nce")
    assert '<script nonce="n0nce">' in page
    assert page.index('<script nonce="n0nce">') < page.index("</head>")
    assert '<div id="status"></div>' in page
    assert '<div id="stage"><img id="shot" alt=""><div id="annotations"></div></div>' in page
    assert 'new EventSource("/events?t="' in page
    assert '"X-AI-Desktop-Token": token' in page


def test_success_status_timer_is_cancelled_by_later_statuses():
    page = render_shell("n0nce")
    assert "let statusTimer = null;" in page
    assert "clearTimeout(statusTimer)" in page
    assert "statusTimer = setTimeout(" in page


def test_viewer_shell_keeps_helper_classes_and_title_prefix():
    page = render_shell("n0nce")
    for selector in ("#annotations .box", "#annotations .badge", "#annotations .note", "#annotations .arrow"):
        assert selector in page
    assert 'id="arrowhead"' in page
    assert VIEWER_TITLE_PREFIX == "ai-desktop | "
    assert 'document.title = "ai-desktop | " + next.title' in page


def test_clicks_on_notes_and_badges_are_not_forwarded():
    page = render_shell("n0nce")
    assert 'event.target.closest("#annotations .note, #annotations .badge, #annotations a, #annotations button")' in page
    assert "吹き出しや番号の上はクリックしても送信しません" in page
    assert ".box" not in page.split('event.target.closest("')[1].split('")')[0]


def test_viewer_shell_has_button_bar_and_explanation_panel():
    page = render_shell("n0nce")
    assert '<div id="bar" hidden><span id="buttons"></span><span id="bar-state"></span></div>' in page
    assert '<aside id="side" hidden></aside>' in page
    assert "button.textContent = label;" in page
    assert 'side.textContent = next.explanation || "";' in page
    assert 'post("/press", {button: label})' in page
    assert 'events.addEventListener("state"' in page
````

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run --no-sync pytest -q tests/test_annotate.py`
Expected: FAIL（`test_viewer_shell_has_button_bar_and_explanation_panel` が失敗する）

- [ ] **Step 3: 実装する（ファイル全体を置き換える）**

`src/ai_desktop/annotate.py` を次の内容に置き換える。

````python
"""The viewer page: a capture as background with Claude's HTML on top, updated live."""

from __future__ import annotations

_CSS = """
html, body { margin: 0; background: #1e1e1e; }
html { overflow-y: scroll; }
#viewport { position: relative; width: 100%; overflow: hidden; }
#stage { position: relative; transform-origin: 0 0; }
#shot { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
#annotations { position: absolute; inset: 0; font-family: system-ui, "Yu Gothic UI", sans-serif; }
#annotations .box { position: absolute; box-sizing: border-box; border: 3px solid #e5484d;
  border-radius: 6px; box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.7); }
#annotations .badge { position: absolute; width: 28px; height: 28px; margin: -14px 0 0 -14px;
  border-radius: 50%; background: #e5484d; color: #fff; font: 700 15px/28px system-ui, sans-serif;
  text-align: center; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4); }
#annotations .note { position: absolute; max-width: 320px; padding: 8px 12px;
  background: rgba(255, 255, 255, 0.96); color: #1a1a1a; border-left: 4px solid #e5484d;
  border-radius: 6px; font-size: 14px; line-height: 1.5; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35); }
#annotations svg.layer { position: absolute; inset: 0; width: 100%; height: 100%;
  overflow: visible; pointer-events: none; }
#annotations .arrow { fill: none; stroke: #e5484d; stroke-width: 4; stroke-linecap: round;
  marker-end: url(#arrowhead); }
"""

_ARROWHEAD = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
    '<marker id="arrowhead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
    'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#e5484d"/>'
    "</marker></defs></svg>"
)

VIEWER_TITLE_PREFIX = "ai-desktop | "

_VIEWER_CSS = """
#stage { cursor: crosshair; }
#status { position: fixed; top: 12px; right: 12px; z-index: 10; display: none; padding: 8px 14px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.78); color: #fff;
  font: 14px/1.5 system-ui, "Yu Gothic UI", sans-serif; }
#status.show { display: block; }
#status.error { background: #e5484d; }
#layout { display: flex; flex-wrap: wrap; align-items: flex-start; }
#main { flex: 1 1 640px; min-width: 0; }
#side { flex: 0 1 340px; box-sizing: border-box; padding: 14px 16px; color: #eee;
  font: 15px/1.7 system-ui, "Yu Gothic UI", sans-serif; white-space: pre-wrap; }
#bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 12px;
  background: #2a2a2a; font: 14px system-ui, "Yu Gothic UI", sans-serif; }
#bar[hidden], #side[hidden] { display: none; }
#bar button { padding: 6px 14px; border: 0; border-radius: 6px; background: #e5484d; color: #fff;
  font: inherit; font-weight: 700; cursor: pointer; }
#bar button:disabled { background: #555; color: #aaa; cursor: default; }
#bar-state { margin-left: auto; color: #ccc; }
"""

# The live viewer: receives views over SSE, scales the stage, and posts clicks back.
_VIEWER_SCRIPT = """
const token = new URLSearchParams(location.search).get("t");
let view = null;
let busy = false;
let pending = null;
let statusTimer = null;
let buttonState = "idle";
const STATE_TEXT = {
  waiting: "",
  thinking: "考え中…",
  idle: "Claude が待ち受けると押せます",
  error: "撮影できませんでした。チャットを確認してください",
};

function fit() {
  if (!view) return;
  const viewport = document.getElementById("viewport");
  const scale = viewport.clientWidth / view.width;
  document.getElementById("stage").style.transform = "scale(" + scale + ")";
  viewport.style.height = view.height * scale + "px";
}

function renderButtons() {
  const labels = view ? view.buttons : [];
  document.getElementById("bar").hidden = labels.length === 0;
  document.getElementById("buttons").replaceChildren(...labels.map((label) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = buttonState !== "waiting";
    button.addEventListener("click", () => press(label));
    return button;
  }));
  document.getElementById("bar-state").textContent = STATE_TEXT[buttonState] || "";
}

async function press(label) {
  for (const button of document.querySelectorAll("#buttons button")) button.disabled = true;
  try {
    const response = await post("/press", {button: label});
    const result = await response.json();
    if (result.error) {
      renderButtons();
      document.getElementById("bar-state").textContent = result.error;
    }
  } catch (error) {
    renderButtons();
    document.getElementById("bar-state").textContent = "送信できませんでした: " + error;
  }
}

function status(text, isError) {
  clearTimeout(statusTimer);
  const box = document.getElementById("status");
  box.textContent = text;
  box.className = text ? (isError ? "show error" : "show") : "";
}

function render(next) {
  view = next;
  document.title = "ai-desktop | " + next.title;
  const stage = document.getElementById("stage");
  stage.style.width = next.width + "px";
  stage.style.height = next.height + "px";
  document.getElementById("shot").src =
    "/image/" + encodeURIComponent(next.captureId) + "?t=" + encodeURIComponent(token);
  document.getElementById("annotations").innerHTML = next.html;
  const side = document.getElementById("side");
  side.textContent = next.explanation || "";
  side.hidden = !next.explanation;
  renderButtons();
  status("", false);
  fit();
}

function post(path, body) {
  return fetch(path + "?t=" + encodeURIComponent(token), {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-AI-Desktop-Token": token},
    body: JSON.stringify(body),
  });
}

async function operate(event, double) {
  if (!view || busy) return;
  const rect = document.getElementById("stage").getBoundingClientRect();
  const scale = rect.width / view.width;
  const x = (event.clientX - rect.left) / scale;
  const y = (event.clientY - rect.top) / scale;
  busy = true;
  status(double ? "ダブルクリック中…" : "クリック中…", false);
  try {
    const response = await post("/click", {captureId: view.captureId, x: x, y: y, double: double});
    const result = await response.json();
    if (result.error) {
      status(result.error, true);
    } else {
      status("クリックしました（ページは更新されません）", false);
      statusTimer = setTimeout(() => status("", false), 1500);
    }
  } catch (error) {
    status("操作できませんでした: " + error, true);
  } finally {
    busy = false;
  }
}

addEventListener("DOMContentLoaded", () => {
  document.getElementById("stage").addEventListener("click", (event) => {
    clearTimeout(pending);
    if (event.target.closest("#annotations .note, #annotations .badge, #annotations a, #annotations button")) {
      status("吹き出しや番号の上はクリックしても送信しません", false);
      statusTimer = setTimeout(() => status("", false), 1500);
      return;
    }
    if (event.detail >= 2) {
      operate(event, true);
      return;
    }
    pending = setTimeout(() => operate(event, false), 300);
  });
  const events = new EventSource("/events?t=" + encodeURIComponent(token));
  events.addEventListener("view", (event) => {
    const next = JSON.parse(event.data);
    render(next);
    post("/ack", {version: next.version});
  });
  events.addEventListener("state", (event) => {
    buttonState = JSON.parse(event.data).state;
    renderButtons();
  });
  events.addEventListener("error", () => {
    status("サーバーとの接続が切れました。Claude Code のセッションを確認してください。", true);
  });
});
addEventListener("resize", fit);
"""


def content_security_policy(nonce: str) -> str:
    """CSP for the viewer page: only its own nonce'd script, same-origin images and requests."""
    return (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        f"script-src 'nonce-{nonce}'; connect-src 'self'"
    )


def render_shell(nonce: str) -> str:
    """The viewer page skeleton; content arrives over /events and is drawn by the script."""
    return (
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        "<title>ai-desktop</title>\n"
        f"<style>{_CSS}{_VIEWER_CSS}</style>\n"
        f'<script nonce="{nonce}">{_VIEWER_SCRIPT}</script>\n'
        "</head><body>\n"
        f"{_ARROWHEAD}\n"
        '<div id="status"></div>\n'
        '<div id="layout"><div id="main">\n'
        '<div id="bar" hidden><span id="buttons"></span><span id="bar-state"></span></div>\n'
        '<div id="viewport"><div id="stage">'
        '<img id="shot" alt="">'
        '<div id="annotations"></div>'
        "</div></div>\n"
        '</div><aside id="side" hidden></aside></div>\n'
        "</body></html>\n"
    )
````

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run --no-sync pytest -q`
Expected: `87 passed`

- [ ] **Step 5: コミットする**

````bash
git add src/ai_desktop/annotate.py tests/test_annotate.py
git commit -F - <<'EOF'
feat: show Claude's buttons and explanation on the viewer page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
````

---

### Task 3: サーバーのツール（buttons・explanation・wait_for_button）

**Goal:** `show_annotated` に `explanation` と `buttons` を加え、ボタン待ちツール `wait_for_button` と撮り直し関数 `_recapture` を追加し、INSTRUCTIONS に使い方を書き足す。

**Files:**
- Modify: `src/ai_desktop/server.py`（ファイル全体を置き換え）
- Test: `tests/test_server.py`（ファイル全体を置き換え）

**Acceptance Criteria:**
- [ ] ツールが 6 つ（既存 5 つ＋`wait_for_button`）になる
- [ ] `show_annotated` が `explanation`（省略時は空）と、空白除去・空除去したボタン名を `viewer.publish` に渡す。7 個以上・30 文字超・重複はツールエラーで、publish されない
- [ ] `wait_for_button` が、押されたら JPEG と `pressed` 付きメタデータ（新しい `captureId`）を、時間切れなら `{"pressed": null}` だけを返す
- [ ] `timeout_seconds` を 1〜110 に丸める（500→110、0→1、既定 90）
- [ ] ビューアーの `CaptureError` はメッセージ付きのツールエラーになる
- [ ] `_recapture(target)` が同じ対象を撮り直し、`(縮小画像, メタデータ)` を返す
- [ ] INSTRUCTIONS が 1 段落のまま、`buttons`・`wait_for_button`・`{"pressed": null}` の扱いに触れている
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync pytest -q` → `99 passed`

**Steps:**

- [ ] **Step 1: テストを書く（ファイル全体を置き換える）**

`tests/test_server.py` を次の内容に置き換える（既存のテストはすべて含まれている）。

````python
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
        "wait_for_button",
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
        self.pressed = None
        self.waited = []
        self.target = Target("window", 42)

    def publish(self, capture_id, html, title, explanation="", buttons=None):
        if self.start_error is not None:
            raise self.start_error
        self.published.append((capture_id, html, title))
        self.last_extras = (explanation, buttons)
        return self.delivered

    def wait_for_button(self, timeout):
        self.waited.append(timeout)
        return self.pressed

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



def test_show_annotated_passes_explanation_and_buttons(viewer):
    call("capture_monitor")
    call("show_annotated", {
        "capture_id": "c1", "html": "<div></div>", "explanation": "設定を開く",
        "buttons": [" できた ", "", "分からない"],
    })
    assert viewer.last_extras == ("設定を開く", ["できた", "分からない"])


def test_show_annotated_defaults_to_no_explanation_or_buttons(viewer):
    call("capture_monitor")
    call("show_annotated", {"capture_id": "c1", "html": "<div></div>"})
    assert viewer.last_extras == ("", [])


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


def test_wait_for_button_returns_label_and_fresh_capture(viewer):
    call("capture_window", {"title": "excel"})
    viewer.pressed = "分からない"
    result = call("wait_for_button", {})
    assert not result.is_error
    image, text = result.content
    assert image.type == "image"
    meta = json.loads(text.text)
    assert meta["pressed"] == "分からない"
    assert meta["captureId"] == "c2"
    assert meta["source"] == "window:42 Book1 - Excel"
    assert viewer.waited == [90]


def test_wait_for_button_timeout_returns_null(viewer):
    result = call("wait_for_button", {"timeout_seconds": 5})
    assert not result.is_error
    assert [c.type for c in result.content] == ["text"]
    assert json.loads(result.content[0].text) == {"pressed": None}


@pytest.mark.parametrize("asked, used", [(500, 110), (0, 1), (30, 30)])
def test_wait_for_button_clamps_the_timeout(viewer, asked, used):
    call("wait_for_button", {"timeout_seconds": asked})
    assert viewer.waited == [used]


def test_wait_for_button_reports_viewer_errors(viewer, monkeypatch):
    def no_buttons(timeout):
        raise CaptureError("表示中のページにボタンがありません。")

    monkeypatch.setattr(viewer, "wait_for_button", no_buttons)
    result = call("wait_for_button", {})
    assert result.is_error
    assert "ボタンがありません" in result.content[0].text


def test_recapture_takes_the_same_target_again():
    call("capture_window", {"title": "excel"})
    shrunk, meta = server._recapture(Target("window", 42))
    assert meta["captureId"] == "c2"
    assert server.captures.target("c2") == Target("window", 42)
    assert meta["source"] == "window:42 Book1 - Excel"
    assert shrunk.size == (800, 600)
````

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run --no-sync pytest -q tests/test_server.py`
Expected: FAIL（`test_exposes_six_tools` や `wait_for_button` 系のテストが失敗する）

- [ ] **Step 3: 実装する（ファイル全体を置き換える）**

`src/ai_desktop/server.py` を次の内容に置き換える。

````python
"""MCP server that lets Claude Code see the user's Windows desktop."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from ai_desktop import capture, control
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta, encode_jpeg, select_window, shrink
from ai_desktop.viewer import Viewer

INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels). To point at things on screen, call \
show_annotated with the capture's captureId and HTML positioned in that image's pixel \
coordinates; it shows in the user's browser, reusing the open viewer tab, and the user \
can click on the page to click the real screen. When an interaction on that page helps \
(guiding steps, letting the user pick an option, getting a confirmation), pass buttons \
(and an explanation) to show_annotated and call wait_for_button; you get the pressed \
label plus a fresh capture of the same target, so react to it and, to keep going, show \
new buttons and wait again. If it returns {"pressed": null}, just call it again; stop \
when the user starts talking about something else in the chat."""

mcp = MCPServer("ai-desktop", instructions=INSTRUCTIONS)
BACKGROUND_JPEG_QUALITY = 90
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


viewer = Viewer(captures, control)


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
    html: str,
    title: str | None = None,
    explanation: str | None = None,
    buttons: list[str] | None = None,
) -> str:
    """Show the user one of your captures with your annotations drawn on top, in their
    default browser. Use it when pointing at places on screen makes your advice clearer.
    An open viewer tab is reused. The user can click or double-click on the page to click
    the real screen at that spot; the page itself is not refreshed (annotations stay),
    so capture again to see the result.

    capture_id: the captureId from a capture's metadata (the latest 10 are kept).
    html: elements positioned absolutely with style left/top in that capture's image
    pixels (imageWidth x imageHeight, i.e. the image you saw). Helper classes:
    .box (outline; left/top/width/height), .badge (numbered circle; left/top is its
    center), .note (callout; left/top is its top-left corner), and for arrows
    <svg class="layer"><line class="arrow" x1=".." y1=".." x2=".." y2=".."/></svg>
    (svg.layer covers the image, in image pixels). Scripts and external resources are
    blocked. title: optional page title. explanation: optional plain text shown beside the
    image. buttons: optional labels (up to 6, 30 chars each) shown above the image; after
    showing them, call wait_for_button to learn which one the user pressed."""
    if not html.strip():
        raise ToolError("html が空です。枠や注釈の HTML を指定してください。")
    if len(html) > MAX_HTML_CHARS:
        raise ToolError(f"html が長すぎます（{len(html)} 文字）。{MAX_HTML_CHARS} 文字以内にしてください。")
    labels = _clean_buttons(buttons)
    with _reported():
        _, meta = captures.get(capture_id)
        try:
            delivered = viewer.publish(capture_id, html, title or meta["source"], explanation or "", labels)
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
def wait_for_button(timeout_seconds: int = WAIT_DEFAULT_SECONDS) -> list[Image | str]:
    """Wait until the user presses one of the buttons on the page shown by show_annotated
    (call it right after showing buttons). Returns {"pressed": "<label>", ...metadata} plus a
    fresh JPEG of the same window or monitor, taken when the button was pressed. Returns
    {"pressed": null} after timeout_seconds (1-110, default 90); then just call it again."""
    timeout = max(1, min(WAIT_MAX_SECONDS, int(timeout_seconds)))
    with _reported():
        label = viewer.wait_for_button(timeout)
        if label is None:
            return [json.dumps({"pressed": None})]
        shrunk, meta = viewer.recapture_current(_recapture)
    result = {"pressed": label, **meta}
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(result, ensure_ascii=False)]


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    capture.enable_dpi_awareness()
    mcp.run()
````

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run --no-sync pytest -q`
Expected: `99 passed`

- [ ] **Step 5: コミットする**

````bash
git add src/ai_desktop/server.py tests/test_server.py
git commit -F - <<'EOF'
feat: add buttons/explanation to show_annotated and the wait_for_button tool

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
````

---

### Task 4: README と実機の通しテスト

**Goal:** README に新しい使い方と既知の制限を書き、MCP サーバー経由の通しテスト（ボタン付き表示 → `wait_for_button` → `/press` → ボタン名と撮り直し画像）を実行して、最後にユーザーに VS Code で試してもらう。

**Files:**
- Modify: `scripts/e2e_viewer.py`（ファイル全体を置き換え）
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-03-page-buttons-design.md`（状態の表記と、実機確認の結果）

**Acceptance Criteria:**
- [ ] README のツール表に `wait_for_button` の行があり、`show_annotated` の行に `buttons` と `explanation` の説明がある。使い方の例と既知の制限 2 行が追加されている
- [ ] `scripts/e2e_viewer.py` の出力に `timeout wait: {"pressed": null}`、`press: {'ok': True}`、`wait result: image 分からない`、`press while not waiting: {'error': 'Claude が待ち受けていません。…'}`、`E2E OK` が出る
- [ ] `smoke-out/viewer-buttons-waiting.png` に、画像の上の「できた」「分からない」のボタンと、画像の右の説明文が写っている
- [ ] ユーザーが VS Code の Claude Code で、ボタンを使ったやりとりを試して問題ないと確認する。その際、Esc で中断したあとの挙動（ページの表示、次のやりとりが詰まらないか）も確認し、仕様書 §5.2 に結果を書く

**Verify:** `PYTHONIOENCODING=utf-8 uv run --no-sync python scripts/e2e_viewer.py 2>&1 | grep -v "^INFO\|Processing request"` → `E2E OK`

**Steps:**

- [ ] **Step 1: `scripts/e2e_viewer.py` を次の内容に置き換える**

````python
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
````

- [ ] **Step 2: README を変更する**

1. 「使い方の例」の最後に次の行を追加する。

````markdown
- 「手順をボタンで案内して」（ページの「できた」「分からない」などのボタンを押しながら進められます）
````

2. ツール表の `show_annotated` の行の末尾（`…注釈は残る）` の後）に、`。`buttons`（最大6個）と `explanation` を付けると、ページにボタンと説明文が出る` を追加し、その下に次の行を追加する。

````markdown
| `wait_for_button` | ページのボタンが押されるまで待ち（1回最大110秒）、押されたボタン名と撮り直した画面を返す。時間切れなら `{"pressed": null}` |
````

3. 「既知の制限」の最後に次の 2 行を追加する。

````markdown
- ボタンでのやりとりの間、チャットは「実行中」になります。止めるときは Esc を押してください。
- ボタンで撮り直すのは、表示中の画像と同じウィンドウまたはモニターだけです。別のウィンドウを見てほしいときはチャットで頼んでください。
````

- [ ] **Step 3: 通しテストを実行する**

ブラウザのタブが 1 つ開き、試験用ウィンドウが数秒表示される。ほかのウィンドウは操作しない。

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync python scripts/e2e_viewer.py 2>&1 | grep -v "^INFO\|Processing request"`
Expected: Acceptance Criteria の行と `E2E OK`。`smoke-out/viewer-buttons-waiting.png` を Read で開き、ボタンと説明文が写っていることを確認する。

- [ ] **Step 4: コミットする**

````bash
git add scripts/e2e_viewer.py README.md
git commit -F - <<'EOF'
docs: document page buttons and extend the end-to-end script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
````

- [ ] **Step 5: ユーザーに試してもらう**

ユーザーに次を依頼し、結果を待つ。
1. VS Code の Claude Code で、`/mcp` から `desktop` を再接続する（または新しいセッションを開く）。古いビューアーのタブは閉じる。
2. 「手順をボタンで案内して」などと頼み、ページのボタンを押して、Claude が反応して次の表示が出ることを確認する。
3. やりとりの途中でチャットの Esc を押して中断し、その後ページのボタンを押したとき・次に頼んだときの挙動を確認する。

- [ ] **Step 6: 仕様書を更新する**

`docs/superpowers/specs/2026-10-03-page-buttons-design.md` の「状態」を `実装済み` にし、§5.2 の Esc の行の後に、Step 5 で確認した結果（例：「2026-10-03 確認: Esc 後にボタンを押すと考え中のまま。次の依頼で新しい待ちが始まると正常に戻る」）を 1 行で追記して、コミットする。
