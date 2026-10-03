"""Local viewer: shows the annotated capture in one reused browser tab and turns its clicks into real ones."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ai_desktop.annotate import VIEWER_TITLE_PREFIX, content_security_policy, render_shell
from ai_desktop.captures import CaptureStore
from ai_desktop.imaging import CaptureError, image_to_screen

_log = logging.getLogger(__name__)

ACK_TIMEOUT_SECONDS = 1.5
HEARTBEAT_SECONDS = 15.0
SETTLE_SECONDS = 0.15  # after minimizing the browser, before the click arrives
MAX_BODY_BYTES = 1024
TOKEN_HEADER = "X-AI-Desktop-Token"


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
        ack_timeout: float = ACK_TIMEOUT_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self._store = store
        self._control = control
        self._settle_seconds = settle_seconds
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

    def publish(self, capture_id: str, html: str, title: str) -> bool:
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
            }
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
                seen = 0
                while True:
                    view = viewer.next_view(seen, viewer.heartbeat_seconds)
                    if view is None:
                        self.wfile.write(b": ping\n\n")
                    else:
                        seen = view["version"]
                        data = json.dumps(view, ensure_ascii=False)
                        self.wfile.write(f"event: view\ndata: {data}\n\n".encode("utf-8"))
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
