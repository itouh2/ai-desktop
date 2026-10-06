"""Test doubles shared by several test modules (tests/ is on sys.path under pytest's default import mode)."""

import time

from ai_desktop.imaging import CaptureError

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
        foreground=BROWSER,
    ):
        self.calls = []
        self.times = {}
        self.minimize_ok = minimize_ok
        self.fail_rect = fail_rect
        self.foreground = foreground
        self.browser_rect = browser_rect
        self.front_ok = front_ok
        self.browser = browser
        self.origin = origin
        self.fail_origin = fail_origin
        self.front = None  # the window last brought to front
        self.covered_by = None  # set to make window_at answer another window (an overlap)
        self.covered_at = {}  # (x, y) -> window: an overlap at one point only

    def find_window(self, fragment):
        self.calls.append(("find_window", fragment))
        return self.browser

    def cursor_pos(self):
        self.calls.append(("cursor_pos",))
        return (5, 6)

    def foreground_window(self):
        self.calls.append(("foreground_window",))
        return self.foreground

    def minimize(self, hwnd):
        self.calls.append(("minimize", hwnd))

    def is_minimized(self, hwnd):
        self.calls.append(("is_minimized", hwnd))
        return self.minimize_ok

    def bring_to_front(self, hwnd):
        self.calls.append(("bring_to_front", hwnd))
        if self.front_ok:
            self.front = hwnd
        return self.front_ok

    def window_at(self, x, y):
        self.calls.append(("window_at", x, y))
        if (x, y) in self.covered_at:
            return self.covered_at[(x, y)]
        return self.front if self.covered_by is None else self.covered_by

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
