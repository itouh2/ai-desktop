# move_mouse（Claude が動かすマウス移動）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude が撮影画像の 1 点へマウスカーソルを動かし、待ってから同じ対象を撮り直す MCP ツール `move_mouse` を加える（クリックはしない）。

**Architecture:** 入力の送信（Win32 `SendInput`）を新モジュール `inputs.py` にまとめ、画面の 1 点を操作する前後の準備と後片付け（排他ロック・範囲チェック・前面化・座標変換・ブラウザの最小化と復元）を新モジュール `pointer.py` の `Pointer.at()` にまとめる。既存のページからのクリック（`Viewer.perform_click`）と新しい `move_mouse` の両方が `Pointer` を使い、ロックを共有する。

**Tech Stack:** Python 3.11+ / uv / mcp 2.x（`MCPServer`）/ pywin32 + ctypes（SendInput）/ Pillow / pytest / tkinter（試験用ウィンドウ）

**Global Constraints:**
- 仕様書: `docs/superpowers/specs/2026-10-05-move-mouse-design.md`
- PyAutoGUI などの新しい依存は加えない（`pyproject.toml` の `dependencies` を変えない）
- `move_mouse` はクリックや押下のイベントを一切送らない
- エラーはすべて `CaptureError`（日本語の文言）で投げ、`server.py` の `_reported()` で `ToolError` に変える
- 撮影・注釈の座標は「その撮影画像のピクセル座標」。画面座標は `image_to_screen(meta, x, y, origin)` で求める
- `wait_seconds` は 0〜5 秒に丸める（範囲外はエラーにしない）
- テストは `uv run --no-sync pytest -q`。各タスクの終わりで全件 PASS
- 文字列リテラル・コメントの言語は既存に合わせる（ユーザー向けの文言は日本語、docstring とコメントは英語）

**User decisions (already made):**
- 最初の段階は「移動＋撮影まで」。クリックはしない（2026-10-05）
- 動かしてよいかは Claude Code のツール許可に任せる（2026-10-05）
- 戻り値は 1 点につき対象全体を 1 枚（既存の撮影と同じ形）（2026-10-05）
- 方式は既存の Win32 `SendInput` を広げる（A 案）。PyAutoGUI はプライマリモニターのみ対応のため今は採用しない（2026-10-05）
- 送信処理を独立したモジュールに分け、将来の差し替えに備える（2026-10-05）

---

## ファイル構成

| ファイル | 役割 | タスク |
|---|---|---|
| `src/ai_desktop/inputs.py`（新規） | マウスとキーの送信（`move`、`click`、`tap_alt`）。SendInput を使う唯一の場所 | 1 |
| `src/ai_desktop/control.py`（変更） | ウィンドウ操作だけを残す。`click` は `inputs` に任せる | 1 |
| `tests/test_inputs.py`（新規） | 送るイベントの中身 | 1 |
| `src/ai_desktop/pointer.py`（新規） | 1 点を操作する前後の処理（`Pointer`、`Spot`） | 2 |
| `src/ai_desktop/viewer.py`（変更） | `perform_click` と `recapture_current` が `Pointer` を使う | 2 |
| `tests/fakes.py`（新規） | `FakeControl` を `test_viewer.py` から移す（複数のテストで共有） | 2 |
| `tests/test_pointer.py`（新規） | `Pointer.at` の準備と後片付け | 2 |
| `tests/test_viewer.py`（変更） | `FakeControl` を `fakes` から読み込む。後片付けの期待値を直す | 2 |
| `src/ai_desktop/server.py`（変更） | `move_mouse` ツール、`Pointer` の生成、INSTRUCTIONS | 3 |
| `tests/test_server.py`（変更） | `move_mouse` のテスト、ツール数 7 | 3 |
| `scripts/click_target.py`（変更） | カーソルが乗ると背景が黄色になり、出入りの回数を出力する | 4 |
| `scripts/e2e_move_mouse.py`（新規） | 実機での通し確認 | 4 |
| `README.md`、`.claude/skills/ai-desktop-guide/SKILL.md`、`docs/games/slay-the-spire2/README.md`、仕様書 | ドキュメント | 5 |

---

### Task 1: 入力の送信を inputs.py に分ける

**Goal:** SendInput による入力の送信を `inputs.py` に移し、カーソル移動の `inputs.move` を加える（既存の動作は変えない）。

**Files:**
- Create: `src/ai_desktop/inputs.py`
- Modify: `src/ai_desktop/control.py`（ファイル全体を置き換え）
- Test: `tests/test_inputs.py`

**Acceptance Criteria:**
- [ ] `inputs.move(x, y)` が 1 回の SendInput で 1 つのマウスイベントを送る。フラグは `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK` のみで、ボタンのフラグを含まない
- [ ] 仮想デスクトップの左上が負の座標（例: x=-1920）でも、左上が 0、右下が 65535 に正規化される
- [ ] `inputs.click(x, y)` は移動・押下・解放の 3 イベント、`double=True` ならさらに押下・解放の 2 イベントを送る（今の `control.click` と同じ）
- [ ] `inputs.tap_alt()` は Alt（VK_MENU）の押下と解放の 2 つのキーイベントを送る
- [ ] SendInput が送れた数が足りないと「入力を送れませんでした」の `CaptureError`
- [ ] `control.py` に SendInput の構造体と `_mouse_at`・`_key`・`_send` が残っていない。`control.click` と `control.bring_to_front` は `inputs` を使う
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync pytest -q` → 全件 PASS（既存 118 件＋新規 6 件）

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_inputs.py`:

```python
import pytest

from ai_desktop import inputs
from ai_desktop.imaging import CaptureError

MOVE_FLAGS = inputs.MOUSEEVENTF_MOVE | inputs.MOUSEEVENTF_ABSOLUTE | inputs.MOUSEEVENTF_VIRTUALDESK


class FakeUser32:
    """Records SendInput batches; the virtual desktop spans two monitors, the left one at x=-1920."""

    def __init__(self, short=False):
        self.batches = []
        self.short = short
        # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
        self.metrics = {76: -1920, 77: 0, 78: 5760, 79: 2160}

    def SendInput(self, count, array, size):  # noqa: N802 - Win32 name
        self.batches.append([array[i] for i in range(count)])
        return 0 if self.short else count

    def GetSystemMetrics(self, index):  # noqa: N802 - Win32 name
        return self.metrics[index]


@pytest.fixture
def user32(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(inputs, "_user32", fake)
    return fake


def test_move_sends_one_absolute_move_without_buttons(user32):
    inputs.move(100, 200)
    assert len(user32.batches) == 1 and len(user32.batches[0]) == 1
    event = user32.batches[0][0]
    assert event.type == inputs.INPUT_MOUSE
    assert event.u.mi.dwFlags == MOVE_FLAGS


def test_move_normalizes_across_the_virtual_desktop(user32):
    inputs.move(-1920, 0)
    inputs.move(3839, 2159)
    first, last = user32.batches[0][0].u.mi, user32.batches[1][0].u.mi
    assert (first.dx, first.dy) == (0, 0)
    assert (last.dx, last.dy) == (65535, 65535)


def test_click_moves_then_presses_and_releases(user32):
    inputs.click(100, 200)
    flags = [event.u.mi.dwFlags for event in user32.batches[0]]
    assert flags == [
        MOVE_FLAGS,
        MOVE_FLAGS | inputs.MOUSEEVENTF_LEFTDOWN,
        MOVE_FLAGS | inputs.MOUSEEVENTF_LEFTUP,
    ]


def test_double_click_presses_twice(user32):
    inputs.click(100, 200, double=True)
    assert [len(batch) for batch in user32.batches] == [3, 2]


def test_tap_alt_presses_and_releases_alt(user32):
    inputs.tap_alt()
    down, up = user32.batches[0]
    assert (down.type, down.u.ki.wVk, down.u.ki.dwFlags) == (inputs.INPUT_KEYBOARD, inputs.VK_MENU, 0)
    assert (up.u.ki.wVk, up.u.ki.dwFlags) == (inputs.VK_MENU, inputs.KEYEVENTF_KEYUP)


def test_short_send_is_an_error(monkeypatch):
    monkeypatch.setattr(inputs, "_user32", FakeUser32(short=True))
    with pytest.raises(CaptureError, match="入力を送れませんでした"):
        inputs.move(100, 200)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --no-sync pytest tests/test_inputs.py -q`
Expected: FAIL（`ImportError: cannot import name 'inputs'`）

- [ ] **Step 3: `src/ai_desktop/inputs.py` を作る**

```python
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
    """Left-click (or double-click) at physical screen coordinates.

    Every event carries the absolute position, so a mouse the user is still moving
    cannot drag the click somewhere else (seen in the smoke test, 2026-10-03)."""
    press = (_mouse_at(x, y, MOUSEEVENTF_LEFTDOWN), _mouse_at(x, y, MOUSEEVENTF_LEFTUP))
    _send(_mouse_at(x, y, 0), *press)
    if double:
        time.sleep(DOUBLE_CLICK_GAP_SECONDS)
        _send(*press)


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
```

- [ ] **Step 4: `src/ai_desktop/control.py` を置き換える**

送信処理を取り除き、`inputs` を使う。ウィンドウ操作の関数は中身を変えない。

```python
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
```

ここから下（`minimize` の本体、`is_minimized`、`restore`、`cursor_pos`、`set_cursor`）は今の `control.py` の 128〜151 行をそのまま残す。そのあとに次を置き、今の `click`、`_activate` 以外（`_mouse_at`、`_key`、`_send`）は削除する。

```python
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
```

確認: `grep -n "SendInput\|_mouse_at\|_key(\|_send(" src/ai_desktop/control.py` が何も出さない。

- [ ] **Step 5: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS（`tests/test_inputs.py` の 6 件を含む）

- [ ] **Step 6: コミット**

```bash
git add src/ai_desktop/inputs.py src/ai_desktop/control.py tests/test_inputs.py
git commit -m "refactor: move SendInput into inputs.py and add inputs.move"
```

---

### Task 2: 1 点の操作の前後処理を pointer.py に分ける

**Goal:** `Viewer.perform_click` の準備と後片付けを `Pointer.at()` に切り出し、ページからのクリックと撮り直しが `Pointer` のロックを共有する（クリックの動作は変えない）。

**Files:**
- Create: `src/ai_desktop/pointer.py`
- Create: `tests/fakes.py`（`tests/test_viewer.py` の `BROWSER` と `FakeControl` を移す）
- Create: `tests/test_pointer.py`
- Modify: `src/ai_desktop/viewer.py`（`__init__`、`recapture_current`、`perform_click`、import）
- Modify: `tests/test_viewer.py`（import と 5 件のテストの期待値）

**Acceptance Criteria:**
- [ ] `Pointer.at(capture_id, x, y, keep_clear)` が、画面座標と元のカーソル位置を持つ `Spot` を渡す
- [ ] ウィンドウ対象は前面化してから、そのときの位置で座標を求める
- [ ] モニター対象では、`keep_clear="point"` はブラウザ内の点のときだけ、`"capture"` はブラウザが撮影範囲に重なるときにブラウザを最小化する
- [ ] 範囲外の点、ブラウザ自身、前面化の失敗、最小化の失敗はそれぞれ `CaptureError`
- [ ] 例外のときも、ブラウザがあれば `restore` し、ロックを外す。ロックが取れなければ「ほかの操作を実行中」
- [ ] `Viewer` は `pointer` 引数を受け取り（省略時は自分で作る）、`perform_click` と `recapture_current` は `Pointer` のロックを使う
- [ ] ページからのクリックの呼び出し順（find_window → cursor_pos → bring_to_front → window_origin → click → set_cursor → restore）が変わらない
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync pytest -q` → 全件 PASS（`tests/test_pointer.py` 10 件を含む）

**Steps:**

- [ ] **Step 1: `FakeControl` を `tests/fakes.py` に移す**

`tests/test_viewer.py` の `BROWSER = 777` と `class FakeControl:`（17〜80 行、`restore` まで）を切り取り、`tests/fakes.py` に置く。先頭に次を付ける。

```python
"""Test doubles shared by several test modules (tests/ is on sys.path under pytest's default import mode)."""

import time

from ai_desktop.imaging import CaptureError
```

`tests/test_viewer.py` の import に次を加え、移した定義は消す（`import time` は他で使っていればそのまま残す）。

```python
from fakes import BROWSER, FakeControl
```

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS（移しただけなので変わらない）

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_pointer.py`:

```python
import pytest
from fakes import BROWSER, FakeControl

from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta
from ai_desktop.pointer import Pointer, Spot

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
def pointer(store, control):
    return Pointer(store, control, settle_seconds=0)


def test_window_target_is_brought_to_front_and_followed(pointer, control):
    with pointer.at("c2", 10, 20, keep_clear="point") as spot:
        assert spot == Spot(screen=(110, 220), cursor=(5, 6))
    assert control.calls == [
        ("find_window", "ai-desktop | "),
        ("cursor_pos",),
        ("bring_to_front", 42),
        ("window_origin", 42),
        ("restore", BROWSER),
    ]


def test_point_mode_minimizes_only_when_the_point_is_under_the_browser(pointer, control):
    control.browser_rect = (3000, 0, 3840, 1000)  # overlaps the capture, not the point (100, 200)
    with pointer.at("c1", 49, 98, keep_clear="point") as spot:
        assert spot.screen == (100, 200)
    assert not any(call[0] == "minimize" for call in control.calls)


def test_capture_mode_minimizes_when_the_browser_overlaps_the_capture(pointer, control):
    control.browser_rect = (3000, 0, 3840, 1000)
    with pointer.at("c1", 49, 98, keep_clear="capture"):
        assert ("minimize", BROWSER) in control.calls
    assert control.calls[-1] == ("restore", BROWSER)


def test_capture_mode_leaves_a_browser_beside_the_capture(pointer, control):
    control.browser_rect = (3840, 0, 7680, 2160)
    with pointer.at("c1", 49, 98, keep_clear="capture"):
        pass
    assert not any(call[0] == "minimize" for call in control.calls)


def test_browser_that_will_not_minimize_stops_the_operation(pointer, control):
    control.minimize_ok = False
    with pytest.raises(CaptureError, match="最小化できなかった"):
        with pointer.at("c1", 49, 98, keep_clear="capture"):
            pytest.fail("the body must not run")
    assert control.calls[-1] == ("restore", BROWSER)


def test_target_that_will_not_come_to_front_stops_the_operation(pointer, control):
    control.front_ok = False
    with pytest.raises(CaptureError, match="前面に出せませんでした"):
        with pointer.at("c2", 10, 20, keep_clear="point"):
            pytest.fail("the body must not run")
    assert control.calls[-1] == ("restore", BROWSER)


def test_point_outside_the_image_is_rejected_before_anything(pointer, control):
    with pytest.raises(CaptureError, match="画像の外"):
        with pointer.at("c2", 800, 10, keep_clear="point"):
            pass
    assert control.calls == []


def test_the_viewer_browser_itself_is_rejected(pointer, control):
    control.browser = 42
    with pytest.raises(CaptureError, match="同じウィンドウ"):
        with pointer.at("c2", 10, 20, keep_clear="point"):
            pass
    assert not any(call[0] in ("bring_to_front", "minimize") for call in control.calls)


def test_errors_in_the_body_still_restore_and_unlock(pointer, control):
    with pytest.raises(RuntimeError):
        with pointer.at("c2", 10, 20, keep_clear="point"):
            raise RuntimeError("boom")
    assert control.calls[-1] == ("restore", BROWSER)
    assert pointer.lock.acquire(blocking=False)
    pointer.lock.release()


def test_only_one_operation_at_a_time(pointer):
    pointer.lock.acquire()
    try:
        with pytest.raises(CaptureError, match="ほかの操作を実行中"):
            with pointer.at("c2", 10, 20, keep_clear="point"):
                pass
    finally:
        pointer.lock.release()
```

- [ ] **Step 3: テストが失敗することを確かめる**

Run: `uv run --no-sync pytest tests/test_pointer.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'ai_desktop.pointer'`）

- [ ] **Step 4: `src/ai_desktop/pointer.py` を作る**

```python
"""Prepares and cleans up an operation at one point of a capture (a click, a cursor move)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from ai_desktop.annotate import VIEWER_TITLE_PREFIX
from ai_desktop.captures import CaptureStore
from ai_desktop.imaging import CaptureError, image_to_screen

SETTLE_SECONDS = 0.15  # after minimizing the browser, before the operation


@dataclass(frozen=True)
class Spot:
    screen: tuple[int, int]  # the point, in physical screen pixels
    cursor: tuple[int, int]  # where the cursor was before; the caller decides whether to put it back


class Pointer:
    """Runs one operation at a time at a point of a capture.

    control is the ai_desktop.control module in production; tests pass a fake with the same
    functions (find_window, cursor_pos, bring_to_front, window_origin, window_rect, minimize,
    is_minimized, restore). lock is shared with the viewer's re-capture."""

    def __init__(self, store: CaptureStore, control: Any, settle_seconds: float = SETTLE_SECONDS) -> None:
        self._store = store
        self._control = control
        self._settle_seconds = settle_seconds
        self.lock = threading.Lock()

    @contextmanager
    def at(
        self, capture_id: str, x: float, y: float, keep_clear: Literal["point", "capture"]
    ) -> Iterator[Spot]:
        """Get ready to operate at (x, y) of the capture and yield where that is on screen.

        keep_clear="point" minimizes a browser covering the point; "capture" minimizes one
        overlapping the captured area. The browser always comes back afterwards; the cursor
        is left to the caller."""
        if not self.lock.acquire(blocking=False):
            raise CaptureError("ほかの操作を実行中です。終わるまで待ってください。")
        try:
            _, meta = self._store.get(capture_id)
            target = self._store.target(capture_id)
            if not (0 <= x < meta["imageWidth"] and 0 <= y < meta["imageHeight"]):
                raise CaptureError("位置が画像の外です。")
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
                        raise CaptureError("対象のウィンドウを前面に出せませんでした。もう一度試してください。")
                    origin = self._control.window_origin(target.id)
                screen = image_to_screen(meta, x, y, origin)
                if browser is not None and target.kind == "monitor" and self._in_the_way(browser, screen, meta, keep_clear):
                    self._control.minimize(browser)
                    time.sleep(self._settle_seconds)
                    if not self._control.is_minimized(browser):
                        raise CaptureError("ブラウザを最小化できなかったため、操作しませんでした。")
                yield Spot(screen=screen, cursor=cursor)
            finally:
                if browser is not None:
                    self._control.restore(browser)
        finally:
            self.lock.release()

    def _in_the_way(self, browser: Any, screen: tuple[int, int], meta: dict, keep_clear: str) -> bool:
        left, top, right, bottom = self._control.window_rect(browser)
        if keep_clear == "point":
            screen_x, screen_y = screen
            return left <= screen_x < right and top <= screen_y < bottom
        m_left, m_top = meta["originX"], meta["originY"]
        m_right, m_bottom = m_left + meta["originalWidth"], m_top + meta["originalHeight"]
        return left < m_right and m_left < right and top < m_bottom and m_top < bottom
```

Run: `uv run --no-sync pytest tests/test_pointer.py -q`
Expected: PASS（10 件）

- [ ] **Step 5: `Viewer` を `Pointer` に切り替える**

`src/ai_desktop/viewer.py`:

1. import を直す。`image_to_screen` を外し、`Pointer` を加える。

```python
from ai_desktop.imaging import CaptureError
from ai_desktop.pointer import Pointer
```

2. `__init__` に `pointer` 引数を加え、`self._operating = threading.Lock()` を消して次に置き換える。

```python
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
```

```python
        self._pointer = pointer if pointer is not None else Pointer(store, control, settle_seconds)
```

3. `recapture_current` の `with self._operating:` を `with self._pointer.lock:` にする。

4. `perform_click` を丸ごと次に置き換える。

```python
    def perform_click(self, capture_id: str, x: float, y: float, double: bool) -> None:
        """Click the real screen where (x, y) is on the capture. The page is left as it is."""
        with self._pointer.at(capture_id, x, y, keep_clear="point") as spot:
            try:
                self._control.click(*spot.screen, double)
                time.sleep(self._after_click_seconds)
            finally:
                self._control.set_cursor(*spot.cursor)
```

5. クラスの docstring の control の関数一覧はそのまま（`Pointer` に渡すものも含むため）。

確認: `grep -n "_operating\|image_to_screen" src/ai_desktop/viewer.py` が何も出さない。

- [ ] **Step 6: `tests/test_viewer.py` の期待値を直す**

カーソルは動く前に失敗したら戻す必要がないので、`set_cursor` は呼ばれなくなる。次の 4 件の最後の行を直す。

```python
def test_click_is_skipped_when_the_browser_cannot_be_minimized(viewer, control):
    control.minimize_ok = False
    with pytest.raises(CaptureError, match="最小化できなかった"):
        viewer.perform_click("c1", 49, 98, False)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)
    assert control.calls[-1] == ("restore", BROWSER)


def test_failed_browser_rect_still_restores(viewer, control):
    control.fail_rect = True
    with pytest.raises(CaptureError, match="位置を取得できませんでした"):
        viewer.perform_click("c1", 49, 98, False)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)
    assert control.calls[-1] == ("restore", BROWSER)


def test_failed_click_still_restores_cursor_and_browser(viewer, control):
    control.fail_origin = True
    with pytest.raises(CaptureError, match="操作対象のウィンドウが見つかりません"):
        viewer.perform_click("c2", 10, 20, False)
    assert control.calls[-1] == ("restore", BROWSER)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)


def test_click_is_skipped_when_the_target_cannot_be_brought_to_front(viewer, control):
    control.front_ok = False
    with pytest.raises(CaptureError, match="前面に出せませんでした"):
        viewer.perform_click("c2", 10, 20, False)
    assert not any(call[0] in ("click", "set_cursor") for call in control.calls)
    assert control.calls[-1] == ("restore", BROWSER)
```

`test_only_one_operation_at_a_time` の `viewer._operating` を `viewer._pointer.lock` にする（2 か所）。

加えて、クリックの失敗でもカーソルが戻ることを確かめるテストを 1 件足す。

```python
def test_click_that_fails_after_moving_restores_the_cursor(viewer, control, monkeypatch):
    def broken_click(x, y, double):
        control.calls.append(("click", x, y, double))
        raise CaptureError("入力を送れませんでした（Win32 エラー 5）。")

    monkeypatch.setattr(control, "click", broken_click)
    with pytest.raises(CaptureError, match="入力を送れませんでした"):
        viewer.perform_click("c2", 10, 20, False)
    assert control.calls[-2:] == [("set_cursor", 5, 6), ("restore", BROWSER)]
```

- [ ] **Step 7: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 8: コミット**

```bash
git add src/ai_desktop/pointer.py src/ai_desktop/viewer.py tests/fakes.py tests/test_pointer.py tests/test_viewer.py
git commit -m "refactor: share the point-operation setup and lock through pointer.py"
```

---

### Task 3: move_mouse ツールを加える

**Goal:** MCP ツール `move_mouse` を加え、撮影画像の 1 点へカーソルを動かして待ち、同じ対象を撮り直して返す（クリックはしない）。

**Files:**
- Modify: `src/ai_desktop/server.py`
- Test: `tests/test_server.py`

**Acceptance Criteria:**
- [ ] ツールが 7 つ（既存 6 つ＋`move_mouse`）
- [ ] `move_mouse` は `Pointer.at(..., keep_clear="capture")` の中で `inputs.move` → 待ち → 同じ対象の撮り直しを行い、`restore_cursor=True`（既定）なら最後に `inputs.move` で元の位置へ戻す
- [ ] 戻り値は JPEG と JSON メタデータ。メタデータに新しい `captureId`、`"hover": {"x", "y", "captureId": 元の id}`、`"cursorRestored"` がある
- [ ] `wait_seconds` は 0〜5 に丸める（既定 0.5）
- [ ] 範囲外の点はエラーで、カーソルを動かさない
- [ ] 撮り直しに失敗してもカーソルを戻してからエラーを返す
- [ ] クリック（`inputs.click`、`control.click`）を一度も呼ばない
- [ ] INSTRUCTIONS が 1 段落のまま `move_mouse` に触れる
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync pytest -q` → 全件 PASS（`tests/test_server.py` の新規 7 件を含む）

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_server.py`:

1. `test_exposes_six_tools` を次に置き換える。

```python
def test_exposes_seven_tools():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(run()).tools}
    assert names == {
        "list_monitors", "list_windows", "capture_monitor", "capture_window", "show_annotated",
        "wait_for_message", "move_mouse",
    }
```

2. `test_instructions_are_one_paragraph` に 1 行加える。

```python
    assert "move_mouse" in server.INSTRUCTIONS
```

3. import に次を加える。

```python
from fakes import BROWSER, FakeControl

from ai_desktop import inputs
from ai_desktop.pointer import Pointer
```

4. ファイルの末尾に次を加える。

```python
class Mouse:
    """What move_mouse did: control calls, cursor moves and sleeps."""

    def __init__(self, control):
        self.control = control
        self.moves = []
        self.sleeps = []


@pytest.fixture
def mouse(monkeypatch):
    mouse = Mouse(FakeControl())
    monkeypatch.setattr(server, "pointer", Pointer(server.captures, mouse.control, settle_seconds=0))
    monkeypatch.setattr(inputs, "move", lambda x, y: mouse.moves.append((x, y)))
    monkeypatch.setattr(inputs, "click", lambda *args, **kwargs: pytest.fail("move_mouse must not click"))
    monkeypatch.setattr(server, "_sleep", mouse.sleeps.append)
    return mouse


def test_move_mouse_moves_waits_recaptures_and_puts_the_cursor_back(mouse):
    call("capture_window", {"title": "excel"})  # c1; FakeControl puts the window at (100, 200)
    result = call("move_mouse", {"capture_id": "c1", "x": 10, "y": 20})
    assert not result.is_error
    assert result.content[0].type == "image"
    meta = json.loads(result.content[1].text)
    assert meta["captureId"] == "c2"
    assert meta["hover"] == {"x": 10, "y": 20, "captureId": "c1"}
    assert meta["cursorRestored"] is True
    assert mouse.moves == [(110, 220), (5, 6)]
    assert mouse.sleeps == [0.5]
    assert ("bring_to_front", 42) in mouse.control.calls
    assert not any(call[0] == "click" for call in mouse.control.calls)


def test_move_mouse_can_leave_the_cursor_where_it_moved(mouse):
    call("capture_window", {"title": "excel"})
    result = call("move_mouse", {"capture_id": "c1", "x": 10, "y": 20, "restore_cursor": False})
    assert json.loads(result.content[1].text)["cursorRestored"] is False
    assert mouse.moves == [(110, 220)]


@pytest.mark.parametrize(("wait", "expected"), [(9, 5.0), (-1, 0.0), (1.25, 1.25)])
def test_move_mouse_clamps_the_wait(mouse, wait, expected):
    call("capture_window", {"title": "excel"})
    call("move_mouse", {"capture_id": "c1", "x": 10, "y": 20, "wait_seconds": wait})
    assert mouse.sleeps == [expected]


def test_move_mouse_outside_the_image_does_not_move(mouse):
    call("capture_window", {"title": "excel"})
    result = call("move_mouse", {"capture_id": "c1", "x": 800, "y": 20})
    assert result.is_error
    assert "画像の外" in result.content[0].text
    assert mouse.moves == []


def test_move_mouse_puts_the_cursor_back_when_the_recapture_fails(mouse, monkeypatch):
    call("capture_window", {"title": "excel"})

    def gone(hwnd):
        raise CaptureError("window_id 42 のウィンドウは存在しません。")

    monkeypatch.setattr(capture, "capture_window", gone)
    result = call("move_mouse", {"capture_id": "c1", "x": 10, "y": 20})
    assert result.is_error
    assert "存在しません" in result.content[0].text
    assert mouse.moves == [(110, 220), (5, 6)]
    assert mouse.control.calls[-1] == ("restore", BROWSER)


def test_move_mouse_on_a_monitor_clears_the_browser_first(mouse):
    call("capture_monitor")  # c1: 3200x1600 shown at 0.49
    result = call("move_mouse", {"capture_id": "c1", "x": 49, "y": 98})
    assert not result.is_error
    assert mouse.moves[0] == (100, 200)
    assert ("minimize", BROWSER) in mouse.control.calls
    assert mouse.control.calls[-1] == ("restore", BROWSER)


def test_move_mouse_unknown_capture_is_reported(mouse):
    result = call("move_mouse", {"capture_id": "c9", "x": 1, "y": 1})
    assert result.is_error
    assert mouse.moves == []
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --no-sync pytest tests/test_server.py -q`
Expected: FAIL（ツールの数と `server._sleep` がないことによる失敗）

- [ ] **Step 3: `server.py` に `move_mouse` を加える**

1. import と定数。

```python
import time
```

```python
from ai_desktop import capture, control, inputs
from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta, encode_jpeg, select_window, shrink
from ai_desktop.pointer import Pointer
from ai_desktop.viewer import Viewer
```

```python
MOVE_WAIT_DEFAULT_SECONDS = 0.5
MOVE_WAIT_MAX_SECONDS = 5.0
_sleep = time.sleep  # replaced in tests
```

2. `viewer = Viewer(captures, control)` を次に置き換える。

```python
pointer = Pointer(captures, control)
viewer = Viewer(captures, control, pointer=pointer)
```

3. `wait_for_message` の後ろ（`def main` の前）にツールを加える。

```python
@mcp.tool()
def move_mouse(
    capture_id: str,
    x: float,
    y: float,
    wait_seconds: float = MOVE_WAIT_DEFAULT_SECONDS,
    restore_cursor: bool = True,
) -> list[Image | str]:
    """Rest the mouse cursor on a point of one of your captures, wait, and capture the same
    window or monitor again, to read what only appears while the cursor is on something
    (tooltips, hover text, descriptions of icons). It never clicks. It moves the user's real
    cursor for a moment, so use it when the user is not using the mouse.

    capture_id: the captureId from a capture's metadata (the latest 10 are kept).
    x, y: the point in that capture's image pixels (imageWidth x imageHeight).
    wait_seconds: how long the cursor rests before the capture (0-5, default 0.5).
    restore_cursor: put the cursor back where it was afterwards (default true).
    Returns a JPEG and JSON metadata like the capture tools, with a new captureId, plus
    "hover" (the point and the captureId it was on) and "cursorRestored". A window capture
    shows only that window, so a tooltip drawn as a separate popup appears only in a
    monitor capture."""
    wait = max(0.0, min(MOVE_WAIT_MAX_SECONDS, float(wait_seconds)))
    with _reported():
        target = captures.target(capture_id)
        with pointer.at(capture_id, x, y, keep_clear="capture") as spot:
            try:
                inputs.move(*spot.screen)
                _sleep(wait)
                shrunk, meta = _recapture(target)
            finally:
                if restore_cursor:
                    inputs.move(*spot.cursor)
    result = {**meta, "hover": {"x": x, "y": y, "captureId": capture_id}, "cursorRestored": restore_cursor}
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(result, ensure_ascii=False)]
```

4. INSTRUCTIONS の 1 文目（`... capture it instead of asking them to describe it.`）の直後に、次の 1 文を加える（改行は `\` で続け、段落を分けない）。

```python
To read something that only appears while the cursor rests on it (a tooltip, hover text, \
the description of an icon), call move_mouse with a capture's captureId and a point on that \
image: it moves the user's real cursor there, waits, captures the same target again and puts \
the cursor back, and it never clicks, so use it when the user is not using the mouse. \
```

- [ ] **Step 4: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/server.py tests/test_server.py
git commit -m "feat: add the move_mouse tool to rest the cursor on a point and recapture"
```

---

### Task 4: 試験用ウィンドウと実機の通し確認

**Goal:** 試験用ウィンドウがカーソルの出入りに反応するようにし、実際の MCP サーバー経由で `move_mouse` を確かめるスクリプトを加える。

**Files:**
- Modify: `scripts/click_target.py`
- Create: `scripts/e2e_move_mouse.py`

**Acceptance Criteria:**
- [ ] `click_target.py` は、カーソルが乗ると背景を黄色（`#ffe066`）にし、離れると元の色（`#f4f4f4`）に戻す。出入りの回数を `{"single", "double", "enter", "leave"}` の JSON で出力する
- [ ] `click_target.py` は、省略可能な第 1 引数で位置（tkinter の geometry 文字列）を受け取る。省略時は今と同じ `520x320+240+240`
- [ ] `e2e_move_mouse.py` は、プライマリモニター上の試験用ウィンドウに `capture_window` → `move_mouse` を呼び、返った画像の中央が黄色であること、`enter` と `leave` が 1 以上であること、カーソルが元の位置に戻ったことを確かめ、`OK` を表示する
- [ ] モニターが 2 枚以上なら、プライマリ以外のモニターに試験用ウィンドウを開き、`capture_monitor` → `move_mouse` で同じことを確かめる
- [ ] 既存の `scripts/e2e_viewer.py` と `scripts/control_smoke.py` が `click_target.py` の出力の変更で壊れない（`get` で読んでいる）
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `uv run --no-sync python scripts/e2e_move_mouse.py` → 最後に `OK` を表示（実機。ユーザーがマウスを触らない状態で実行）

**Steps:**

- [ ] **Step 1: `scripts/click_target.py` を置き換える**

```python
"""A harmless window for manual and end-to-end tests: counts clicks, double-clicks and hovers.

Turns yellow while the cursor is on it. Every change is also printed to stdout as one JSON
line, so test scripts can read it. An optional first argument sets the tkinter geometry."""

import json
import sys
import tkinter as tk

TITLE = "ai-desktop クリック試験"
DEFAULT_GEOMETRY = "520x320+240+240"
IDLE_COLOR = "#f4f4f4"
HOVER_COLOR = "#ffe066"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    counts = {"single": 0, "double": 0, "enter": 0, "leave": 0}
    root = tk.Tk()
    root.title(TITLE)
    root.geometry(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GEOMETRY)
    label = tk.Label(root, font=("Yu Gothic UI", 20), bg=IDLE_COLOR)
    label.pack(expand=True, fill="both")

    def show() -> None:
        label.config(
            text=f"クリック: {counts['single']}\nダブルクリック: {counts['double']}\n"
            f"ホバー: {counts['enter']} / {counts['leave']}"
        )
        print(json.dumps(counts), flush=True)

    def count(name: str, color: str | None = None):
        def handler(_event: tk.Event) -> None:
            counts[name] += 1
            if color is not None:
                label.config(bg=color)
            show()

        return handler

    label.bind("<Button-1>", count("single"))
    label.bind("<Double-Button-1>", count("double"))
    label.bind("<Enter>", count("enter", HOVER_COLOR))
    label.bind("<Leave>", count("leave", IDLE_COLOR))
    show()
    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: `scripts/e2e_move_mouse.py` を作る**

```python
"""Real-machine end-to-end check of move_mouse, run against the real MCP server over stdio.

1. On the primary monitor: capture_window the test window, rest the cursor on its middle,
   and check the returned image shows the hover color, the window saw the cursor come and
   go, and the cursor is back where it was.
2. With two or more monitors: the same on a non-primary monitor with capture_monitor.

Opens a small test window (closed at the end). Do not touch the mouse while it runs."""

import asyncio
import base64
import io
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from mcp import Client, StdioServerParameters
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from click_target import HOVER_COLOR, TITLE  # noqa: E402

from ai_desktop import capture, control  # noqa: E402


def start_target(geometry: str) -> tuple[subprocess.Popen, queue.Queue]:
    app = subprocess.Popen(
        [sys.executable, str(HERE / "click_target.py"), geometry],
        stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(json.loads(line)) for line in app.stdout], daemon=True).start()
    return app, lines


def latest(lines: queue.Queue, wait: float) -> dict:
    deadline, state = time.monotonic() + wait, {}
    while time.monotonic() < deadline:
        try:
            state = lines.get(timeout=0.1)
        except queue.Empty:
            pass
    return state


def target_window():
    return next((w for w in capture.list_windows() if w.title == TITLE), None)


def is_hover_color(rgb: tuple[int, int, int]) -> bool:
    expected = tuple(int(HOVER_COLOR[i : i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= 24 for a, b in zip(rgb, expected))  # JPEG drifts a little


async def check(client: Client, lines: queue.Queue, tool: str, arguments: dict, point_of) -> None:
    window = target_window()
    assert window is not None, "test window not found"
    away = (window.x - 40, window.y - 40)  # just outside the window, so the hover must start and end
    control.set_cursor(*away)
    latest(lines, 0.5)

    shot = await client.call_tool(tool, arguments)
    meta = json.loads(shot.content[1].text)
    x, y = point_of(meta, window)
    result = await client.call_tool("move_mouse", {"capture_id": meta["captureId"], "x": x, "y": y})
    assert not result.is_error, result.content[0].text
    hover_meta = json.loads(result.content[1].text)
    image = Image.open(io.BytesIO(base64.b64decode(result.content[0].data))).convert("RGB")
    pixel = image.getpixel((round(x), round(y)))
    state = latest(lines, 1.0)
    print(tool, "->", hover_meta["captureId"], "pixel", pixel, "state", state, "cursor", control.cursor_pos())
    assert is_hover_color(pixel), f"the capture does not show the hover color: {pixel}"
    assert state.get("enter", 0) >= 1 and state.get("leave", 0) >= 1, state
    assert control.cursor_pos() == away, (control.cursor_pos(), away)
    assert hover_meta["cursorRestored"] is True


def window_middle(meta: dict, window) -> tuple[float, float]:
    return meta["imageWidth"] / 2, meta["imageHeight"] / 2


def window_middle_on_monitor(meta: dict, window) -> tuple[float, float]:
    scale = meta["scale"]
    return (
        (window.x - meta["originX"] + window.width / 2) * scale,
        (window.y - meta["originY"] + window.height / 2) * scale,
    )


async def run_on(geometry: str, tool: str, arguments: dict, point_of) -> None:
    app, lines = start_target(geometry)
    try:
        time.sleep(1.5)  # let the window appear
        params = StdioServerParameters(command="uv", args=["run", "--no-sync", "ai-desktop"], cwd=str(HERE.parent))
        async with Client(params) as client:
            await check(client, lines, tool, arguments, point_of)
    finally:
        app.terminate()


async def main() -> None:
    capture.enable_dpi_awareness()
    await run_on("520x320+240+240", "capture_window", {"title": TITLE}, window_middle)
    others = [m for m in capture.list_monitors() if not m.primary]
    if others:
        monitor = others[0]
        geometry = f"520x320+{monitor.x + 200}+{monitor.y + 200}"
        print("secondary monitor:", monitor.id, monitor.name, (monitor.x, monitor.y))
        await run_on(geometry, "capture_monitor", {"monitor_id": monitor.id}, window_middle_on_monitor)
    else:
        print("only one monitor: skipped the secondary-monitor check")
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
```

注: tkinter の geometry はプロセスの DPI 設定により論理ピクセルで解釈されることがある。サブモニターでウィンドウが期待の位置に出ない場合でも、`window_middle_on_monitor` は `list_windows` の実際の位置（物理ピクセル）から点を求めるので、ウィンドウがそのモニター内にあれば確認は成り立つ。モニター外に出た場合は `test window not found` ではなく `capture_monitor` の画像外エラーになるので、その旨を報告する。

- [ ] **Step 3: 既存スクリプトが出力の変更で壊れないことを確かめる**

Run: `grep -n "latest(\|state\[" scripts/e2e_viewer.py scripts/control_smoke.py`
Expected: 出力の dict を `get` で読んでいるか、表示しているだけ（キーの追加で壊れる比較がない）

- [ ] **Step 4: 単体テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 5: 実機で確かめる（マウスに触らない）**

Run: `uv run --no-sync python scripts/e2e_move_mouse.py`
Expected: `capture_window -> c2 pixel (255, 224, 102) ...` のような行のあと、最後に `OK`。サブモニターがなければ `only one monitor: skipped ...` のあとに `OK`

失敗した場合は、出力（pixel、state、cursor）をそのまま報告する。`wait_seconds` が足りないと pixel が元の色（244, 244, 244 付近）になる。

- [ ] **Step 6: コミット**

```bash
git add scripts/click_target.py scripts/e2e_move_mouse.py
git commit -m "test: add a hover-aware test window and an end-to-end move_mouse check"
```

---

### Task 5: ドキュメントとスキルを更新する

**Goal:** README、ai-desktop-guide スキル、Slay the Spire 2 のノート、仕様書に `move_mouse` の使い方と制限を書く。

**Files:**
- Modify: `README.md`
- Modify: `.claude/skills/ai-desktop-guide/SKILL.md`
- Modify: `docs/games/slay-the-spire2/README.md`
- Modify: `docs/superpowers/specs/2026-10-05-move-mouse-design.md`（§10 に既知の制限を 1 項目）

**Acceptance Criteria:**
- [ ] README のツール表に `move_mouse` の行がある。既知の制限に「ウィンドウ撮影には別ウィンドウのツールチップが写らない」「ユーザーのマウスを一時的に動かす」がある。実機の動作確認に `scripts/e2e_move_mouse.py` がある
- [ ] SKILL.md のツール数が 7 つで、`move_mouse` を使って説明文を読む節がある（ウィンドウ撮影とモニター撮影の使い分けを含む）
- [ ] `docs/games/slay-the-spire2/README.md` の §6 に「状態アイコンや敵の意図は `move_mouse` で説明文を読む」がある
- [ ] 仕様書 §10 に、ウィンドウ撮影と別ウィンドウのツールチップの制限が書かれている
- [ ] `uv run --no-sync pytest -q` が全件 PASS

**Verify:** `grep -c "move_mouse" README.md .claude/skills/ai-desktop-guide/SKILL.md docs/games/slay-the-spire2/README.md` → 各ファイル 1 以上

**Steps:**

- [ ] **Step 1: README.md**

ツール表の `wait_for_message` の行の下に加える。

```markdown
| `move_mouse` | 撮影画像の 1 点にマウスカーソルを乗せ、`wait_seconds`（0〜5 秒、既定 0.5）待ってから同じウィンドウまたはモニターを撮り直す。ツールチップや説明文など、カーソルを乗せたときだけ出る表示を読むためのもの。クリックはしない。既定でカーソルを元の位置に戻す（`restore_cursor`） |
```

既知の制限の最後に加える。

```markdown
- `move_mouse` はユーザーのマウスカーソルを一時的に動かします（既定で元の位置に戻します）。操作中に使うと、操作とぶつかります。
- ウィンドウ撮影（`capture_window`）には、そのウィンドウの外に別ウィンドウとして出るツールチップは写りません。一般的な Windows アプリのツールチップを読むときは、モニター撮影（`capture_monitor`）の画像に対して `move_mouse` を使ってください（ゲームのように画面の中に描かれる説明文は、ウィンドウ撮影でも写ります）。
```

実機の動作確認のコードブロックに 1 行加える。

```powershell
uv run python scripts/e2e_move_mouse.py  # move_mouse の確認（試験用ウィンドウが開きます。実行中はマウスに触らない）
```

- [ ] **Step 2: SKILL.md**

1. 冒頭の一覧を次にする。

```markdown
ツールは `mcp__ai-desktop__` で始まる 7 つ: `list_monitors`、`list_windows`、`capture_monitor`、`capture_window`、`show_annotated`、`wait_for_message`、`move_mouse`。
```

2. frontmatter の `description` の末尾（`含む。` の前）に「、move_mouse でカーソルを乗せて説明文を読む手順」を加える。

3. 「## 3.」節の後ろに次の節を加える。

```markdown
## 4. カーソルを乗せて説明文を読む

アイコンの意味、ボタンのツールチップ、ゲームの状態や敵の意図など、カーソルを乗せたときだけ出る表示は `move_mouse(capture_id, x, y, wait_seconds=0.5, restore_cursor=True)` で読む。

1. 撮影する。対象アプリの説明文が**画面の中に描かれる**（ゲームなど）なら `capture_window`、**別ウィンドウのツールチップ**（一般的な Windows アプリ）なら `capture_monitor` の画像を使う。ウィンドウ撮影には別ウィンドウのツールチップが写らない。
2. 知りたいものの位置（その画像のピクセル座標）を指定して `move_mouse` を呼ぶ。返る画像（新しい `captureId`）に説明文が写る。
3. 写っていなければ、`wait_seconds` を 1〜2 に延ばして撮り直す。それでも出なければ、その場所には説明文がないか、アプリがその入力に反応しないと伝える。
4. 読めた内容は、推測と区別してチャットに書く。

注意:
- ユーザーのマウスを一瞬動かす（既定で元の位置に戻す）。ユーザーが操作している最中は使わない。ボタンでのやりとり中なら、ボタンが押された直後（ユーザーが待っている間）に使う。
- クリックはしない。押す操作が必要なら、注釈ページでユーザーに押してもらう。
- 1 回 1 点。調べたい場所が多いときは、大事なものから順に呼ぶ（1 回ごとに画像が 1 枚増える）。
```

- [ ] **Step 3: docs/games/slay-the-spire2/README.md**

§6 の最初の箇条（「アニメーション中は撮り直す」）の前に加える。

```markdown
- **状態アイコン、敵の意図、レリック、見切れた手札の説明文は `move_mouse` で読む。** ゲームの説明文は画面の中に描かれるので、`capture_window` の画像の座標を渡せばよい。読めた内容は、このノートの敵ごとのメモやキャラ別ノートに追記する。
```

- [ ] **Step 4: 仕様書 §10 に加える**

```markdown
- 既知の制限: ウィンドウ撮影（PrintWindow）は、別ウィンドウとして出るツールチップを写さない。一般的な Windows アプリではモニター撮影の画像に対して `move_mouse` を使う（README とスキルに記載）。必要になれば、`move_mouse` にウィンドウ対象でもモニター範囲で撮る選択肢を足す
```

- [ ] **Step 5: 確認とコミット**

Run: `grep -c "move_mouse" README.md .claude/skills/ai-desktop-guide/SKILL.md docs/games/slay-the-spire2/README.md` → 各ファイル 1 以上
Run: `uv run --no-sync pytest -q` → 全件 PASS

```bash
git add README.md .claude/skills/ai-desktop-guide/SKILL.md docs/games/slay-the-spire2/README.md docs/superpowers/specs/2026-10-05-move-mouse-design.md
git commit -m "docs: document move_mouse in the README, the guide skill and the game notes"
```

---

## 自己点検の結果

- 仕様の網羅: §4.1 → Task 1、§4.2・§4.3 → Task 1〜2、§5・§6 → Task 3、§7 → Task 1〜4、§8 → Task 3（INSTRUCTIONS）と Task 5、§9 の順番どおり
- 仕様からの変更点: 範囲外のエラー文言を「位置が画像の外です。」に統一（クリックも同じ文言になる）。前面化失敗の文言を「もう一度試してください」に統一（クリック専用の言い回しをやめる）。ウィンドウ撮影と別ウィンドウのツールチップの制限を Task 5 で仕様書に追記
- 型の一貫性: `Pointer(store, control, settle_seconds)`、`Pointer.at(capture_id, x, y, keep_clear)`、`Spot(screen, cursor)`、`Pointer.lock`、`server.pointer`、`server._sleep`、`inputs.move/click/tap_alt` を全タスクで同じ名前で使う
