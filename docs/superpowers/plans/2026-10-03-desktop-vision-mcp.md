# ai-desktop デスクトップ撮影 MCP サーバー Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VS Code の Claude Code から、ユーザーの Windows デスクトップ（モニター全体・特定ウィンドウ）を AI が自分で撮影して見られる MCP サーバーを作る。

**Architecture:** Python 製の stdio MCP サーバーで、ツールは4つ。処理は3つのモジュールに分ける。`imaging.py` は Windows に依存しない純粋な処理（縮小・JPEG 化・座標メタデータ・ウィンドウ選択）、`capture.py` は Win32 に触れる処理（DPI 設定・列挙・mss と PrintWindow による撮影）、`server.py` は MCP の配線とエラー変換だけを担う。

**Tech Stack:** Python 3.12 / uv / mcp 2.x（`MCPServer`）/ mss / pywin32 / Pillow / pytest

**Global Constraints:**
- Windows 専用。Win32 に触れるコードは `src/ai_desktop/capture.py` にだけ置く。
- MCP SDK は `mcp>=2.3,<3`。サーバーは `from mcp.server.mcpserver import MCPServer, Image` を使う。`mcp.server.fastmcp` は 2.x では存在しない。
- ツールのエラーは必ず `mcp.server.mcpserver.exceptions.ToolError` で送出する。他の例外ではメッセージが隠される（mcp 2.3.0 で確認済み）。
- 文字列を返すツールは `@mcp.tool(structured_output=False)`、画像を返すツールは戻り値の型注釈を `list[Image | str]` にする。
- 標準出力は MCP 専用。ログは標準エラー出力に出す。
- 座標はすべて物理ピクセル。サーバー起動時、Win32 や mss を呼ぶ前に `enable_dpi_awareness()` を実行する。
- 画像は長辺が 1568px を超える場合だけ縮小し（拡大はしない）、JPEG 品質 85 で返す。
- 座標メタデータのキーは `source, originX, originY, originalWidth, originalHeight, imageWidth, imageHeight, scale` で固定。変換式は「画面座標 = origin + 画像座標 ÷ scale」。
- サーバーはスクショをディスクに保存しない。保存するのは `scripts/smoke.py` だけで、保存先 `smoke-out/` は gitignore 対象。
- ユーザー向けのエラーメッセージは日本語で書く。
- 仕様書: `docs/superpowers/specs/2026-10-03-desktop-vision-mcp-design.md`

**User decisions (already made):**
- 用途は汎用（何でも聞ける）。
- AiGameCompanion は参考にするが、コードはゼロから書く。
- AI との接続は Claude Code 経由（API キーは使わない）。
- 連動方式は MCP サーバー。AI が自分でスクショを撮る。
- 撮影対象はモニター全体と特定ウィンドウ。部分拡大は作らない。
- 言語は Python。将来、pywinauto / PyAutoGUI で操作機能を足すため。
- MVP は撮影のみ。操作ツールは後から追加する。座標メタデータは MVP から返す。

---

## ファイル構成

| パス | 責務 |
|---|---|
| `pyproject.toml` | 依存、エントリポイント `ai-desktop`、pytest 設定 |
| `.python-version` | `3.12` |
| `.gitignore` | `.venv/`、キャッシュ、`smoke-out/` |
| `src/ai_desktop/__init__.py` | パッケージの目印 |
| `src/ai_desktop/imaging.py` | 純粋処理。`CaptureError`、`MonitorInfo`、`WindowInfo`、`fit_size`、`shrink`、`encode_jpeg`、`build_meta`、`image_to_screen`、`select_window` |
| `src/ai_desktop/capture.py` | Win32 処理。`enable_dpi_awareness`、`list_monitors`、`list_windows`、`capture_monitor`、`capture_window` |
| `src/ai_desktop/server.py` | `MCPServer` とツール4つ、`main()` |
| `scripts/smoke.py` | 実機での撮影確認（手動実行） |
| `tests/test_imaging.py` | 縮小・JPEG・メタデータ・座標変換 |
| `tests/test_matching.py` | `select_window` |
| `tests/test_server.py` | capture を偽物に差し替え、インメモリの MCP クライアントで検証 |
| `README.md` | セットアップと登録手順 |

コマンドはすべて `C:\Works\2026\ai-desktop` で実行する（Bash ツールでは `cd /c/Works/2026/ai-desktop`）。

---

### Task 1: プロジェクトの雛形と画像処理

**Goal:** uv プロジェクトを作り、縮小・JPEG 化・座標メタデータ・座標変換の純粋関数をテスト付きで実装する。

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `src/ai_desktop/__init__.py`
- Create: `src/ai_desktop/imaging.py`
- Test: `tests/test_imaging.py`

**Acceptance Criteria:**
- [ ] `uv sync` が成功し、`.venv` に mcp 2.x・mss・pywin32・Pillow・pytest が入る
- [ ] `fit_size` が、横長・縦長・ちょうど上限・上限未満・極端な比率で期待どおりのサイズと縮小率を返す
- [ ] `shrink` が大きい画像を縮小し、小さい画像は同じオブジェクトのまま返す
- [ ] `encode_jpeg` が RGBA 入力でも `FF D8` で始まる JPEG を返す
- [ ] `build_meta` のキーと値が仕様 §5.3 と一致する
- [ ] `image_to_screen` が origin と scale を正しく適用する
- [ ] `uv run pytest tests/test_imaging.py -v` が全件 PASS

**Verify:** `uv run pytest tests/test_imaging.py -v` → `10 passed`

**Steps:**

- [ ] **Step 1: プロジェクトファイルを作る**

`pyproject.toml`:

```toml
[project]
name = "ai-desktop"
version = "0.1.0"
description = "MCP server that lets Claude Code see the Windows desktop"
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.3,<3",
    "mss>=10.2",
    "pillow>=12.0",
    "pywin32>=312; sys_platform == 'win32'",
]

[project.scripts]
ai-desktop = "ai_desktop.server:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_desktop"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.python-version`:

```text
3.12
```

`.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
smoke-out/
```

`src/ai_desktop/__init__.py`:

```python
"""Desktop screenshot MCP server for Claude Code."""
```

- [ ] **Step 2: 依存をインストールする**

Run: `uv sync`
Expected: エラーなく完了し、`uv pip list` に `mcp 2.x`、`mss`、`pillow`、`pywin32`、`pytest` が表示される。

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_imaging.py`:

```python
from PIL import Image

from ai_desktop.imaging import build_meta, encode_jpeg, fit_size, image_to_screen, shrink


def test_fit_size_shrinks_landscape_to_max_edge():
    width, height, scale = fit_size(3840, 2560)
    assert (width, height) == (1568, 1045)
    assert scale == 1568 / 3840


def test_fit_size_shrinks_portrait_to_max_edge():
    width, height, scale = fit_size(1000, 3000)
    assert (width, height) == (523, 1568)
    assert scale == 1568 / 3000


def test_fit_size_keeps_exact_max_edge():
    assert fit_size(1568, 1000) == (1568, 1000, 1.0)


def test_fit_size_never_upscales():
    assert fit_size(800, 600) == (800, 600, 1.0)


def test_fit_size_keeps_at_least_one_pixel():
    width, height, _ = fit_size(10000, 1)
    assert (width, height) == (1568, 1)


def test_shrink_resizes_large_image():
    image, scale = shrink(Image.new("RGB", (3000, 1000)))
    assert image.size == (1568, 523)
    assert scale == 1568 / 3000


def test_shrink_leaves_small_image_untouched():
    original = Image.new("RGB", (800, 600))
    image, scale = shrink(original)
    assert image is original
    assert scale == 1.0


def test_encode_jpeg_accepts_rgba():
    data = encode_jpeg(Image.new("RGBA", (10, 10), (255, 0, 0, 128)))
    assert data[:2] == b"\xff\xd8"


def test_build_meta_matches_spec_keys():
    meta = build_meta("window:42 Book1 - Excel", 120, 80, (1600, 900), (1568, 882), 0.98)
    assert meta == {
        "source": "window:42 Book1 - Excel",
        "originX": 120,
        "originY": 80,
        "originalWidth": 1600,
        "originalHeight": 900,
        "imageWidth": 1568,
        "imageHeight": 882,
        "scale": 0.98,
    }


def test_image_to_screen_applies_origin_and_scale():
    meta = build_meta("monitor:3", -2160, -1255, (2160, 3840), (1080, 1920), 0.5)
    assert image_to_screen(meta, 100, 50) == (-1960, -1155)
    _, _, scale = fit_size(3840, 2560)
    corner = build_meta("monitor:1", 0, 0, (3840, 2560), (1568, 1045), scale)
    assert image_to_screen(corner, 1568, 0) == (3840, 0)
```

- [ ] **Step 4: テストが失敗することを確認する**

Run: `uv run pytest tests/test_imaging.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'ai_desktop.imaging'`）

- [ ] **Step 5: 実装する**

`src/ai_desktop/imaging.py`:

```python
"""Pure image and geometry helpers.

Nothing here touches Win32, so all of it is unit-testable on any machine.
"""

from __future__ import annotations

import io

from PIL import Image

MAX_EDGE = 1568
JPEG_QUALITY = 85


def fit_size(width: int, height: int, max_edge: int = MAX_EDGE) -> tuple[int, int, float]:
    """Size that fits within max_edge on the long side, never upscaling."""
    scale = min(1.0, max_edge / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale)), scale


def shrink(image: Image.Image, max_edge: int = MAX_EDGE) -> tuple[Image.Image, float]:
    """Downscale per fit_size; returns the image unchanged when it already fits."""
    width, height, scale = fit_size(image.width, image.height, max_edge)
    if scale >= 1.0:
        return image, 1.0
    return image.resize((width, height), Image.LANCZOS), scale


def encode_jpeg(image: Image.Image, quality: int = JPEG_QUALITY) -> bytes:
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def build_meta(
    source: str,
    origin_x: int,
    origin_y: int,
    original_size: tuple[int, int],
    image_size: tuple[int, int],
    scale: float,
) -> dict:
    """Coordinate metadata returned next to every capture (spec §5.3)."""
    return {
        "source": source,
        "originX": origin_x,
        "originY": origin_y,
        "originalWidth": original_size[0],
        "originalHeight": original_size[1],
        "imageWidth": image_size[0],
        "imageHeight": image_size[1],
        "scale": scale,
    }


def image_to_screen(meta: dict, x: float, y: float) -> tuple[int, int]:
    """Map a point on the returned image back to physical screen coordinates."""
    return (
        round(meta["originX"] + x / meta["scale"]),
        round(meta["originY"] + y / meta["scale"]),
    )
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest tests/test_imaging.py -v`
Expected: `10 passed`

- [ ] **Step 7: コミットする**

```bash
git add pyproject.toml uv.lock .python-version .gitignore src/ai_desktop/__init__.py src/ai_desktop/imaging.py tests/test_imaging.py
git commit -F - <<'EOF'
feat: scaffold project and add image helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: データ型とウィンドウ選択

**Goal:** `CaptureError`・`MonitorInfo`・`WindowInfo` を定義し、タイトルの部分一致でウィンドウを1つに絞る `select_window` をテスト付きで実装する。

**Files:**
- Modify: `src/ai_desktop/imaging.py`（データ型と `select_window` を追加）
- Test: `tests/test_matching.py`

**Acceptance Criteria:**
- [ ] 該当 0 件で、`list_windows` への案内を含む `CaptureError` を送出する
- [ ] 該当 1 件で、そのウィンドウを返す
- [ ] 複数件のうち完全一致（大文字小文字は区別しない）が1つなら、それを返す
- [ ] 複数件で完全一致がなければ、各候補の `id=` とタイトル、および `window_id` への案内を含む `CaptureError` を送出する
- [ ] 候補が 20 件を超える場合、21 件目以降は「ほか N 件」と要約する
- [ ] 大文字小文字の違いを無視して一致させる
- [ ] `uv run pytest -v` が全件 PASS（Task 1 の分を含む）

**Verify:** `uv run pytest -v` → `16 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_matching.py`:

```python
import pytest

from ai_desktop.imaging import CaptureError, WindowInfo, select_window


def window(id: int, title: str) -> WindowInfo:
    return WindowInfo(
        id=id, title=title, app="app.exe", x=0, y=0, width=800, height=600,
        minimized=False, focused=False,
    )


WINDOWS = [
    window(1, "Book1 - Excel"),
    window(2, "Inbox - Outlook"),
    window(3, "ChatGPT - Google Chrome"),
    window(4, "ChatGPT"),
    window(5, "Claude - Google Chrome"),
]


def test_no_match_raises_with_hint():
    with pytest.raises(CaptureError, match="list_windows"):
        select_window(WINDOWS, "Photoshop")


def test_single_match_is_returned():
    assert select_window(WINDOWS, "excel").id == 1


def test_match_ignores_case():
    assert select_window(WINDOWS, "OUTLOOK").id == 2


def test_exact_title_wins_among_several_matches():
    assert select_window(WINDOWS, "chatgpt").id == 4


def test_ambiguous_match_lists_candidates():
    with pytest.raises(CaptureError) as error:
        select_window(WINDOWS, "Google Chrome")
    message = str(error.value)
    assert "window_id" in message
    assert "id=3" in message
    assert "id=5" in message


def test_candidate_list_is_capped():
    many = [window(i, f"Untitled {i}") for i in range(25)]
    with pytest.raises(CaptureError) as error:
        select_window(many, "Untitled")
    message = str(error.value)
    assert "id=19" in message
    assert "id=20" not in message
    assert "ほか 5 件" in message
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_matching.py -v`
Expected: FAIL（`ImportError: cannot import name 'CaptureError'`）

- [ ] **Step 3: 実装する**

`src/ai_desktop/imaging.py` の `import io` の直後に `from dataclasses import dataclass` を追加し、`JPEG_QUALITY = 85` の下に次を追加する。

```python
MAX_CANDIDATES = 20


class CaptureError(Exception):
    """A capture problem whose message is written for the model to read."""


@dataclass(frozen=True)
class MonitorInfo:
    id: int
    name: str
    primary: bool
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class WindowInfo:
    id: int
    title: str
    app: str
    x: int
    y: int
    width: int
    height: int
    minimized: bool
    focused: bool
```

ファイル末尾に次を追加する。

```python
def select_window(windows: list[WindowInfo], title: str) -> WindowInfo:
    """Pick the one window whose title contains `title`, ignoring case (spec §6.2)."""
    needle = title.casefold()
    matches = [w for w in windows if needle in w.title.casefold()]
    if not matches:
        raise CaptureError(
            f"タイトルに「{title}」を含むウィンドウがありません。list_windows で確認してください。"
        )
    if len(matches) == 1:
        return matches[0]
    exact = [w for w in matches if w.title.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    lines = [f"- id={w.id} title={w.title}" for w in matches[:MAX_CANDIDATES]]
    if len(matches) > MAX_CANDIDATES:
        lines.append(f"…ほか {len(matches) - MAX_CANDIDATES} 件")
    raise CaptureError(
        f"タイトルに「{title}」を含むウィンドウが {len(matches)} 件あります。"
        "window_id を指定して撮り直してください。\n" + "\n".join(lines)
    )
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `16 passed`

- [ ] **Step 5: コミットする**

```bash
git add src/ai_desktop/imaging.py tests/test_matching.py
git commit -F - <<'EOF'
feat: add capture data types and title-based window selection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Win32 の撮影モジュールとスモークスクリプト

**Goal:** DPI 設定・モニター／ウィンドウの列挙・mss によるモニター撮影・PrintWindow によるウィンドウ撮影を実装し、実機スモークスクリプトで動作を確かめる。

**Files:**
- Create: `src/ai_desktop/capture.py`
- Create: `scripts/smoke.py`

**Acceptance Criteria:**
- [ ] `uv run python scripts/smoke.py` が例外なく終了する
- [ ] 出力の monitor 行の数が接続中のモニター数と一致し、ちょうど1つが `primary=True` である
- [ ] 出力の `captured monitor` のサイズが、プライマリモニターの `width × height`（物理ピクセル）と一致する
- [ ] `smoke-out/monitor.png` と `smoke-out/window.png` が作られ、Read で開くと黒一色ではなく画面の内容が写っている
- [ ] `uv run pytest -v` が引き続き全件 PASS

**Verify:** `PYTHONIOENCODING=utf-8 uv run python scripts/smoke.py` → `monitor:` 行・`windows: N visible`・`captured monitor ...`・`captured window ...` が表示される。その後 `smoke-out/*.png` を Read で目視確認する。

**Steps:**

- [ ] **Step 1: `capture.py` を書く**

`src/ai_desktop/capture.py`:

```python
"""Everything that touches Win32: DPI awareness, enumeration and capture."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import mss
import pywintypes
import win32api
import win32gui
import win32ui
from mss.exception import ScreenShotError
from PIL import Image

from ai_desktop.imaging import CaptureError, MonitorInfo, WindowInfo

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2
DWMWA_CLOAKED = 14
MONITORINFOF_PRIMARY = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_RENDERFULLCONTENT = 2

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")

_user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
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


def enable_dpi_awareness() -> None:
    """Make every API in this process speak physical pixels (spec §6.3)."""
    context = ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    if _user32.SetProcessDpiAwarenessContext(context):
        return
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)


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
    monitors = list_monitors()
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
    if not win32gui.IsWindow(hwnd):
        raise CaptureError(
            f"window_id {hwnd} のウィンドウは存在しません。list_windows で確認してください。"
        )
    try:
        info = _window_info(hwnd, win32gui.GetForegroundWindow())
        if info.minimized:
            raise CaptureError(
                f"「{info.title}」は最小化中のため撮影できません。元に戻してから再実行してください。"
            )
        if info.width <= 0 or info.height <= 0:
            raise CaptureError(f"「{info.title}」はサイズが 0 のため撮影できません。")
        return _print_window(hwnd, info.width, info.height), info
    except (pywintypes.error, win32ui.error) as error:
        raise CaptureError(f"ウィンドウの撮影に失敗しました: {error}") from error


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
                memory_dc.SelectObject(bitmap)
                if not _user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), PW_RENDERFULLCONTENT):
                    raise CaptureError(
                        f"PrintWindow が失敗しました（Win32 エラー {ctypes.get_last_error()}）。"
                    )
                bits = bitmap.GetBitmapBits(True)
            finally:
                win32gui.DeleteObject(bitmap.GetHandle())
        finally:
            memory_dc.DeleteDC()
            window_dc.DeleteDC()
    finally:
        win32gui.ReleaseDC(hwnd, window_dc_handle)
    return Image.frombuffer("RGB", (width, height), bits, "raw", "BGRX", 0, 1)
```

- [ ] **Step 2: スモークスクリプトを書く**

`scripts/smoke.py`:

```python
"""Manual smoke test: enumerate and capture on the real desktop, saving to smoke-out/."""

import sys
from pathlib import Path

from ai_desktop import capture


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    capture.enable_dpi_awareness()
    out = Path(__file__).resolve().parent.parent / "smoke-out"
    out.mkdir(exist_ok=True)

    for monitor in capture.list_monitors():
        print("monitor:", monitor)

    windows = capture.list_windows()
    print(f"windows: {len(windows)} visible")
    for window in windows[:10]:
        print("  ", window)

    image, monitor = capture.capture_monitor(None)
    image.save(out / "monitor.png")
    print("captured monitor", monitor.id, image.size, image.getextrema())

    target = next(w for w in windows if not w.minimized and w.width > 100 and w.height > 100)
    image, window = capture.capture_window(target.id)
    image.save(out / "window.png")
    print("captured window", repr(window.title), image.size, image.getextrema())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: スモークスクリプトを実行する**

Run: `PYTHONIOENCODING=utf-8 uv run python scripts/smoke.py`
Expected:
- 例外なく終了する。
- `monitor:` 行が接続中のモニター数だけ出て、ちょうど1つが `primary=True`。
- `captured monitor <id> (W, H) ...` の `<id>` が `primary=True` のモニターの id で、`(W, H)` がその `width, height` と一致する。
- `captured window '...' (W, H) ...` の extrema が `((0, 0), (0, 0), (0, 0))`（黒一色）ではない。

- [ ] **Step 4: 画像を目視で確認する**

`smoke-out/monitor.png` と `smoke-out/window.png` を Read で開く（大きい場合は `uv run python -c "from PIL import Image; im=Image.open('smoke-out/monitor.png'); im.thumbnail((1000,1000)); im.save('smoke-out/monitor_small.png')"` で縮小してから開く）。
Expected: 両方に、実際のデスクトップとウィンドウの内容が写っていて、切れていない。

- [ ] **Step 5: 既存テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `16 passed`

- [ ] **Step 6: コミットする**

```bash
git add src/ai_desktop/capture.py scripts/smoke.py
git commit -F - <<'EOF'
feat: add Win32 enumeration and capture with smoke script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: MCP サーバーとツール4つ

**Goal:** `MCPServer` でツール4つ（`list_monitors` / `list_windows` / `capture_monitor` / `capture_window`）を公開し、`CaptureError` をメッセージ付きの `ToolError` に変換する。インメモリの MCP クライアントでテストする。

**Files:**
- Create: `src/ai_desktop/server.py`
- Test: `tests/test_server.py`

**Acceptance Criteria:**
- [ ] `list_tools` が、ちょうど `list_monitors`・`list_windows`・`capture_monitor`・`capture_window` の4つを返す
- [ ] `list_monitors` が `MonitorInfo` のフィールドを持つ JSON 配列を返す
- [ ] `capture_monitor` が `image/jpeg` の画像と、仕様 §5.3 のメタデータ JSON の2つを返す（3200×1600 → 1568×784、scale 0.49）
- [ ] `capture_window(title="excel")` で、`source` が `window:42 Book1 - Excel`、`originX` が -100 のメタデータを返す
- [ ] `capture_window` に引数なし、または両方を渡すと、「どちらか一方」を含む `isError` 結果になる
- [ ] `CaptureError` の日本語メッセージが、`isError` 結果のテキストにそのまま含まれる
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `24 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_server.py`:

```python
import asyncio
import json
from dataclasses import asdict

import pytest
from mcp import Client
from PIL import Image

from ai_desktop import capture, server
from ai_desktop.imaging import CaptureError, MonitorInfo, WindowInfo

MONITOR = MonitorInfo(id=1, name=r"\\.\DISPLAY1", primary=True, x=0, y=0, width=3200, height=1600)
WINDOW = WindowInfo(
    id=42, title="Book1 - Excel", app="EXCEL.EXE", x=-100, y=50, width=800, height=600,
    minimized=False, focused=True,
)


def call(name: str, arguments: dict | None = None):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments or {})

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def fake_capture(monkeypatch):
    def fake_capture_monitor(monitor_id):
        if monitor_id not in (None, MONITOR.id):
            raise CaptureError(f"monitor_id {monitor_id} は存在しません。有効な id: 1")
        return Image.new("RGB", (MONITOR.width, MONITOR.height)), MONITOR

    def fake_capture_window(hwnd):
        if hwnd != WINDOW.id:
            raise CaptureError(f"window_id {hwnd} のウィンドウは存在しません。")
        return Image.new("RGB", (WINDOW.width, WINDOW.height)), WINDOW

    monkeypatch.setattr(capture, "list_monitors", lambda: [MONITOR])
    monkeypatch.setattr(capture, "list_windows", lambda: [WINDOW])
    monkeypatch.setattr(capture, "capture_monitor", fake_capture_monitor)
    monkeypatch.setattr(capture, "capture_window", fake_capture_window)


def test_exposes_four_tools():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(run()).tools}
    assert names == {"list_monitors", "list_windows", "capture_monitor", "capture_window"}


def test_list_monitors_returns_json():
    result = call("list_monitors")
    assert not result.is_error
    assert json.loads(result.content[0].text) == [asdict(MONITOR)]


def test_list_windows_returns_json():
    result = call("list_windows")
    assert not result.is_error
    assert json.loads(result.content[0].text) == [asdict(WINDOW)]


def test_capture_monitor_returns_jpeg_and_meta():
    result = call("capture_monitor")
    assert not result.is_error
    image, text = result.content
    assert image.type == "image"
    assert image.mime_type == "image/jpeg"
    assert json.loads(text.text) == {
        "source": r"monitor:1 \\.\DISPLAY1",
        "originX": 0,
        "originY": 0,
        "originalWidth": 3200,
        "originalHeight": 1600,
        "imageWidth": 1568,
        "imageHeight": 784,
        "scale": 0.49,
    }


def test_capture_window_by_title():
    result = call("capture_window", {"title": "excel"})
    assert not result.is_error
    meta = json.loads(result.content[1].text)
    assert meta["source"] == "window:42 Book1 - Excel"
    assert (meta["originX"], meta["originY"]) == (-100, 50)
    assert (meta["imageWidth"], meta["scale"]) == (800, 1.0)


@pytest.mark.parametrize("arguments", [{}, {"window_id": 42, "title": "excel"}])
def test_capture_window_needs_exactly_one_selector(arguments):
    result = call("capture_window", arguments)
    assert result.is_error
    assert "どちらか一方" in result.content[0].text


def test_capture_error_message_reaches_the_model():
    result = call("capture_window", {"window_id": 7})
    assert result.is_error
    assert "window_id 7 のウィンドウは存在しません" in result.content[0].text
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL（`ImportError: cannot import name 'server' from 'ai_desktop'`）

- [ ] **Step 3: 実装する**

`src/ai_desktop/server.py`:

```python
"""MCP server that lets Claude Code see the user's Windows desktop."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from ai_desktop import capture
from ai_desktop.imaging import CaptureError, build_meta, encode_jpeg, select_window, shrink

INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels)."""

mcp = MCPServer("ai-desktop", instructions=INSTRUCTIONS)


@contextmanager
def _reported() -> Iterator[None]:
    """Surface CaptureError text to the model; other exceptions get masked by MCPServer."""
    try:
        yield
    except CaptureError as error:
        raise ToolError(str(error)) from error


def _capture_result(image: PILImage.Image, source: str, origin_x: int, origin_y: int) -> list[Image | str]:
    shrunk, scale = shrink(image)
    meta = build_meta(source, origin_x, origin_y, image.size, shrunk.size, scale)
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(meta, ensure_ascii=False)]


@mcp.tool(structured_output=False)
def list_monitors() -> str:
    """List the user's monitors: id, device name, primary flag, and position/size in
    physical pixels. Pass an id to capture_monitor."""
    with _reported():
        return json.dumps([asdict(m) for m in capture.list_monitors()], ensure_ascii=False)


@mcp.tool(structured_output=False)
def list_windows() -> str:
    """List visible top-level windows, front-most first: id, title, app exe, position/size
    in physical pixels, minimized, focused. Pass an id to capture_window as window_id."""
    with _reported():
        return json.dumps([asdict(w) for w in capture.list_windows()], ensure_ascii=False)


@mcp.tool()
def capture_monitor(monitor_id: int | None = None) -> list[Image | str]:
    """Capture a whole monitor of the user's desktop (the primary monitor when monitor_id
    is omitted). Use this when the user asks you to look at their screen or desktop.
    Returns a JPEG and JSON metadata; screen coordinates = origin + image coordinates / scale."""
    with _reported():
        image, monitor = capture.capture_monitor(monitor_id)
    return _capture_result(image, f"monitor:{monitor.id} {monitor.name}", monitor.x, monitor.y)


@mcp.tool()
def capture_window(window_id: int | None = None, title: str | None = None) -> list[Image | str]:
    """Capture one window, even when other windows cover it. Pass exactly one of window_id
    or title (a case-insensitive part of the window title). Try title first; if several
    windows match, the error lists candidates, so retry with window_id. Minimized windows
    cannot be captured. Returns a JPEG and JSON metadata; screen coordinates = origin +
    image coordinates / scale."""
    if (window_id is None) == (title is None):
        raise ToolError("window_id と title のどちらか一方だけを指定してください。")
    with _reported():
        if window_id is None:
            window_id = select_window(capture.list_windows(), title).id
        image, window = capture.capture_window(window_id)
    return _capture_result(image, f"window:{window.id} {window.title}", window.x, window.y)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    capture.enable_dpi_awareness()
    mcp.run()
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `24 passed`

- [ ] **Step 5: stdio での起動を確認する**

実際の stdio トランスポート越しに、実機で撮影できることを確かめる。次のスクリプトを実行する。

```bash
uv run python - <<'EOF'
import asyncio
from mcp import Client, StdioServerParameters

async def main():
    params = StdioServerParameters(command="uv", args=["run", "ai-desktop"])
    async with Client(params) as client:
        tools = await client.list_tools()
        print(sorted(t.name for t in tools.tools))
        result = await client.call_tool("capture_monitor", {})
        print(result.is_error, [c.type for c in result.content], result.content[1].text)

asyncio.run(main())
EOF
```

Expected: `['capture_monitor', 'capture_window', 'list_monitors', 'list_windows']` の後に `False ['image', 'text'] {"source": "monitor:1 ...", ...}` が表示される（実機のプライマリモニターが撮れている）。

- [ ] **Step 6: コミットする**

```bash
git add src/ai_desktop/server.py tests/test_server.py
git commit -F - <<'EOF'
feat: expose monitor and window capture as MCP tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: README・Claude Code への登録・受け入れテスト

**Goal:** README を書き、Claude Code に MCP サーバーを登録して、仕様 §8 の受け入れテストを実機の Claude Code で確認する。

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Create: `README.md`

**Acceptance Criteria:**
- [ ] `README.md` に、必要環境・`uv sync`・`uv run pytest`・`claude mcp add` での登録・使い方の例・ツール一覧・既知の制限が書かれている
- [ ] `claude mcp list` の出力に `desktop` が含まれ、`Connected` と表示される
- [ ] 受け入れ1: `claude -p` に「今の画面を見て」と頼むと `capture_monitor` が呼ばれ、実際の画面内容に触れた回答が返る
- [ ] 受け入れ2・3: 起動中で、他のウィンドウの裏にある Chrome か VS Code のウィンドウを `title` で撮らせると、そのウィンドウの内容に触れた回答が返る（黒画像ではない）
- [ ] 受け入れ4: 表示スケールが 100% 以外のモニターで、`capture_monitor` のメタデータの `originalWidth × originalHeight` が `list_monitors` のサイズと一致する
- [ ] 受け入れ5（モニターが2台以上ある場合）: `monitor_id=2` で2番目のモニターが撮れる
- [ ] 受け入れ6: 複数のウィンドウに一致するタイトル（例: `Chrome`）を指定すると、Claude が候補リストを受けて `window_id` で撮り直す
- [ ] ユーザーが VS Code の Claude Code パネルから「今の画面を見てアドバイスして」を実行し、問題ないと確認する

**Verify:** `claude mcp list` → `desktop: ... - ✓ Connected`。続いて Step 4 の `claude -p` コマンドを実行し、出力を記録する。

**Steps:**

- [ ] **Step 1: README を書く**

`README.md`:

````markdown
# ai-desktop

Claude Code（VS Code 拡張・CLI）から、Windows のデスクトップ画面を AI が自分で撮影して見られるようにする MCP サーバーです。
チャットで「今の画面を見てアドバイスして」「Excel のウィンドウを見て」と頼むだけで、Claude が画面を撮影して答えます。

## 必要環境

- Windows 10 / 11
- [uv](https://docs.astral.sh/uv/)
- Claude Code

## セットアップ

```powershell
cd C:\Works\2026\ai-desktop
uv sync
uv run pytest
```

## Claude Code への登録

```powershell
claude mcp add --scope user desktop -- uv run --directory C:/Works/2026/ai-desktop ai-desktop
claude mcp list   # desktop が ✓ Connected になっていれば OK
```

登録後、Claude Code のセッションを開き直すとツールが使えるようになります。撮影のたびに Claude Code の許可確認が出ます。

## 使い方の例

- 「今の画面を見てアドバイスして」
- 「Excel のウィンドウを見て、この表の改善点を教えて」
- 「2番目のモニターに何が映ってる？」

## ツール

| ツール | 内容 |
|---|---|
| `list_monitors` | モニター一覧（id・名前・プライマリか・位置とサイズ） |
| `list_windows` | 表示中のウィンドウ一覧（id・タイトル・アプリ・位置とサイズ・最小化中か・アクティブか） |
| `capture_monitor` | モニター全体を撮影（省略時はプライマリ） |
| `capture_window` | ウィンドウを撮影（`window_id` か `title` の部分一致） |

撮影結果は JPEG（長辺 1568px 以下）と座標メタデータです。画面座標 = `origin + 画像上の座標 ÷ scale`（物理ピクセル）。

## 既知の制限

- 最小化中のウィンドウは撮影できません。
- DRM 保護された内容は黒く写ることがあります。
- 管理者権限で動いているウィンドウは撮影できない場合があります。
- スクショはディスクに保存しません。

## 実機の動作確認

```powershell
uv run python scripts/smoke.py   # smoke-out/ に monitor.png と window.png を保存
```

設計の詳細は [docs/superpowers/specs/2026-10-03-desktop-vision-mcp-design.md](docs/superpowers/specs/2026-10-03-desktop-vision-mcp-design.md) を参照してください。
````

- [ ] **Step 2: コミットする**

```bash
git add README.md
git commit -F - <<'EOF'
docs: add README with setup and registration steps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 3: Claude Code に登録する**

Run: `claude mcp add --scope user desktop -- uv run --directory C:/Works/2026/ai-desktop ai-desktop`
Run: `claude mcp list`
Expected: `desktop: uv run --directory C:/Works/2026/ai-desktop ai-desktop - ✓ Connected`

すでに `desktop` が登録済みでエラーになった場合は、`claude mcp get desktop` で中身を確認し、同じコマンドならそのまま進める。違う内容なら、上書きしてよいかユーザーに確認してから `claude mcp remove --scope user desktop` → 再登録する。

- [ ] **Step 4: ヘッドレスの Claude Code で受け入れテストを行う**

各コマンドの出力を記録する。`--allowedTools` で、このサーバーのツールだけを許可する。

```bash
TOOLS="mcp__desktop__list_monitors mcp__desktop__list_windows mcp__desktop__capture_monitor mcp__desktop__capture_window"

# 受け入れ1
claude -p "今の画面を見て、何が表示されているか2文で教えて" --allowedTools $TOOLS

# 受け入れ2・3（事前に Chrome を開き、VS Code の裏に回しておく）
claude -p "Chrome のウィンドウを title 指定で撮影して、何が表示されているか1文で教えて" --allowedTools $TOOLS

# 受け入れ4・5
claude -p "list_monitors の結果と、各モニターを capture_monitor した結果のメタデータの originalWidth/originalHeight を表にして" --allowedTools $TOOLS

# 受け入れ6
claude -p "title に 'Chrome' を指定して capture_window を呼び、複数候補が返ったら window_id で1つ選んで撮り直して。何をしたか説明して" --allowedTools $TOOLS
```

Expected:
- 1: 実際に画面に出ているもの（例: VS Code やこの計画書）に具体的に触れた回答
- 2・3: Chrome のページ内容に触れた回答。黒い画像だという回答ではない
- 4・5: 各モニターの `originalWidth × originalHeight` が `list_monitors` の `width × height` と一致する
- 6: 候補リストのエラーを受けて `window_id` で撮り直したという説明（Chrome のウィンドウが1つしかない場合は、2つ目を開いてから実行する）

- [ ] **Step 5: ユーザーに VS Code で最終確認してもらう**

ユーザーに次を依頼し、結果を待つ。
1. VS Code の Claude Code パネルで、新しいセッションを開く。
2. 「今の画面を見てアドバイスして」と送る。
3. 許可確認が出たら許可し、画面内容に基づいたアドバイスが返ることを確認する。

ユーザーが問題ないと答えたらタスク完了とする。
