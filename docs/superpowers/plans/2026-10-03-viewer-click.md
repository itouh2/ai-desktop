# ビューアーのクリック連動とタブの再利用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 注釈ページ上のクリック・ダブルクリックを実際の画面のクリックに連動させ（撮り直してページを自動更新）、`show_annotated` が毎回新しいタブを開く問題を既存タブの再利用で解消する。あわせて、高 DPI 非対応アプリのウィンドウ撮影が欠ける不具合を直す。

**Architecture:** MCP サーバー内に 127.0.0.1 だけで待ち受ける Web サーバー（`viewer.py`、標準ライブラリのみ）を持ち、ページの枠組み・背景画像・表示内容（SSE）を配信し、ページからのクリック要求を受ける。クリック時は Win32 操作（`control.py`）で「ブラウザを最小化 → 対象を前面に → クリック → 撮り直し → 元に戻す」を行う。撮影ごとに対象（`Target`）を `CaptureStore` に記録し、撮り直しと座標換算に使う。

**Tech Stack:** Python 3.12 / uv / mcp 2.x（`MCPServer`）/ pywin32 + ctypes（SendInput 等）/ http.server（ThreadingHTTPServer）/ Server-Sent Events / pytest / tkinter（試験用ウィンドウ）

**Global Constraints:**
- 仕様書: `docs/superpowers/specs/2026-10-03-viewer-click-design.md`
- Windows 専用。Win32 に触れるコードは `src/ai_desktop/capture.py` と `src/ai_desktop/control.py` にだけ置く。
- Web サーバーは `127.0.0.1` のみで待ち受け、ポートは空きポート（0 指定）。合言葉は `secrets.token_urlsafe(24)`。
- GET は クエリ `t`（合言葉）と `Host == 127.0.0.1:<port>` を必須にする。POST は ヘッダー `X-AI-Desktop-Token`、`Origin == http://127.0.0.1:<port>`、Host を必須にする。比較は `secrets.compare_digest`。
- 全レスポンスに `Cache-Control: no-store`、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`。ページの CSP は `default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-<nonce>'; connect-src 'self'`（HTTP ヘッダーで送る）。
- ページのタイトルは `ai-desktop | <title>`（`VIEWER_TITLE_PREFIX = "ai-desktop | "`）。ブラウザのウィンドウ探しに使う。
- タブの受け取り確認（ack）の待ち時間は 1.5 秒、SSE の生存確認は 15 秒、クリック後の撮り直しまでの待ち時間は 0.7 秒、前面化成功後の待ち時間は 0.15 秒、ダブルクリックの間隔は 50ms、要求本文の上限は 1024 バイト。
- クリック操作は同時に1つだけ。失敗してもマウス位置とブラウザは必ず元に戻す（`finally`）。
- ツールのエラーは `ToolError`（`CaptureError` は `_reported()` で変換）。ページへのエラーは JSON の `error` に日本語で入れる。
- 標準出力は MCP 専用。HTTP サーバーのログは `logging` 経由。
- 注釈 HTML の危険なタグの拒否はしない（ユーザー判断）。
- 一時フォルダへの HTML 保存（`%TEMP%\ai-desktop\annotations\`）は廃止する。
- コミットメッセージの末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- `.superpowers/`、`smoke-out/`、未追跡の `docs/superpowers/reviews/`、`*.tasks.json` はステージしない。

**User decisions (already made):**
- クリック後は「リモート操作風」：実際の画面をクリックし、撮り直した画面にページを自動更新する（注釈は消える）。
- ブラウザが対象に重なる問題は「一時的にどかす」：最小化 → 対象を前面に → クリック → 撮り直し → ブラウザを戻す。
- 伝える操作は左クリックとダブルクリックだけ。
- 方式は MCP サーバー内の小さな Web サーバー（設計セクション1・2 を承認済み）。
- 注釈 HTML の危険なタグの拒否は「今回も対応しない」。
- 計画作成中に見つかった「高 DPI 非対応アプリの撮影が欠ける」不具合は「含める」。

**参考実装について:** この計画のコードは、スクラッチの作業ツリーで実装・テスト（pytest 66 件、`control_smoke.py` を 3 回、`e2e_viewer.py`）済みのものをそのまま載せている。

---

## ファイル構成

| パス | 責務 |
|---|---|
| `src/ai_desktop/captures.py`（変更） | `Target` を撮影と一緒に保持し、`target(capture_id)` で返す |
| `src/ai_desktop/imaging.py`（変更） | `image_to_screen` の `origin` 上書き、`restore_dpi_scaling` |
| `src/ai_desktop/capture.py`（変更） | ウィンドウ撮影に DPI の補正をかける |
| `src/ai_desktop/control.py`（新規） | クリック、ダブルクリック、マウス位置、前面化（Alt キーの回避策）、最小化と復元、タイトル検索 |
| `src/ai_desktop/annotate.py`（変更） | ビューアーページの枠組み（CSS、スクリプト、CSP）。ファイル保存の関数は削除 |
| `src/ai_desktop/viewer.py`（新規） | Web サーバー、認証、SSE、ack、クリック操作の手順 |
| `src/ai_desktop/server.py`（変更） | `Target` の記録、`_recapture`、`show_annotated` のビューアー化 |
| `scripts/click_target.py`（新規） | 試験用ウィンドウ（クリック回数を表示・出力） |
| `scripts/control_smoke.py`（新規） | `control.py` の実機スモークテスト |
| `scripts/e2e_viewer.py`（新規） | 実機の通しテスト |
| `tests/test_viewer.py`（新規）ほか既存テスト | 各タスク参照 |
| `README.md`（変更） | 新しい動作と既知の制限 |

コマンドはすべて `C:\Works\2026\ai-desktop` で実行する（Bash ツールでは `cd /c/Works/2026/ai-desktop`）。作業ブランチは `feature/click`。開始時点のテストは 52 件。

---

### Task 1: 撮影対象の記録と座標換算の拡張

**Goal:** 撮影ごとに対象（`Target`：モニター id かウィンドウのハンドル）を `CaptureStore` に記録し、同じ対象を撮り直す `_recapture` を用意する。`image_to_screen` に基準位置の上書き引数を足す。

**Files:**
- Modify: `src/ai_desktop/captures.py`（ファイル全体を置き換え）
- Modify: `src/ai_desktop/imaging.py`（`image_to_screen` を置き換え）
- Modify: `src/ai_desktop/server.py`（import、`_capture_result` まわり、撮影ツールの return）
- Test: `tests/test_captures.py`、`tests/test_imaging.py`、`tests/test_server.py`

**Acceptance Criteria:**
- [ ] `CaptureStore.add(..., target)` で記録した `Target` が `target(capture_id)` で返る
- [ ] 対象の記録がない撮影は「操作の対象を記録していません」、未知の id は id を含む `CaptureError` になる
- [ ] `image_to_screen(meta, x, y, origin=(ox, oy))` が撮影時の origin の代わりに `(ox, oy)` を使う
- [ ] `capture_monitor` は `Target("monitor", id)`、`capture_window` は `Target("window", hwnd)` を記録する
- [ ] `server._recapture(target)` が同じ対象を撮り直し、同じ `Target` 付きの新しい captureId を返す
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `57 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_captures.py` の `from ai_desktop.captures import CaptureStore` を `from ai_desktop.captures import CaptureStore, Target` に変え、末尾に追加する。

```python
def test_target_is_stored_with_the_capture():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {}, Target("window", 42))
    assert store.target(capture_id) == Target("window", 42)


def test_target_missing_or_unknown_is_an_error():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {})
    with pytest.raises(CaptureError, match="操作の対象を記録していません"):
        store.target(capture_id)
    with pytest.raises(CaptureError, match="c9"):
        store.target("c9")
```

`tests/test_imaging.py` の末尾に追加する。

```python
def test_image_to_screen_can_use_a_newer_origin():
    meta = build_meta("window:42 Excel", -100, 50, (1600, 900), (800, 450), 0.5)
    assert image_to_screen(meta, 10, 20) == (-80, 90)
    assert image_to_screen(meta, 10, 20, origin=(300, 400)) == (320, 440)
```

`tests/test_server.py` の `from ai_desktop.captures import CaptureStore` を `from ai_desktop.captures import CaptureStore, Target` に変え、`@pytest.fixture` / `def opened(` の直前に次の 2 テストを入れる。

```python
def test_captures_record_their_target():
    call("capture_monitor")
    call("capture_window", {"title": "excel"})
    assert server.captures.target("c1") == Target("monitor", 1)
    assert server.captures.target("c2") == Target("window", 42)


def test_recapture_takes_the_same_target_again():
    call("capture_window", {"title": "excel"})
    new_id = server._recapture(Target("window", 42))
    assert new_id == "c2"
    assert server.captures.target(new_id) == Target("window", 42)
    assert server.captures.get(new_id)[1]["source"] == "window:42 Book1 - Excel"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest -v`
Expected: FAIL（`ImportError: cannot import name 'Target'`）

- [ ] **Step 3: `captures.py` を次の内容に置き換える**

```python
"""Recent captures kept in memory, so annotations land on the exact image Claude saw."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from ai_desktop.imaging import CaptureError

CAPTURE_LIMIT = 10


@dataclass(frozen=True)
class Target:
    """What a capture was taken of, so it can be clicked and captured again."""

    kind: Literal["monitor", "window"]
    id: int


class CaptureStore:
    """Background JPEG, metadata and target of the latest captures, keyed c1, c2, ..."""

    def __init__(self, limit: int = CAPTURE_LIMIT) -> None:
        self._limit = limit
        self._items: OrderedDict[str, tuple[bytes, dict, Target | None]] = OrderedDict()
        self._next_number = 1
        self._lock = threading.Lock()  # tools may run on parallel worker threads

    def add(self, background_jpeg: bytes, meta: dict, target: Target | None = None) -> str:
        with self._lock:
            capture_id = f"c{self._next_number}"
            self._next_number += 1
            self._items[capture_id] = (background_jpeg, {**meta, "captureId": capture_id}, target)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
            return capture_id

    def get(self, capture_id: str) -> tuple[bytes, dict]:
        with self._lock:
            background_jpeg, meta, _target = self._item(capture_id)
            return background_jpeg, dict(meta)

    def target(self, capture_id: str) -> Target:
        with self._lock:
            target = self._item(capture_id)[2]
        if target is None:
            raise CaptureError(f"capture_id「{capture_id}」は操作の対象を記録していません。撮影し直してください。")
        return target

    def _item(self, capture_id: str) -> tuple[bytes, dict, Target | None]:
        item = self._items.get(capture_id)
        if item is None:
            available = ", ".join(self._items) or "なし"
            raise CaptureError(
                f"capture_id「{capture_id}」は見つかりません"
                f"（保持しているのは直近 {self._limit} 件: {available}）。"
                "撮影し直してから指定してください。"
            )
        return item
```

- [ ] **Step 4: `imaging.py` の `image_to_screen` を次の内容に置き換える**

```python
def image_to_screen(
    meta: dict, x: float, y: float, origin: tuple[int, int] | None = None
) -> tuple[int, int]:
    """Map a point on the returned image back to physical screen coordinates.

    origin replaces the capture-time origin, e.g. for a window that has moved since."""
    origin_x, origin_y = origin if origin is not None else (meta["originX"], meta["originY"])
    return (
        round(origin_x + x / meta["scale"]),
        round(origin_y + y / meta["scale"]),
    )
```

- [ ] **Step 5: `server.py` を変更する**

1. `from ai_desktop.captures import CaptureStore` を `from ai_desktop.captures import CaptureStore, Target` に変える。
2. `_capture_result` 関数全体を、次の 3 関数に置き換える。

```python
def _store_capture(
    image: PILImage.Image, source: str, origin_x: int, origin_y: int, target: Target
) -> tuple[PILImage.Image, dict]:
    """Shrink for the model, keep the full-resolution background, and return (shrunk, meta)."""
    shrunk, scale = shrink(image)
    meta = build_meta(source, origin_x, origin_y, image.size, shrunk.size, scale)
    meta["captureId"] = captures.add(encode_jpeg(image, quality=BACKGROUND_JPEG_QUALITY), meta, target)
    return shrunk, meta


def _capture_result(
    image: PILImage.Image, source: str, origin_x: int, origin_y: int, target: Target
) -> list[Image | str]:
    shrunk, meta = _store_capture(image, source, origin_x, origin_y, target)
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(meta, ensure_ascii=False)]


def _recapture(target: Target) -> str:
    """Capture the same monitor or window again; returns the new captureId."""
    if target.kind == "monitor":
        image, monitor = capture.capture_monitor(target.id)
        source, origin = f"monitor:{monitor.id} {monitor.name}", (monitor.x, monitor.y)
    else:
        image, window = capture.capture_window(target.id)
        source, origin = f"window:{window.id} {window.title}", (window.x, window.y)
    return _store_capture(image, source, *origin, target)[1]["captureId"]
```

3. `capture_monitor` の最後の `return` を次に置き換える。

```python
    return _capture_result(
        image, f"monitor:{monitor.id} {monitor.name}", monitor.x, monitor.y, Target("monitor", monitor.id)
    )
```

4. `capture_window` の最後の `return` を次に置き換える。

```python
    return _capture_result(
        image, f"window:{window.id} {window.title}", window.x, window.y, Target("window", window.id)
    )
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `57 passed`

- [ ] **Step 7: コミットする**

```bash
git add src/ai_desktop/captures.py src/ai_desktop/imaging.py src/ai_desktop/server.py tests/test_captures.py tests/test_imaging.py tests/test_server.py
git commit -F - <<'EOF'
feat: record capture targets and allow origin override in image_to_screen

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Win32 の操作モジュールと実機スモークテスト

**Goal:** クリック・ダブルクリック・マウス位置・前面化（Alt キーの回避策）・最小化と復元・タイトル検索を行う `control.py` と、試験用ウィンドウ・スモークスクリプトを作り、実機で動作を確かめる。

**Files:**
- Create: `src/ai_desktop/control.py`
- Create: `scripts/click_target.py`
- Create: `scripts/control_smoke.py`

**Acceptance Criteria:**
- [ ] `PYTHONIOENCODING=utf-8 uv run python scripts/control_smoke.py` が例外なく終わる
- [ ] 出力が `bring back original: True`、`bring target: True`、`after click: {'single': 1, 'double': 0}`、`after double: {'single': 2, 'double': 1}`、`cursor restored: True`、`minimized: True`、`restored to front: True` になる
- [ ] 同じスモークテストを 3 回続けて実行し、3 回とも上の値になる
- [ ] 試験用ウィンドウは終了時に閉じ、元の前面ウィンドウが前面に戻る
- [ ] `uv run pytest -v` が引き続き全件 PASS（57 件）

**Verify:** `for i in 1 2 3; do PYTHONIOENCODING=utf-8 uv run python scripts/control_smoke.py | grep after; done` → 3 回とも `after click: {'single': 1, 'double': 0}` と `after double: {'single': 2, 'double': 1}`

**Steps:**

- [ ] **Step 1: `src/ai_desktop/control.py` を作る**

```python
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
    """Left-click (or double-click) at physical screen coordinates."""
    if not _user32.SetCursorPos(x, y):
        raise CaptureError(f"マウスを ({x}, {y}) に移動できませんでした（Win32 エラー {ctypes.get_last_error()}）。")
    _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))
    if double:
        time.sleep(DOUBLE_CLICK_GAP_SECONDS)
        _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))


def _activate(hwnd: int) -> bool:
    _user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + FOREGROUND_WAIT_SECONDS
    while time.monotonic() < deadline:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


def _mouse(flags: int) -> INPUT:
    event = INPUT(type=INPUT_MOUSE)
    event.u.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
    return event


def _key(vk: int, up: bool = False) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return event


def _send(*events: INPUT) -> None:
    array = (INPUT * len(events))(*events)
    if _user32.SendInput(len(events), array, ctypes.sizeof(INPUT)) != len(events):
        raise CaptureError(f"入力を送れませんでした（Win32 エラー {ctypes.get_last_error()}）。")
```

- [ ] **Step 2: `scripts/click_target.py` を作る**

```python
"""A harmless window for manual and end-to-end tests: counts clicks and double-clicks.

Every change is also printed to stdout as one JSON line, so test scripts can read it."""

import json
import sys
import tkinter as tk

TITLE = "ai-desktop クリック試験"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    counts = {"single": 0, "double": 0}
    root = tk.Tk()
    root.title(TITLE)
    root.geometry("520x320+240+240")
    label = tk.Label(root, font=("Yu Gothic UI", 20), bg="#f4f4f4")
    label.pack(expand=True, fill="both")

    def show() -> None:
        label.config(text=f"クリック: {counts['single']}\nダブルクリック: {counts['double']}")
        print(json.dumps(counts), flush=True)

    def on_click(_event: tk.Event) -> None:
        counts["single"] += 1
        show()

    def on_double(_event: tk.Event) -> None:
        counts["double"] += 1
        show()

    label.bind("<Button-1>", on_click)
    label.bind("<Double-Button-1>", on_double)
    show()
    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: `scripts/control_smoke.py` を作る**

試験用ウィンドウはタイトルの**完全一致**で探す。ビューアーのタブを開いていると、そのタイトルにも同じ文字列が入るため。

```python
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
```

- [ ] **Step 4: スモークテストを 3 回実行する**

ユーザーのデスクトップで、試験用ウィンドウが数秒表示されてクリックされる。ほかのウィンドウは操作しない。

Run: `for i in 1 2 3; do PYTHONIOENCODING=utf-8 uv run python scripts/control_smoke.py; done`
Expected: 3 回とも Acceptance Criteria の値。`after click` が `{}` や `single: 0` になる場合は、前面化直後の取りこぼし（`ACTIVATION_SETTLE_SECONDS`）を疑い、DONE_WITH_CONCERNS で出力を添えて報告する。

- [ ] **Step 5: 既存テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `57 passed`

- [ ] **Step 6: コミットする**

```bash
git add src/ai_desktop/control.py scripts/click_target.py scripts/control_smoke.py
git commit -F - <<'EOF'
feat: add Win32 mouse/window control with smoke test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: 高 DPI 非対応アプリのウィンドウ撮影の修正

**Goal:** 高 DPI 非対応のウィンドウを PrintWindow で撮ると左上の一部にしか写らない問題を、ウィンドウとモニターの DPI を比べて「写った部分を切り出して元のサイズに拡大」して直す。

**Files:**
- Modify: `src/ai_desktop/imaging.py`（`restore_dpi_scaling` を追加）
- Modify: `src/ai_desktop/capture.py`（import、argtypes、`_capture_window` の return、`_monitor_dpi` を追加）
- Test: `tests/test_imaging.py`

**Acceptance Criteria:**
- [ ] `restore_dpi_scaling(image, 96, 144)` が、左上 2/3 の内容を元のサイズに引き伸ばす（右下の画素が内容の色になる）
- [ ] ウィンドウ DPI がモニター DPI 以上、または 0（取得失敗）のときは、同じ画像オブジェクトをそのまま返す
- [ ] 実機で、試験用ウィンドウ（tkinter、高 DPI 非対応）を `capture_window` で撮ると、右下付近の画素が背景色（黒ではない）になり、画像全体に中身が写る
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `59 passed`。Step 5 のスクリプトで `window dpi: 96 monitor dpi: 144`（表示スケール 150% の場合）と、黒ではない右下の画素を確認する。

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_imaging.py` の import を次に置き換える。

```python
from ai_desktop.imaging import (
    build_meta,
    encode_jpeg,
    fit_size,
    image_to_screen,
    restore_dpi_scaling,
    shrink,)
```

ファイル末尾に追加する。

```python
def test_restore_dpi_scaling_stretches_the_rendered_part():
    image = Image.new("RGB", (300, 150), "black")
    image.paste(Image.new("RGB", (200, 100), "red"), (0, 0))  # rendered at 96 dpi on a 144 dpi monitor
    restored = restore_dpi_scaling(image, 96, 144)
    assert restored.size == (300, 150)
    assert restored.getpixel((290, 140)) == (255, 0, 0)


def test_restore_dpi_scaling_leaves_dpi_aware_windows_alone():
    image = Image.new("RGB", (300, 150))
    assert restore_dpi_scaling(image, 144, 144) is image
    assert restore_dpi_scaling(image, 0, 144) is image
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_imaging.py -v`
Expected: FAIL（`ImportError: cannot import name 'restore_dpi_scaling'`）

- [ ] **Step 3: `imaging.py` に `restore_dpi_scaling` を追加する**

`def build_meta(` の直前に次の関数を追加する。

```python
def restore_dpi_scaling(image: Image.Image, window_dpi: int, monitor_dpi: int) -> Image.Image:
    """Undo DPI virtualization in a PrintWindow image of a DPI-unaware window.

    Such a window renders at window_dpi into the top-left of a bitmap sized for monitor_dpi,
    leaving the rest black; crop that part and scale it back up to the full size."""
    if window_dpi <= 0 or window_dpi >= monitor_dpi:
        return image
    ratio = window_dpi / monitor_dpi
    content = image.crop((0, 0, max(1, round(image.width * ratio)), max(1, round(image.height * ratio))))
    return content.resize(image.size, Image.LANCZOS)
```

- [ ] **Step 4: `capture.py` を変更する**

1. `from ai_desktop.imaging import CaptureError, MonitorInfo, WindowInfo` を `from ai_desktop.imaging import CaptureError, MonitorInfo, WindowInfo, restore_dpi_scaling` に変える。
2. `_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long` の直後に次を追加する。

```python
_user32.GetDpiForWindow.argtypes = [wintypes.HWND]
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
```

3. `_capture_window` の `return _print_window(hwnd, info.width, info.height), info` を次の 2 行に置き換える。

```python
        image = _print_window(hwnd, info.width, info.height)
        return restore_dpi_scaling(image, _user32.GetDpiForWindow(hwnd), _monitor_dpi(hwnd)), info
```

4. `def _window_info(` の直前に次の関数を追加する。

```python
def _monitor_dpi(hwnd: int) -> int:
    """Effective DPI of the monitor showing the window; 0 if it cannot be read."""
    monitor = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    if ctypes.WinDLL("shcore").GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)):
        return 0
    return dpi_x.value
```

- [ ] **Step 5: テストと実機確認**

Run: `uv run pytest -v`
Expected: `59 passed`

実機確認（試験用ウィンドウが数秒表示される）:

```bash
PYTHONIOENCODING=utf-8 uv run python - <<'EOF'
import sys, time
sys.path.insert(0, "scripts")
from control_smoke import find_target, start_target
from ai_desktop import capture
capture.enable_dpi_awareness()
app, lines = start_target()
try:
    for _ in range(50):
        hwnd = find_target()
        if hwnd:
            break
        time.sleep(0.1)
    time.sleep(0.8)
    print("window dpi:", capture._user32.GetDpiForWindow(hwnd), "monitor dpi:", capture._monitor_dpi(hwnd))
    image, info = capture.capture_window(hwnd)
    print(info.title, image.size, "bottom-right:", image.getpixel((image.width - 30, image.height - 30)))
finally:
    app.terminate()
EOF
```

Expected: 表示スケールが 100% より大きいモニターでは `window dpi: 96` で、モニター DPI のほうが大きい。`bottom-right` が `(0, 0, 0)` ではなく明るい色（試験用ウィンドウの背景、例 `(244, 244, 244)`）。

- [ ] **Step 6: コミットする**

```bash
git add src/ai_desktop/imaging.py src/ai_desktop/capture.py tests/test_imaging.py
git commit -F - <<'EOF'
fix: capture DPI-unaware windows at full size

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: ビューアーページの枠組み

**Goal:** SSE で表示内容を受け取り、ステージを拡大縮小し、クリック・ダブルクリックをサーバーに送るビューアーページ（`render_shell`）と、その CSP（`content_security_policy`）を `annotate.py` に追加する。既存のファイル保存方式の関数は Task 6 まで残す。

**Files:**
- Modify: `src/ai_desktop/annotate.py`（`def render_page(` の直前に追加）
- Test: `tests/test_annotate.py`

**Acceptance Criteria:**
- [ ] `content_security_policy("n0nce")` が `default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-n0nce'; connect-src 'self'` を返す
- [ ] `render_shell(nonce)` のナンス付きスクリプトが `</head>` より前にあり、`#status`、空の `#stage`（`#shot` と `#annotations`）、`EventSource("/events?t="`、`X-AI-Desktop-Token` ヘッダーを含む
- [ ] 部品クラス（`.box`、`.badge`、`.note`、`.arrow`）と矢じりマーカー、`document.title = "ai-desktop | " + next.title` を含む
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `62 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_annotate.py` の `from ai_desktop.annotate import render_page, save_page` を次に置き換える。

```python
from ai_desktop.annotate import (
    VIEWER_TITLE_PREFIX,
    content_security_policy,
    render_page,
    render_shell,
    save_page,)
```

ファイル末尾に追加する。

```python
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


def test_viewer_shell_keeps_helper_classes_and_title_prefix():
    page = render_shell("n0nce")
    for selector in ("#annotations .box", "#annotations .badge", "#annotations .note", "#annotations .arrow"):
        assert selector in page
    assert 'id="arrowhead"' in page
    assert VIEWER_TITLE_PREFIX == "ai-desktop | "
    assert 'document.title = "ai-desktop | " + next.title' in page
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_annotate.py -v`
Expected: FAIL（`ImportError: cannot import name 'VIEWER_TITLE_PREFIX'`）

- [ ] **Step 3: `annotate.py` に追加する**

`def render_page(` の直前（`_FIT_SCRIPT` の定義の後）に、次をそのまま追加する。

```python
VIEWER_TITLE_PREFIX = "ai-desktop | "

_VIEWER_CSS = """
#stage { cursor: crosshair; }
#status { position: fixed; top: 12px; right: 12px; z-index: 10; display: none; padding: 8px 14px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.78); color: #fff;
  font: 14px/1.5 system-ui, "Yu Gothic UI", sans-serif; }
#status.show { display: block; }
#status.error { background: #e5484d; }
"""

# The live viewer: receives views over SSE, scales the stage, and posts clicks back.
_VIEWER_SCRIPT = """
const token = new URLSearchParams(location.search).get("t");
let view = null;
let busy = false;
let pending = null;

function fit() {
  if (!view) return;
  const scale = document.documentElement.clientWidth / view.width;
  document.getElementById("stage").style.transform = "scale(" + scale + ")";
  document.getElementById("viewport").style.height = view.height * scale + "px";
}

function status(text, isError) {
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
    status(result.error || "", Boolean(result.error));
  } catch (error) {
    status("操作できませんでした: " + error, true);
  } finally {
    busy = false;
  }
}

addEventListener("DOMContentLoaded", () => {
  document.getElementById("stage").addEventListener("click", (event) => {
    clearTimeout(pending);
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
        '<div id="viewport"><div id="stage">'
        '<img id="shot" alt="">'
        '<div id="annotations"></div>'
        "</div></div>\n"
        "</body></html>\n"
    )
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `62 passed`

- [ ] **Step 5: コミットする**

```bash
git add src/ai_desktop/annotate.py tests/test_annotate.py
git commit -F - <<'EOF'
feat: add live viewer page shell and CSP

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: ビューアーの Web サーバーとクリック操作

**Goal:** `Viewer`（127.0.0.1 の Web サーバー、合言葉・Host・Origin の確認、SSE、ack、画像配信、タブの再利用判定、クリック操作の手順）を `viewer.py` に作り、偽の control と実際の HTTP サーバーでテストする。

**Files:**
- Create: `src/ai_desktop/viewer.py`
- Test: `tests/test_viewer.py`

**Acceptance Criteria:**
- [ ] ウィンドウ撮影へのクリックで、control の呼び出しが `find_window → cursor_pos → minimize(ブラウザ) → bring_to_front(対象) → window_origin(対象) → click(今の origin 基準の座標) → set_cursor(元の位置) → restore(ブラウザ)` の順になり、新しい captureId が注釈なしで表示内容になる
- [ ] モニター撮影へのダブルクリックは撮影時の origin で座標を求め、前面化はしない
- [ ] 途中で失敗しても `set_cursor` と `restore` が最後に呼ばれ、クリックはされない
- [ ] 画像の範囲外は control を呼ぶ前にエラー、ブラウザと同じウィンドウはエラー、操作中の 2 つ目はエラー
- [ ] 合言葉が違う GET、合言葉か Origin が違う POST は 403。ページは CSP（`connect-src 'self'` とナンス）、`Referrer-Policy: no-referrer`、`Cache-Control: no-store` 付き
- [ ] `/image/<id>` が保存済みの背景を返し、未知の id は 404
- [ ] タブがないときの `publish` は `False`、SSE で受け取って ack を返すタブがあるときは `True`
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `74 passed`（`tests/test_viewer.py` の 12 件を含む）

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_viewer.py` を作る。

```python
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

    def __init__(self, browser=BROWSER, origin=(100, 200), fail_origin=False):
        self.calls = []
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

    def bring_to_front(self, hwnd):
        self.calls.append(("bring_to_front", hwnd))
        return True

    def window_origin(self, hwnd):
        self.calls.append(("window_origin", hwnd))
        if self.fail_origin:
            raise CaptureError("操作対象のウィンドウが見つかりません。撮影し直してください。")
        return self.origin

    def click(self, x, y, double):
        self.calls.append(("click", x, y, double))

    def set_cursor(self, x, y):
        self.calls.append(("set_cursor", x, y))

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
    def recapture(target):
        meta = WINDOW_META if target.kind == "window" else MONITOR_META
        return store.add(b"fresh-jpeg", meta, target)

    viewer = Viewer(store, recapture, control, settle_seconds=0, ack_timeout=1.0, heartbeat_seconds=0.2)
    yield viewer
    viewer.close()


# --- perform_click ----------------------------------------------------------------------------


def test_click_on_window_capture_follows_the_window(viewer, control):
    new_id = viewer.perform_click("c2", 10, 20, False)
    assert new_id == "c3"
    assert control.calls == [
        ("find_window", "ai-desktop | "),
        ("cursor_pos",),
        ("minimize", BROWSER),
        ("bring_to_front", 42),
        ("window_origin", 42),
        ("click", 110, 220, False),
        ("set_cursor", 5, 6),
        ("restore", BROWSER),
    ]
    assert viewer.next_view(0, 0)["captureId"] == "c3"
    assert viewer.next_view(0, 0)["html"] == ""


def test_double_click_on_monitor_capture_uses_capture_origin(viewer, control):
    viewer.perform_click("c1", 49, 98, True)
    assert ("click", 100, 200, True) in control.calls
    assert not any(call[0] in ("bring_to_front", "window_origin") for call in control.calls)


def test_failed_click_still_restores_cursor_and_browser(viewer, control):
    control.fail_origin = True
    with pytest.raises(CaptureError, match="操作対象のウィンドウが見つかりません"):
        viewer.perform_click("c2", 10, 20, False)
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]
    assert not any(call[0] == "click" for call in control.calls)


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
    assert (status, result) == (200, {"ok": True, "captureId": "c3"})
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
        while len(received) < 1:
            line = response.fp.readline().decode("utf-8")
            if line.startswith("data: "):
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_viewer.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'ai_desktop.viewer'`）

- [ ] **Step 3: `src/ai_desktop/viewer.py` を作る**

```python
"""Local viewer: shows the annotated capture in one reused browser tab and turns its clicks into real ones."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ai_desktop.annotate import VIEWER_TITLE_PREFIX, content_security_policy, render_shell
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, image_to_screen

_log = logging.getLogger(__name__)

ACK_TIMEOUT_SECONDS = 1.5
HEARTBEAT_SECONDS = 15.0
SETTLE_SECONDS = 0.7
MAX_BODY_BYTES = 1024
TOKEN_HEADER = "X-AI-Desktop-Token"


class Viewer:
    """Serves the current view to browser tabs over SSE and performs clicks sent back from them.

    control is the ai_desktop.control module in production; tests pass a fake with the same
    functions (find_window, cursor_pos, minimize, bring_to_front, window_origin, click,
    set_cursor, restore)."""

    def __init__(
        self,
        store: CaptureStore,
        recapture: Callable[[Target], str],
        control: Any,
        settle_seconds: float = SETTLE_SECONDS,
        ack_timeout: float = ACK_TIMEOUT_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self._store = store
        self._recapture = recapture
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
            server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, name="ai-desktop-viewer", daemon=True).start()
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

    def perform_click(self, capture_id: str, x: float, y: float, double: bool) -> str:
        """Click the real screen where (x, y) is on the capture, then show a fresh capture."""
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
                if browser is not None:
                    self._control.minimize(browser)
                origin = None
                if target.kind == "window":
                    self._control.bring_to_front(target.id)
                    origin = self._control.window_origin(target.id)
                screen_x, screen_y = image_to_screen(meta, x, y, origin)
                self._control.click(screen_x, screen_y, double)
                time.sleep(self._settle_seconds)
                new_id = self._recapture(target)
            finally:
                self._control.set_cursor(*cursor)
                if browser is not None:
                    self._control.restore(browser)
            _, new_meta = self._store.get(new_id)
            self.publish(new_id, "", new_meta["source"])
            return new_id
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
            if not (self._host_ok() and secrets.compare_digest(token, viewer.token)):
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
            token_ok = secrets.compare_digest(self.headers.get(TOKEN_HEADER, ""), viewer.token)
            if not (self._host_ok() and token_ok and self.headers.get("Origin") == viewer.origin):
                self._send_json(403, {"error": "forbidden"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._send_json(413, {"error": "要求が大きすぎます。"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._send_json(400, {"error": "要求の形式が正しくありません。"})
                return
            if path == "/ack":
                viewer.acknowledge(int(body.get("version", 0)))
                self._send_json(200, {"ok": True})
            elif path == "/click":
                self._click(body)
            else:
                self._send_json(404, {"error": "not found"})

        def _click(self, body: dict) -> None:
            try:
                new_id = viewer.perform_click(
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
                self._send_json(200, {"ok": True, "captureId": new_id})

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
```

- [ ] **Step 4: テストが通ることを確認する（3 回）**

HTTP サーバーとスレッドを使うので、不安定でないことを確かめる。

Run: `for i in 1 2 3; do uv run pytest -q | tail -1; done`
Expected: 3 回とも `74 passed`

- [ ] **Step 5: コミットする**

```bash
git add src/ai_desktop/viewer.py tests/test_viewer.py
git commit -F - <<'EOF'
feat: add local viewer server with SSE, tab reuse and click handling

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: show_annotated をビューアーに切り替える

**Goal:** `show_annotated` をビューアー経由（開いているタブがあれば更新して前面に、なければブラウザを開く）に切り替え、一時フォルダへの HTML 保存と関連コード・テストを取り除く。

**Files:**
- Modify: `src/ai_desktop/server.py`
- Modify: `src/ai_desktop/annotate.py`（ファイル全体を置き換え）
- Modify: `tests/test_annotate.py`（ファイル全体を置き換え）
- Modify: `tests/test_server.py`

**Acceptance Criteria:**
- [ ] タブがないとき、`show_annotated` は `viewer.publish(capture_id, html, title または source)` を呼んでから `viewer.open_browser()` を呼び、「ブラウザで開きました: <URL>」を返す
- [ ] タブがあるとき（publish が True）は `viewer.focus_browser()` を呼び、「既存のタブを更新しました。」を返す（ブラウザは開かない）
- [ ] サーバー起動の `OSError` は「表示用のローカルサーバーを起動できませんでした」、ブラウザ起動の `OSError` は「ブラウザで開けませんでした: <URL>」を含むツールエラーになる
- [ ] 未知の captureId、空・長すぎる html は今までどおりエラーで、publish されない
- [ ] `INSTRUCTIONS` が 1 段落のまま、タブの再利用とページ上のクリックに触れている
- [ ] `annotate.py` に `render_page`、`save_page`、`open_in_browser`、`ANNOTATION_DIR`、`KEEP_PAGES`、`_FIT_SCRIPT` が残っていない
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `66 passed`

**Steps:**

- [ ] **Step 1: テストを書き換える**

`tests/test_annotate.py` を次の内容に置き換える。

```python
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


def test_viewer_shell_keeps_helper_classes_and_title_prefix():
    page = render_shell("n0nce")
    for selector in ("#annotations .box", "#annotations .badge", "#annotations .note", "#annotations .arrow"):
        assert selector in page
    assert 'id="arrowhead"' in page
    assert VIEWER_TITLE_PREFIX == "ai-desktop | "
    assert 'document.title = "ai-desktop | " + next.title' in page
```

`tests/test_server.py` を次のように変更する。

1. `from ai_desktop import annotate, capture, server` を `from ai_desktop import capture, server` に変える。
2. `@pytest.fixture` / `def opened(` から、`def test_instructions_are_one_paragraph` の直前までを、次の内容に置き換える（`test_instructions_are_one_paragraph` 自体は残す）。

```python
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

    def publish(self, capture_id, html, title):
        if self.start_error is not None:
            raise self.start_error
        self.published.append((capture_id, html, title))
        return self.delivered

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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest -v`
Expected: FAIL（`test_server.py` の `server.viewer` が無い、`show_annotated` の戻り値が違う、など）

- [ ] **Step 3: `server.py` を変更する**

1. `import secrets` の行を削除する。
2. `from ai_desktop import annotate, capture` を `from ai_desktop import capture, control` に変える。
3. `from ai_desktop.imaging import ...` の行の直後に `from ai_desktop.viewer import Viewer` を追加する。
4. `INSTRUCTIONS` を次に置き換える。

```python
INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels). To point at things on screen, call \
show_annotated with the capture's captureId and HTML positioned in that image's pixel \
coordinates; it shows in the user's browser, reusing the open viewer tab, and the user \
can click on the page to click the real screen."""
```

5. `_recapture` 関数の直後（`@mcp.tool(structured_output=False)` / `def list_monitors` の前）に、次の 1 行を追加する（前後に空行 2 つ）。

```python
viewer = Viewer(captures, _recapture, control)
```

6. `show_annotated` 関数全体を、次の内容に置き換える。

```python
@mcp.tool(structured_output=False)
def show_annotated(capture_id: str, html: str, title: str | None = None) -> str:
    """Show the user one of your captures with your annotations drawn on top, in their
    default browser. Use it when pointing at places on screen makes your advice clearer.
    An open viewer tab is reused. The user can click or double-click on the page to click
    the real screen at that spot; the page then shows a fresh capture without annotations.

    capture_id: the captureId from a capture's metadata (the latest 10 are kept).
    html: elements positioned absolutely with style left/top in that capture's image
    pixels (imageWidth x imageHeight, i.e. the image you saw). Helper classes:
    .box (outline; left/top/width/height), .badge (numbered circle; left/top is its
    center), .note (callout; left/top is its top-left corner), and for arrows
    <svg class="layer"><line class="arrow" x1=".." y1=".." x2=".." y2=".."/></svg>
    (svg.layer covers the image, in image pixels). Scripts and external resources are
    blocked. title: optional page title."""
    if not html.strip():
        raise ToolError("html が空です。枠や注釈の HTML を指定してください。")
    if len(html) > MAX_HTML_CHARS:
        raise ToolError(f"html が長すぎます（{len(html)} 文字）。{MAX_HTML_CHARS} 文字以内にしてください。")
    with _reported():
        _, meta = captures.get(capture_id)
        try:
            delivered = viewer.publish(capture_id, html, title or meta["source"])
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
```

- [ ] **Step 4: `annotate.py` を次の内容に置き換える**

```python
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
"""

# The live viewer: receives views over SSE, scales the stage, and posts clicks back.
_VIEWER_SCRIPT = """
const token = new URLSearchParams(location.search).get("t");
let view = null;
let busy = false;
let pending = null;

function fit() {
  if (!view) return;
  const scale = document.documentElement.clientWidth / view.width;
  document.getElementById("stage").style.transform = "scale(" + scale + ")";
  document.getElementById("viewport").style.height = view.height * scale + "px";
}

function status(text, isError) {
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
    status(result.error || "", Boolean(result.error));
  } catch (error) {
    status("操作できませんでした: " + error, true);
  } finally {
    busy = false;
  }
}

addEventListener("DOMContentLoaded", () => {
  document.getElementById("stage").addEventListener("click", (event) => {
    clearTimeout(pending);
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
        '<div id="viewport"><div id="stage">'
        '<img id="shot" alt="">'
        '<div id="annotations"></div>'
        "</div></div>\n"
        "</body></html>\n"
    )
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `66 passed`

- [ ] **Step 6: コミットする**

```bash
git add src/ai_desktop/server.py src/ai_desktop/annotate.py tests/test_annotate.py tests/test_server.py
git commit -F - <<'EOF'
feat: serve annotations through the live viewer and drop temp-file pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: README と実機での通しテスト

**Goal:** README を新しい動作に合わせ、実機の通しテスト（MCP サーバー経由でタブの再利用とページ経由のクリック・ダブルクリックの到達）を実行し、最後にユーザーにブラウザ上でのクリックを試してもらう。

**Files:**
- Create: `scripts/e2e_viewer.py`
- Modify: `README.md`

**Acceptance Criteria:**
- [ ] README のツール表の `show_annotated` の説明、使い方の例、「既知の制限」が新しい動作に合っている（一時フォルダへの保存の記述がない）
- [ ] `scripts/e2e_viewer.py` の出力に `first show: ブラウザで開きました: http://127.0.0.1:`、`second show: 既存のタブを更新しました。`、`click: {'ok': True, ...} {'single': 1, 'double': 0}`、`double: {'ok': True, ...} {'single': 2, 'double': 1}`、`E2E OK` が出る
- [ ] 通しテストのあと、ビューアーのタブを撮影すると、撮り直した試験用ウィンドウ（クリック 2・ダブルクリック 1）が、黒い欠けなしで表示されている
- [ ] ユーザーが、Claude Code から開いたページ上でクリックとダブルクリックを試し、実際の画面に伝わってページが更新されたと確認する

**Verify:** `PYTHONIOENCODING=utf-8 uv run python scripts/e2e_viewer.py` → `E2E OK`

**Steps:**

- [ ] **Step 1: `scripts/e2e_viewer.py` を作る**

```python
"""Real-machine end-to-end check of the viewer, run against the real MCP server over stdio.

1. show_annotated opens a browser tab, and a second call reuses it.
2. A click and a double-click sent the way the page sends them reach a real window.

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


def post_click(url: str, capture_id: str, x: float, y: float, double: bool) -> dict:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    token = parse_qs(parts.query)["t"][0]
    request = urllib.request.Request(
        f"{origin}/click",
        data=json.dumps({"captureId": capture_id, "x": x, "y": y, "double": double}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-AI-Desktop-Token": token, "Origin": origin},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


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
        doubled = await asyncio.to_thread(post_click, url, clicked["captureId"], *center, True)
        state = latest(lines, 1.0)
        print("double:", doubled, state)
        assert doubled.get("ok"), doubled
        assert state.get("single", 0) >= 1 and state.get("double", 0) >= 1, state


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
```

- [ ] **Step 2: README を変更する**

1. 「使い方の例」の最後の行を次に置き換える。

```markdown
- 「どこを押せばいいか、画面に印をつけて見せて」（注釈付きのスクショがブラウザに表示されます。ページ上をクリックすると実際の画面もクリックされます）
```

2. ツール表の `show_annotated` の行を次に置き換える。

```markdown
| `show_annotated` | 撮影画像を背景に、Claude が書いた枠・番号・吹き出し・矢印を重ねてブラウザに表示する（撮影メタデータの `captureId` を `capture_id` に指定）。開いているタブは使い回す。ページ上のクリック・ダブルクリックは実際の画面に伝わり、撮り直した画面に更新される |
```

3. 「既知の制限」の `- 撮影ツールはディスクに保存しません。…直近30件まで保存されます。` の行を、次の行に置き換える。

```markdown
- スクショはディスクに保存しません。注釈ページは MCP サーバー内の Web サーバー（127.0.0.1 のみ）から配信され、Claude Code のセッションが終わると表示できなくなります。
- ページ上でクリックすると、ブラウザを一時的に最小化して実際の画面をクリックします。ビューアーのタブと同じブラウザのウィンドウにある別のタブは操作できません（対象のタブは別ウィンドウに分けてください）。
- ウィンドウを前面に出すために Alt キーを一瞬押すので、まれにアプリのメニューバーが反応することがあります。
- 管理者権限で動いているアプリは、ページからクリックできません。
```

4. 「実機の動作確認」のコードブロックに、次の 2 行を追加する。

```powershell
uv run python scripts/control_smoke.py   # クリック・前面化・最小化の確認（試験用ウィンドウが開きます）
uv run python scripts/e2e_viewer.py      # タブの再利用とページ経由のクリックの確認（ブラウザのタブが開きます）
```

- [ ] **Step 3: コミットする**

```bash
git add scripts/e2e_viewer.py README.md
git commit -F - <<'EOF'
docs: document live viewer and add end-to-end script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 4: 通しテストを実行する**

ブラウザのタブが 1 つ開き、試験用ウィンドウが数秒表示されてクリックされる。ほかのウィンドウは操作しない。タブは閉じずに残す。

Run: `PYTHONIOENCODING=utf-8 uv run python scripts/e2e_viewer.py 2>&1 | grep -v "^INFO\|Processing request"`
Expected: Acceptance Criteria の行と `E2E OK`

- [ ] **Step 5: ビューアーのタブを撮影して確認する**

```bash
PYTHONIOENCODING=utf-8 uv run python - <<'EOF'
from pathlib import Path
from ai_desktop import capture, control
capture.enable_dpi_awareness()
hwnd = control.find_window("ai-desktop | ")
image, info = capture.capture_window(hwnd)
image.thumbnail((1200, 1200))
Path("smoke-out").mkdir(exist_ok=True)
image.save("smoke-out/viewer-e2e.png")
print(info.title, image.size)
EOF
```

`smoke-out/viewer-e2e.png` を Read で開く。
Expected: 試験用ウィンドウの撮り直し画像（「クリック: 2」「ダブルクリック: 1」）が、右側・下側が黒く欠けることなく表示されている。サーバーは終了しているので、右上に「サーバーとの接続が切れました」が出ていてよい。

- [ ] **Step 6: ユーザーに試してもらう**

ユーザーに次を依頼し、結果を待つ。
1. VS Code の Claude Code パネルで、新しいセッションを開く（新しい MCP サーバーを読み込むため）。
2. 「画面を見て、どこを押せばいいか印をつけて見せて」と送り、ブラウザにページが開くことを確認する。
3. もう一度別のお願いをして、新しいタブが増えずに同じタブが更新されることを確認する。
4. ページ上で、押しても問題のない場所をクリック・ダブルクリックし、実際の画面がクリックされ、ページが撮り直した画面に更新されることを確認する。

