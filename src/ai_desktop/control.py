"""Window control through Win32 (with capture.py, the only Win32 code besides inputs.py)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import pywintypes
import win32con
import win32gui

from ai_desktop import capture, inputs
from ai_desktop.imaging import CaptureError

FOREGROUND_WAIT_SECONDS = 0.3
ACTIVATION_SETTLE_SECONDS = 0.15  # let the window finish activating before input arrives

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_user32.SetCursorPos.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL


def find_window(title_fragment: str) -> int | None:
    """The front-most visible window whose title contains title_fragment, if any."""
    for window in capture.list_windows():
        if title_fragment in window.title:
            return window.id
    return None


def foreground_window() -> int:
    return win32gui.GetForegroundWindow()


def window_origin(hwnd: int) -> tuple[int, int]:
    """Current top-left of the window, in physical pixels."""
    try:
        if not win32gui.IsWindow(hwnd):
            raise CaptureError("操作対象のウィンドウが見つかりません。撮影し直してください。")
        left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
    except (pywintypes.error, TypeError, OverflowError) as error:
        raise CaptureError("操作対象のウィンドウが見つかりません。撮影し直してください。") from error
    return left, top


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Current (left, top, right, bottom) of the window, in physical pixels."""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except (pywintypes.error, TypeError, OverflowError) as error:
        raise CaptureError("ブラウザのウィンドウの位置を取得できませんでした。") from error
    return left, top, right, bottom


def bring_to_front(hwnd: int) -> bool:
    """Foreground the window, restoring it if minimized; True on success.

    Windows ignores SetForegroundWindow from a background process, so after a plain
    attempt fails, a tap of Alt unlocks it (verified on this machine 2026-10-03)."""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        if not _activate(hwnd):
            inputs.tap_alt()
            if not _activate(hwnd):
                return False
        time.sleep(ACTIVATION_SETTLE_SECONDS)
        return True
    except (pywintypes.error, CaptureError):
        return False


def minimize(hwnd: int) -> None:
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    except pywintypes.error:
        pass


def is_minimized(hwnd: int) -> bool:
    try:
        return bool(win32gui.IsIconic(hwnd))
    except pywintypes.error:
        return False


def restore(hwnd: int) -> None:
    bring_to_front(hwnd)


def cursor_pos() -> tuple[int, int]:
    return win32gui.GetCursorPos()


def set_cursor(x: int, y: int) -> None:
    _user32.SetCursorPos(x, y)


def click(x: int, y: int, double: bool = False) -> None:
    """Left-click (or double-click) at physical screen coordinates (see inputs.click)."""
    inputs.click(x, y, double)


def _activate(hwnd: int) -> bool:
    _user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + FOREGROUND_WAIT_SECONDS
    while time.monotonic() < deadline:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False
