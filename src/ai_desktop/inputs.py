"""Mouse and keyboard input through Win32 SendInput (the only code that sends input)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from ai_desktop.imaging import CaptureError

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
VK_MENU = 0x12
DOUBLE_CLICK_GAP_SECONDS = 0.05
HOVER_SECONDS = 0.1  # the cursor rests on the point this long before the press
PRESS_SECONDS = 0.05  # the button stays down this long
_sleep = time.sleep  # replaced in tests


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
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int


def move(x: int, y: int) -> None:
    """Move the cursor to physical screen coordinates as a real mouse move (no buttons)."""
    _send(_mouse_at(x, y, 0))


def click(x: int, y: int, double: bool = False) -> None:
    """Left-click (or double-click) at physical screen coordinates, the way a hand does it.

    The cursor rests on the point before the press, because games pick what is under the
    cursor once a frame and a press arriving with the move lands on what the cursor was over
    before (seen in Balatro, 2026-10-05); the button stays down across a frame for apps that
    poll it. Every event carries the absolute position, so a mouse the user is still moving
    cannot drag the click somewhere else (seen in the smoke test, 2026-10-03)."""
    _send(_mouse_at(x, y, 0))
    _sleep(HOVER_SECONDS)
    _press(x, y)
    if double:
        _sleep(DOUBLE_CLICK_GAP_SECONDS)
        _press(x, y)


def _press(x: int, y: int) -> None:
    _send(_mouse_at(x, y, MOUSEEVENTF_LEFTDOWN))
    _sleep(PRESS_SECONDS)
    _send(_mouse_at(x, y, MOUSEEVENTF_LEFTUP))


def tap_alt() -> None:
    """Press and release Alt, which lets a background process bring a window to the front."""
    _send(_key(VK_MENU), _key(VK_MENU, up=True))


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
