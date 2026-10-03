"""Manual smoke test for control.py: foreground, minimize/restore and click a harmless window."""

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import win32gui

from ai_desktop import capture, control

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from click_target import TITLE  # noqa: E402


def start_target() -> tuple[subprocess.Popen, queue.Queue]:
    app = subprocess.Popen(
        [sys.executable, str(HERE / "click_target.py")],
        stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(json.loads(line)) for line in app.stdout], daemon=True).start()
    return app, lines


def find_target() -> int | None:
    """The test window itself; a viewer tab showing it also has TITLE in its title."""
    return next((w.id for w in capture.list_windows() if w.title == TITLE), None)


def latest(lines: queue.Queue, wait: float) -> dict:
    deadline, state = time.monotonic() + wait, {}
    while time.monotonic() < deadline:
        try:
            state = lines.get(timeout=0.1)
        except queue.Empty:
            pass
    return state


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.enable_dpi_awareness()
    original = control.foreground_window()
    app, lines = start_target()
    try:
        hwnd = None
        for _ in range(50):
            hwnd = find_target()
            if hwnd:
                break
            time.sleep(0.1)
        assert hwnd, "試験用ウィンドウが見つかりません"
        print("startup:", latest(lines, 0.8))  # drain the initial 0/0 line
        print("bring back original:", control.bring_to_front(original))
        print("bring target:", control.bring_to_front(hwnd))
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        center = ((left + right) // 2, (top + bottom) // 2 + 20)
        cursor = control.cursor_pos()
        control.click(*center)
        print("after click:", latest(lines, 0.8))
        control.click(*center, double=True)
        print("after double:", latest(lines, 0.8))
        control.set_cursor(*cursor)
        print("cursor restored:", control.cursor_pos() == cursor)
        control.minimize(hwnd)
        time.sleep(0.3)
        print("minimized:", bool(win32gui.IsIconic(hwnd)))
        control.restore(hwnd)
        print("restored to front:", control.foreground_window() == hwnd)
        print("origin:", control.window_origin(hwnd))
    finally:
        app.terminate()
        control.bring_to_front(original)


if __name__ == "__main__":
    main()
