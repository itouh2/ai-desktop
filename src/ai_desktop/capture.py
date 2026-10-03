"""Everything that touches Win32: DPI awareness, enumeration and capture."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

import mss
import pywintypes
import win32api
import win32gui
import win32ui
from mss.exception import ScreenShotError
from PIL import Image

from ai_desktop.imaging import CaptureError, MonitorInfo, WindowInfo, restore_dpi_scaling

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2
DPI_AWARENESS_PER_MONITOR = 2
DWMWA_CLOAKED = 14
MONITORINFOF_PRIMARY = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_RENDERFULLCONTENT = 2

_log = logging.getLogger(__name__)
# mcp runs sync tools on worker threads and clients may call tools in parallel;
# GDI capture is serialized so two captures never interleave.
_capture_lock = threading.Lock()

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")

_user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_user32.GetThreadDpiAwarenessContext.argtypes = []
_user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
_user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_user32.PrintWindow.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
]
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
_user32.GetDpiForWindow.argtypes = [wintypes.HWND]
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0


def enable_dpi_awareness() -> None:
    """Make every API in this process speak physical pixels (spec §6.3)."""
    context = ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    if not _user32.SetProcessDpiAwarenessContext(context):
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
    awareness = _user32.GetAwarenessFromDpiAwarenessContext(_user32.GetThreadDpiAwarenessContext())
    if awareness != DPI_AWARENESS_PER_MONITOR:
        _log.warning(
            "Process is not per-monitor DPI aware (awareness=%s); screen coordinates "
            "and captured sizes may be wrong on scaled displays.",
            awareness,
        )


def list_monitors() -> list[MonitorInfo]:
    monitors = []
    for index, (handle, _dc, _rect) in enumerate(win32api.EnumDisplayMonitors(), start=1):
        info = win32api.GetMonitorInfo(handle)
        left, top, right, bottom = info["Monitor"]
        monitors.append(
            MonitorInfo(
                id=index,
                name=info["Device"],
                primary=bool(info["Flags"] & MONITORINFOF_PRIMARY),
                x=left,
                y=top,
                width=right - left,
                height=bottom - top,
            )
        )
    return monitors


def list_windows() -> list[WindowInfo]:
    """Visible, titled, uncloaked top-level windows, front-most first."""
    handles: list[int] = []

    def collect(hwnd: int, _extra: object) -> bool:
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) and not _is_cloaked(hwnd):
            handles.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)
    foreground = win32gui.GetForegroundWindow()
    windows = []
    for hwnd in handles:
        try:
            windows.append(_window_info(hwnd, foreground))
        except pywintypes.error:
            continue  # closed between enumeration and inspection
    return windows


def capture_monitor(monitor_id: int | None) -> tuple[Image.Image, MonitorInfo]:
    with _capture_lock:
        return _capture_monitor(monitor_id)


def _capture_monitor(monitor_id: int | None) -> tuple[Image.Image, MonitorInfo]:
    monitors = list_monitors()
    if not monitors:
        raise CaptureError("モニターが見つかりません。")
    if monitor_id is None:
        monitor = next((m for m in monitors if m.primary), monitors[0])
    else:
        monitor = next((m for m in monitors if m.id == monitor_id), None)
        if monitor is None:
            ids = ", ".join(str(m.id) for m in monitors)
            raise CaptureError(f"monitor_id {monitor_id} は存在しません。有効な id: {ids}")
    area = {"left": monitor.x, "top": monitor.y, "width": monitor.width, "height": monitor.height}
    try:
        with mss.mss() as screen:
            shot = screen.grab(area)
    except ScreenShotError as error:
        raise CaptureError(f"モニターの撮影に失敗しました: {error}") from error
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"), monitor


def capture_window(hwnd: int) -> tuple[Image.Image, WindowInfo]:
    with _capture_lock:
        return _capture_window(hwnd)


def _capture_window(hwnd: int) -> tuple[Image.Image, WindowInfo]:
    missing = CaptureError(
        f"window_id {hwnd} のウィンドウは存在しません。list_windows で確認してください。"
    )
    try:
        if not win32gui.IsWindow(hwnd):
            raise missing
        info = _window_info(hwnd, win32gui.GetForegroundWindow())
        if info.minimized:
            raise CaptureError(
                f"「{info.title}」は最小化中のため撮影できません。元に戻してから再実行してください。"
            )
        if info.width <= 0 or info.height <= 0:
            raise CaptureError(f"「{info.title}」はサイズが 0 のため撮影できません。")
        image = _print_window(hwnd, info.width, info.height)
        return restore_dpi_scaling(image, _user32.GetDpiForWindow(hwnd), _monitor_dpi(hwnd)), info
    except (TypeError, OverflowError) as error:
        raise missing from error
    except (pywintypes.error, win32ui.error) as error:
        raise CaptureError(f"ウィンドウの撮影に失敗しました: {error}") from error


def _monitor_dpi(hwnd: int) -> int:
    """Effective DPI of the monitor showing the window; 0 if it cannot be read."""
    monitor = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    if ctypes.WinDLL("shcore").GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)):
        return 0
    return dpi_x.value


def _window_info(hwnd: int, foreground: int) -> WindowInfo:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return WindowInfo(
        id=hwnd,
        title=win32gui.GetWindowText(hwnd),
        app=_exe_name(hwnd),
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
        minimized=bool(win32gui.IsIconic(hwnd)),
        focused=hwnd == foreground,
    )


def _is_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return cloaked.value != 0


def _exe_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not _kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value.rsplit("\\", 1)[-1]
    finally:
        _kernel32.CloseHandle(process)


def _print_window(hwnd: int, width: int, height: int) -> Image.Image:
    """Have the window render itself into a bitmap, so covered windows still capture."""
    window_dc_handle = win32gui.GetWindowDC(hwnd)
    try:
        window_dc = win32ui.CreateDCFromHandle(window_dc_handle)
        memory_dc = window_dc.CreateCompatibleDC()
        try:
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(window_dc, width, height)
            try:
                previous = memory_dc.SelectObject(bitmap)
                try:
                    if not _user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), PW_RENDERFULLCONTENT):
                        raise CaptureError(
                            f"PrintWindow が失敗しました（Win32 エラー {ctypes.get_last_error()}）。"
                        )
                    bits = bitmap.GetBitmapBits(True)
                finally:
                    # A bitmap can only be deleted once it is no longer selected into a DC.
                    memory_dc.SelectObject(previous)
            finally:
                win32gui.DeleteObject(bitmap.GetHandle())
        finally:
            memory_dc.DeleteDC()
            window_dc.DeleteDC()
    finally:
        win32gui.ReleaseDC(hwnd, window_dc_handle)
    if len(bits) != width * height * 4:
        raise CaptureError(
            "ウィンドウのビットマップ形式に対応していません（32 ビットカラーではありません）。"
        )
    return Image.frombuffer("RGB", (width, height), bits, "raw", "BGRX", 0, 1)
