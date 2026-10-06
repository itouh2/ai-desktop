"""Prepares and cleans up an operation at a point of a capture (a click, a cursor move, a drag)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ai_desktop.annotate import VIEWER_TITLE_PREFIX
from ai_desktop.captures import CaptureStore
from ai_desktop.imaging import CaptureError, image_to_screen

SETTLE_SECONDS = 0.15  # after minimizing the browser, before the operation
# after bringing a window that did not have focus to the front: a game that just got focus back
# can drop the first input for a moment (Balatro ignored clicks sent 0.25 s after, 2026-10-05)
FOCUS_SECONDS = 0.5
COVERED_MESSAGE = (
    "押す位置が対象のウィンドウの外か、別のウィンドウの下にあるため、押しませんでした。"
    "重なっているウィンドウをどけてもらうか、撮影し直してください。"
)


@dataclass(frozen=True)
class Spot:
    screen: tuple[int, int]  # the point, in physical screen pixels
    cursor: tuple[int, int]  # where the cursor was before; the caller decides whether to put it back
    end: tuple[int, int] | None = None  # the end point of a drag, in physical screen pixels


class Pointer:
    """Runs one operation at a time at a point of a capture.

    control is the ai_desktop.control module in production; tests pass a fake with the same
    functions (find_window, cursor_pos, foreground_window, bring_to_front, window_origin, window_at, window_rect,
    minimize, is_minimized, restore). lock is shared with the viewer's re-capture."""

    def __init__(
        self,
        store: CaptureStore,
        control: Any,
        settle_seconds: float = SETTLE_SECONDS,
        focus_seconds: float = FOCUS_SECONDS,
    ) -> None:
        self._store = store
        self._control = control
        self._settle_seconds = settle_seconds
        self._focus_seconds = focus_seconds
        self.lock = threading.Lock()

    @contextmanager
    def at(
        self,
        capture_id: str,
        x: float,
        y: float,
        return_focus: bool = True,
        must_hit_target: bool = False,
        to: tuple[float, float] | None = None,
        restore_browser: bool = True,
    ) -> Iterator[Spot]:
        """Get ready to operate at (x, y) of the capture and yield where that is on screen.

        On a monitor capture, a viewer browser covering the point is minimized. It comes back
        afterwards unless restore_browser=False (for a cursor left on the point, which the browser
        would cover again), and focus returns to the window that had it; the cursor is left to the
        caller. When return_focus=False, the previous foreground window is not restored (a window
        target stays in front).
        must_hit_target=True refuses a window target unless that window is the top-level window at
        the point once it is in front, so an operation never lands on a window over it or, when the
        window got smaller than the capture, on what is behind it. to is the end point of a drag on
        the same capture: it is checked like (x, y) and comes back as Spot.end."""
        if not self.lock.acquire(blocking=False):
            raise CaptureError("ほかの操作を実行中です。終わるまで待ってください。")
        try:
            _, meta = self._store.get(capture_id)
            target = self._store.target(capture_id)
            points = [(x, y)] if to is None else [(x, y), to]
            if not all(0 <= px < meta["imageWidth"] and 0 <= py < meta["imageHeight"] for px, py in points):
                raise CaptureError("位置が画像の外です。")
            browser = self._control.find_window(VIEWER_TITLE_PREFIX)
            if target.kind == "window" and target.id == browser:
                raise CaptureError(
                    "表示中のブラウザと同じウィンドウは操作できません。対象のタブを別のウィンドウに分けてください。"
                )
            cursor = self._control.cursor_pos()
            previous = self._control.foreground_window()
            minimized = False
            try:
                origin = None
                if target.kind == "window":
                    # Bringing the target to the front also lifts it above the browser.
                    if not self._control.bring_to_front(target.id):
                        raise CaptureError("対象のウィンドウを前面に出せませんでした。もう一度試してください。")
                    if previous != target.id:
                        time.sleep(self._focus_seconds)
                    origin = self._control.window_origin(target.id)
                screens = [image_to_screen(meta, px, py, origin) for px, py in points]
                screen = screens[0]
                if must_hit_target and target.kind == "window" and any(
                    self._control.window_at(*point) != target.id for point in screens
                ):
                    raise CaptureError(COVERED_MESSAGE)
                if browser is not None and target.kind == "monitor" and self._covers(browser, screen):
                    self._control.minimize(browser)
                    minimized = True
                    time.sleep(self._settle_seconds)
                    if not self._control.is_minimized(browser):
                        raise CaptureError("ブラウザを最小化できなかったため、操作しませんでした。")
                yield Spot(screen=screen, cursor=cursor, end=screens[1] if to is not None else None)
            finally:
                if minimized and restore_browser:
                    self._control.restore(browser)
                if return_focus and previous and not (minimized and previous == browser):
                    self._control.restore(previous)
        finally:
            self.lock.release()

    def _covers(self, browser: Any, screen: tuple[int, int]) -> bool:
        left, top, right, bottom = self._control.window_rect(browser)
        screen_x, screen_y = screen
        return left <= screen_x < right and top <= screen_y < bottom
