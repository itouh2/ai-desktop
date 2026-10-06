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

from ai_desktop.annotate import MAX_MESSAGE_CHARS, VIEWER_TITLE_PREFIX, content_security_policy, render_shell
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError
from ai_desktop.pointer import SETTLE_SECONDS, Pointer

_log = logging.getLogger(__name__)

ACK_TIMEOUT_SECONDS = 1.5
HEARTBEAT_SECONDS = 15.0
AFTER_CLICK_SECONDS = 0.3  # apps (games especially) may handle a click on a later frame; keep focus and cursor until then
MAX_BODY_BYTES = 16 * 1024  # fits a MAX_MESSAGE_CHARS message even with every character \u-escaped
TOKEN_HEADER = "X-AI-Desktop-Token"
MAX_EXPLANATION_CHARS = 4000
NOT_WAITING_MESSAGE = "Claude が待ち受けていません。チャットで、ページで進めたいと頼んでください。"
UNKNOWN_BUTTON_MESSAGE = "そのボタンは今は使えません。"
NO_MESSAGE_BOX_MESSAGE = "このページでは入力欄を使えません。"
EMPTY_MESSAGE = "メッセージが空です。"
LONG_MESSAGE = f"メッセージは {MAX_MESSAGE_CHARS} 文字までです。"
MAX_CLICK_RECORDS = 5
AGENT_OFF_MESSAGE = "ページで『Claude に操作を任せる』がオフです。押してほしいことをユーザーに伝えるか、オンにしてもらってください。"
NO_PAGE_FOR_CLICK_MESSAGE = "表示中のページがありません。先に show_annotated で対象のウィンドウを表示してください。"
MONITOR_CLICK_MESSAGE = "画面全体の撮影ではクリックできません。対象のウィンドウを capture_window で撮り、ページに表示してください。"
OTHER_WINDOW_MESSAGE = "クリックできるのは、ページに表示中のウィンドウだけです。"
AGENT_STALE_MESSAGE = "ページの表示が別のウィンドウに変わりました。表示を確かめてから、もう一度オンにしてください。"


def _accepts_messages(view: dict) -> bool:
    """Whether the page offers a way to send Claude a message (buttons or the message box)."""
    return bool(view["buttons"]) or view["messageBox"]


def _target_key(target: Target) -> str:
    """How the page names a capture target ("window:<hwnd>" or "monitor:<id>")."""
    return f"{target.kind}:{target.id}"


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
        pointer: Pointer | None = None,
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
        self._shown_target: Target | None = None
        self._version = 0
        self._acked = 0
        self._clients = 0
        self._pointer = pointer if pointer is not None else Pointer(store, control, settle_seconds, settle_seconds)
        self._state = "idle"
        self._state_version = 1  # new tabs receive the current state right away
        self._wait_generation = 0
        self._reply: dict | None = None
        self._agent = False  # the user's permission for Claude's click tool; off until the page turns it on
        self._clicks: list[dict] = []  # Claude's latest clicks, newest first

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
        self,
        capture_id: str,
        html: str,
        title: str,
        explanation: str = "",
        buttons: list[str] | None = None,
        message_box: bool = False,
    ) -> bool:
        """Make this the current view; True when an open tab confirmed it within the timeout.

        buttons and message_box are the page's ways of sending Claude a message: a button
        sends its label, the message box sends what the user typed. The permission for Claude's
        clicks belongs to the window the page showed when the user gave it, so showing another
        window or a monitor turns it off; a newer capture of the same window keeps it."""
        _, meta = self._store.get(capture_id)
        target = self._store.target(capture_id)
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
                "messageBox": bool(message_box),
                "target": target.kind,
                "targetKey": _target_key(target),
            }
            if self._agent and target != self._shown_target:
                self._agent = False
                self._bump_state()
            self._shown_target = target  # kept here: the shown capture may leave the store before a click
            if self._state == "waiting" and not _accepts_messages(self._view):
                self._wait_generation += 1  # the waiter returns None
                self._set_state("idle")
            elif self._state in ("thinking", "error"):
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

    # --- messages from the page ------------------------------------------------------------

    def wait_for_message(self, timeout: float) -> dict | None:
        """Block until the page sends Claude a message; {"message": text, "via": "button",
        "text" or "refresh"}, or None on timeout.

        A newer wait cancels an older one, which then returns None, so a wait left over
        from an interrupted turn cannot block the next one."""
        with self._changed:
            if self._view is None:
                raise CaptureError("表示中のページがありません。先に show_annotated で表示してください。")
            if not _accepts_messages(self._view):
                raise CaptureError(
                    "表示中のページに、メッセージを送る入口がありません。"
                    "show_annotated に buttons か message_box を付けてください。"
                )
            self._wait_generation += 1
            generation = self._wait_generation
            self._reply = None
            self._set_state("waiting")
            done = lambda: self._reply is not None or self._wait_generation != generation  # noqa: E731
            self._changed.wait_for(done, timeout=timeout)
            if self._wait_generation != generation:
                return None
            if self._reply is not None:
                reply, self._reply = self._reply, None
                return reply
            self._set_state("idle")
            return None

    def press(self, label: str) -> None:
        """A page button was pressed; wakes the waiting tool call."""
        with self._changed:
            if self._state != "waiting":
                raise CaptureError(NOT_WAITING_MESSAGE)
            if self._view is None or label not in self._view["buttons"]:
                raise CaptureError(UNKNOWN_BUTTON_MESSAGE)
            self._answer({"message": label, "via": "button"})

    def refresh(self) -> None:
        """The page's built-in refresh button was pressed; wakes the waiting tool call.

        Unlike press there is no page check: a wait only runs while the shown page can send
        messages, because publishing a page that cannot ends the wait."""
        with self._changed:
            if self._state != "waiting":
                raise CaptureError(NOT_WAITING_MESSAGE)
            self._answer({"message": "", "via": "refresh"})

    def send_message(self, text: str) -> None:
        """The user typed a message in the page's message box; wakes the waiting tool call."""
        text = text.strip()
        if not text:
            raise CaptureError(EMPTY_MESSAGE)
        if len(text) > MAX_MESSAGE_CHARS:
            raise CaptureError(LONG_MESSAGE)
        with self._changed:
            if self._state != "waiting":
                raise CaptureError(NOT_WAITING_MESSAGE)
            if self._view is None or not self._view["messageBox"]:
                raise CaptureError(NO_MESSAGE_BOX_MESSAGE)
            self._answer({"message": text, "via": "text"})

    def _answer(self, reply: dict) -> None:
        """Caller holds self._changed."""
        self._reply = reply
        self._set_state("thinking")

    def recapture_current(self, recapture: Callable[[Target], Any]) -> Any:
        """Capture the target of the view on screen again (waits for a click in progress)."""
        with self._pointer.lock:
            with self._changed:
                if self._view is None:
                    raise CaptureError("表示中のページがありません。先に show_annotated で表示してください。")
                capture_id = self._view["captureId"]
            browser = None
            try:
                target = self._store.target(capture_id)
                if target.kind == "monitor":
                    browser = self._minimize_browser_over(capture_id)
                return recapture(target)
            except Exception as error:
                with self._changed:
                    self._set_state("error")
                if isinstance(error, CaptureError):
                    raise
                raise CaptureError(f"撮り直しに失敗しました: {error}") from error
            finally:
                if browser is not None:
                    self._control.restore(browser)

    def _minimize_browser_over(self, capture_id: str) -> Any:
        """Minimize the viewer browser if it covers the shown monitor; its handle when minimized."""
        browser = self._control.find_window(VIEWER_TITLE_PREFIX)
        if browser is None:
            return None
        _, meta = self._store.get(capture_id)
        left, top, right, bottom = self._control.window_rect(browser)
        m_left, m_top = meta["originX"], meta["originY"]
        m_right, m_bottom = m_left + meta["originalWidth"], m_top + meta["originalHeight"]
        if not (left < m_right and m_left < right and top < m_bottom and m_top < bottom):
            return None
        self._control.minimize(browser)
        try:
            time.sleep(self._settle_seconds)
            if not self._control.is_minimized(browser):
                raise CaptureError("ブラウザを最小化できなかったため、撮り直せませんでした。")
        except BaseException:
            self._control.restore(browser)
            raise
        return browser

    def _set_state(self, state: str) -> None:
        """Caller holds self._changed."""
        self._state = state
        self._bump_state()

    def _bump_state(self) -> None:
        """Send the page a new state entry. Caller holds self._changed."""
        self._state_version += 1
        self._changed.notify_all()

    # --- Claude's clicks: permission and records -------------------------------------------

    def set_agent(self, enabled: bool, target_key: str | None = None) -> None:
        """The page's switch for letting Claude click: the only way the permission is given.

        Turning it on names the target the page showed (its targetKey); unless that is still the
        shown target, it raises CaptureError(AGENT_STALE_MESSAGE) and stays off, so a page that
        changed under the user's click cannot hand over a window they did not see. Turning it off
        always works."""
        with self._changed:
            if enabled and (self._shown_target is None or target_key != _target_key(self._shown_target)):
                raise CaptureError(AGENT_STALE_MESSAGE)
            self._agent = enabled
            self._bump_state()

    def authorize_click(self, capture_id: str) -> None:
        """Raise CaptureError unless Claude may click on this capture now: the user allowed it
        and the capture is of the window the page shows."""
        with self._changed:
            if not self._agent:
                raise CaptureError(AGENT_OFF_MESSAGE)
            if self._view is None:
                raise CaptureError(NO_PAGE_FOR_CLICK_MESSAGE)
            target = self._store.target(capture_id)
            if target.kind == "monitor":
                raise CaptureError(MONITOR_CLICK_MESSAGE)
            if target != self._shown_target:
                raise CaptureError(OTHER_WINDOW_MESSAGE)

    def record_click(self, what: str) -> None:
        """Log a click Claude made, newest first, for the page to show."""
        with self._changed:
            self._clicks.insert(0, {"time": time.strftime("%H:%M:%S"), "what": what})
            del self._clicks[MAX_CLICK_RECORDS:]
            self._bump_state()

    # --- clicking --------------------------------------------------------------------------

    def perform_click(self, capture_id: str, x: float, y: float, double: bool) -> None:
        """Click the real screen where (x, y) is on the capture. The page is left as it is."""
        with self._pointer.at(capture_id, x, y) as spot:
            try:
                self._control.click(*spot.screen, double)
                time.sleep(self._after_click_seconds)
            finally:
                self._control.set_cursor(*spot.cursor)

    # --- used by the request handler -------------------------------------------------------

    def background(self, capture_id: str) -> bytes:
        return self._store.get(capture_id)[0]

    def register_client(self) -> None:
        with self._changed:
            self._clients += 1

    def unregister_client(self) -> None:
        with self._changed:
            self._clients -= 1
            if self._clients <= 0 and self._agent:
                self._agent = False  # nobody is watching the page any more
                self._bump_state()

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
                {
                    "version": self._state_version,
                    "state": self._state,
                    "agent": {"enabled": self._agent, "clicks": [dict(click) for click in self._clicks]},
                }
                if self._state_version > seen_state
                else None
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
            elif path == "/refresh":
                try:
                    viewer.refresh()
                except CaptureError as error:
                    self._send_json(200, {"error": str(error)})
                else:
                    self._send_json(200, {"ok": True})
            elif path == "/agent":
                enabled = body.get("enabled")
                target_key = body.get("target")
                if not isinstance(enabled, bool) or (enabled and not isinstance(target_key, str)):
                    self._send_json(400, {"error": "要求の形式が正しくありません。"})
                    return
                try:
                    viewer.set_agent(enabled, target_key if enabled else None)
                except CaptureError as error:
                    self._send_json(200, {"error": str(error)})
                else:
                    self._send_json(200, {"ok": True})
            elif path == "/message":
                text = body.get("text")
                if not isinstance(text, str):
                    self._send_json(400, {"error": "要求の形式が正しくありません。"})
                    return
                try:
                    viewer.send_message(text)
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
