"""Mouse and window control through Win32 (with capture.py, the only Win32 code)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import pywintypes
import win32con
import win32gui

from ai_desktop import capture
from ai_desktop.imaging import CaptureError

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
VK_MENU = 0x12
DOUBLE_CLICK_GAP_SECONDS = 0.05
FOREGROUND_WAIT_SECONDS = 0.3
ACTIVATION_SETTLE_SECONDS = 0.15  # let the window finish activating before input arrives


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_user32.SetCursorPos.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int


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
            _send(_key(VK_MENU), _key(VK_MENU, up=True))
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


def restore(hwnd: int) -> None:
    bring_to_front(hwnd)


def cursor_pos() -> tuple[int, int]:
    return win32gui.GetCursorPos()


def set_cursor(x: int, y: int) -> None:
    _user32.SetCursorPos(x, y)


def click(x: int, y: int, double: bool = False) -> None:
    """Left-click (or double-click) at physical screen coordinates.

    Every event carries the absolute position, so a mouse the user is still moving
    cannot drag the click somewhere else (seen in the smoke test, 2026-10-03)."""
    press = (_mouse_at(x, y, MOUSEEVENTF_LEFTDOWN), _mouse_at(x, y, MOUSEEVENTF_LEFTUP))
    _send(_mouse_at(x, y, 0), *press)
    if double:
        time.sleep(DOUBLE_CLICK_GAP_SECONDS)
        _send(*press)


def _activate(hwnd: int) -> bool:
    _user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + FOREGROUND_WAIT_SECONDS
    while time.monotonic() < deadline:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


def _mouse_at(x: int, y: int, flags: int) -> INPUT:
    """A mouse event at (x, y), normalized to 0..65535 across the virtual desktop."""
    left = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    event = INPUT(type=INPUT_MOUSE)
    event.u.mi = MOUSEINPUT(
        round((x - left) * 65535 / max(1, width - 1)),
        round((y - top) * 65535 / max(1, height - 1)),
        0,
        flags | MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        0,
        0,
    )
    return event


def _key(vk: int, up: bool = False) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return event


def _send(*events: INPUT) -> None:
    array = (INPUT * len(events))(*events)
    if _user32.SendInput(len(events), array, ctypes.sizeof(INPUT)) != len(events):
        raise CaptureError(f"入力を送れませんでした（Win32 エラー {ctypes.get_last_error()}）。")
