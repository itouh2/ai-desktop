# 注釈付きスクショ表示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude が撮影したスクショを背景に、Claude が書いた HTML（枠・番号・吹き出し・矢印）を重ねたページを、既定のブラウザで開く `show_annotated` ツールを ai-desktop MCP サーバーに追加する。

**Architecture:** 撮影ツールが、元の解像度の JPEG を `CaptureStore`（直近10件、メモリ上）に保存し、メタデータに `captureId` を付けて返す。`show_annotated` はその画像を背景にし、Claude の HTML を画像のピクセル座標で重ねた、1ファイル完結の HTML を `annotate.py` で生成する。生成したファイルは一時フォルダに保存し（直近30件）、`os.startfile` でブラウザを開く。

**Tech Stack:** Python 3.12 / uv / mcp 2.x（`MCPServer`）/ Pillow / pytest（既存の ai-desktop プロジェクトに追加）

**Global Constraints:**
- 仕様書: `docs/superpowers/specs/2026-10-03-annotated-view-design.md`
- Windows 専用。Win32 API に触れるコードは `src/ai_desktop/capture.py` にだけ置く。ブラウザ起動の `os.startfile` は `annotate.open_in_browser` にだけ置く。
- ツールのエラーは `mcp.server.mcpserver.exceptions.ToolError` で送出する（他の例外ではメッセージが隠される）。`CaptureError` は既存の `_reported()` で `ToolError` に変換する。文字列を返すツールは `@mcp.tool(structured_output=False)`。
- 撮影メタデータのキーは `source, originX, originY, originalWidth, originalHeight, imageWidth, imageHeight, scale, captureId` の9つ。`captureId` は `c1`、`c2`… の連番。
- `CaptureStore` が保持するのは直近 **10** 件で、背景は元の解像度の JPEG（品質 **90**）のバイト列。
- 注釈の座標系は、その撮影の縮小画像のピクセル座標（`imageWidth × imageHeight`）。
- ページの CSP は次の文字列で固定: `default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-<nonce>'`
- ページの保存先は `%TEMP%\ai-desktop\annotations\`（`Path(tempfile.gettempdir()) / "ai-desktop" / "annotations"`）。ファイル名は `annotated-YYYYMMDD-HHMMSS-ffffff-<hex6>.html`、保持は直近 **30** 件。
- `html` の上限は 100,000 文字。空白だけの `html` はエラーにする。
- ユーザー向けのエラーメッセージは日本語で書く。
- 標準出力は MCP 専用。ログは標準エラー出力に出す。
- コミットメッセージの末尾は `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 未追跡の `docs/superpowers/reviews/`（外部レビュー）と `.superpowers/` はステージしない。

**User decisions (already made):**
- 透明オーバーレイはあきらめ、HTML を普通に表示し、その背景にスクショを出すだけにする。
- 表示先は、いつものブラウザ（既定のブラウザ）。
- 「ディスクに保存しない」には縛られなくてよい。スマートに実装できる方法を選ぶ（→ 一時フォルダに HTML ファイルを書く方式を採用）。
- 注釈の書き方は「自由な HTML＋部品クラス」。
- 設計セクション1（流れ・ツール・座標・部品クラス）は承認済み。

---

## ファイル構成

| パス | 責務 |
|---|---|
| `src/ai_desktop/captures.py`（新規） | `CaptureStore`: 直近の撮影（背景 JPEG＋メタデータ）をメモリに保持する |
| `src/ai_desktop/annotate.py`（新規） | `render_page`（HTML 生成）、`save_page`（保存と古いファイルの削除）、`open_in_browser` |
| `src/ai_desktop/server.py`（変更） | `captureId` の付与、`show_annotated` ツール、`INSTRUCTIONS` の更新 |
| `tests/test_captures.py`（新規） | `CaptureStore` |
| `tests/test_annotate.py`（新規） | `render_page` と `save_page` |
| `tests/test_server.py`（変更） | `captureId`、`show_annotated` |
| `README.md`（変更） | 新ツールと一時フォルダへの保存の説明 |

コマンドはすべて `C:\Works\2026\ai-desktop` で実行する（Bash ツールでは `cd /c/Works/2026/ai-desktop`）。作業ブランチは `feat/annotated-view`。

---

### Task 1: CaptureStore と captureId

**Goal:** 撮影画像を元の解像度の JPEG にして `CaptureStore` に保存し、撮影ツールのメタデータに `captureId` を付けて返す。

**Files:**
- Create: `src/ai_desktop/captures.py`
- Modify: `src/ai_desktop/server.py`（import、`BACKGROUND_JPEG_QUALITY`、`captures`、`_capture_result`）
- Test: `tests/test_captures.py`
- Modify: `tests/test_server.py`（fixture、メタデータの期待値、新テスト1件）

**Acceptance Criteria:**
- [ ] `CaptureStore.add` が `c1`、`c2`… と連番の id を返す
- [ ] `CaptureStore.get` が保存した `(bytes, dict)` をそのまま返す
- [ ] `limit` を超えると最古のものが消え、`get` で `CaptureError` になる
- [ ] 未知の id の `CaptureError` に、その id・保持中の id 一覧・「撮影し直して」が含まれる
- [ ] `capture_monitor` のメタデータが、既存の8キーに `"captureId": "c1"` を加えた9キーになる
- [ ] 2回撮影すると `c1`、`c2` になり、ストアの背景が元の解像度（3200×1600）の JPEG になっている
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `33 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_captures.py`:

```python
import pytest

from ai_desktop.captures import CaptureStore
from ai_desktop.imaging import CaptureError


def test_ids_are_sequential():
    store = CaptureStore()
    assert store.add(b"a", {}) == "c1"
    assert store.add(b"b", {}) == "c2"


def test_get_returns_stored_capture():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {"imageWidth": 10})
    assert store.get(capture_id) == (b"jpeg", {"imageWidth": 10})


def test_oldest_capture_is_evicted_past_limit():
    store = CaptureStore(limit=3)
    ids = [store.add(bytes([i]), {}) for i in range(4)]
    assert ids == ["c1", "c2", "c3", "c4"]
    with pytest.raises(CaptureError):
        store.get("c1")
    assert store.get("c4") == (bytes([3]), {})


def test_unknown_id_lists_available_ids():
    store = CaptureStore()
    store.add(b"a", {})
    store.add(b"b", {})
    with pytest.raises(CaptureError) as error:
        store.get("c9")
    message = str(error.value)
    assert "c9" in message
    assert "c1, c2" in message
    assert "撮影し直して" in message
```

`tests/test_server.py` を次のように変更する。

1. import に `from ai_desktop.captures import CaptureStore` を追加する。
2. `fake_capture` fixture の末尾（最後の `monkeypatch.setattr(capture, "capture_window", fake_capture_window)` の直後）に、次の1行を追加する。

```python
    monkeypatch.setattr(server, "captures", CaptureStore())
```

3. `test_capture_monitor_returns_jpeg_and_meta` の期待する dict の最後（`"scale": 0.49,` の次）に、`"captureId": "c1",` を追加する。ほかの値は変えない。
4. ファイル末尾に次のテストを追加する。

```python
def test_captures_are_stored_with_sequential_ids():
    first = json.loads(call("capture_monitor").content[1].text)
    second = json.loads(call("capture_window", {"title": "excel"}).content[1].text)
    assert (first["captureId"], second["captureId"]) == ("c1", "c2")
    background, meta = server.captures.get("c1")
    assert Image.open(io.BytesIO(background)).size == (3200, 1600)
    assert meta == first
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'ai_desktop.captures'`）

- [ ] **Step 3: `captures.py` を実装する**

`src/ai_desktop/captures.py`:

```python
"""Recent captures kept in memory, so annotations land on the exact image Claude saw."""

from __future__ import annotations

import threading
from collections import OrderedDict

from ai_desktop.imaging import CaptureError

CAPTURE_LIMIT = 10


class CaptureStore:
    """Background JPEG and metadata of the latest captures, keyed c1, c2, ..."""

    def __init__(self, limit: int = CAPTURE_LIMIT) -> None:
        self._limit = limit
        self._items: OrderedDict[str, tuple[bytes, dict]] = OrderedDict()
        self._next_number = 1
        self._lock = threading.Lock()  # tools may run on parallel worker threads

    def add(self, background_jpeg: bytes, meta: dict) -> str:
        with self._lock:
            capture_id = f"c{self._next_number}"
            self._next_number += 1
            self._items[capture_id] = (background_jpeg, meta)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
            return capture_id

    def get(self, capture_id: str) -> tuple[bytes, dict]:
        with self._lock:
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

- [ ] **Step 4: `server.py` に `captureId` を組み込む**

`src/ai_desktop/server.py` の `from ai_desktop import capture` の下に、次の1行を追加する。

```python
from ai_desktop.captures import CaptureStore
```

`mcp = MCPServer("ai-desktop", instructions=INSTRUCTIONS)` の直後に、次を追加する。

```python
BACKGROUND_JPEG_QUALITY = 90
captures = CaptureStore()
```

`_capture_result` を次の内容に置き換える。

```python
def _capture_result(image: PILImage.Image, source: str, origin_x: int, origin_y: int) -> list[Image | str]:
    shrunk, scale = shrink(image)
    meta = build_meta(source, origin_x, origin_y, image.size, shrunk.size, scale)
    meta["captureId"] = captures.add(encode_jpeg(image, quality=BACKGROUND_JPEG_QUALITY), meta)
    return [Image(data=encode_jpeg(shrunk), format="jpeg"), json.dumps(meta, ensure_ascii=False)]
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `33 passed`

- [ ] **Step 6: コミットする**

```bash
git add src/ai_desktop/captures.py src/ai_desktop/server.py tests/test_captures.py tests/test_server.py
git commit -F - <<'EOF'
feat: keep recent captures in memory and return captureId

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: 注釈ページの生成と保存

**Goal:** 背景画像の上に Claude の HTML を重ねる1ファイル完結のページを生成し（CSP・部品クラス・矢じりマーカー・幅合わせスクリプト付き）、一時フォルダに保存して古いものを削除する `annotate.py` を作る。

**Files:**
- Create: `src/ai_desktop/annotate.py`
- Test: `tests/test_annotate.py`

**Acceptance Criteria:**
- [ ] ページに、CSP 文字列 `default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-<nonce>'` と `<script nonce="<nonce>">` が入る
- [ ] `#stage` の style が `width:<imageWidth>px;height:<imageHeight>px` になる
- [ ] 背景が `data:image/jpeg;base64,...` で埋め込まれる
- [ ] Claude の HTML が `#annotations` にそのまま入り、`title` は HTML エスケープされる
- [ ] `.box`、`.badge`、`.note`、`.arrow`、`svg.layer` の CSS と `id="arrowhead"` のマーカーが入る
- [ ] `save_page` が `annotated-*.html` を書いてパスを返し、新しいものを含めて `keep` 件だけ残す。無関係なファイルは消さない
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `40 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_annotate.py`:

```python
import base64

from ai_desktop.annotate import render_page, save_page

BOX = '<div class="box" style="left:10px;top:20px;width:30px;height:40px"></div>'
PAGE_ARGS = dict(
    background_jpeg=b"\xff\xd8fake",
    image_width=1568,
    image_height=882,
    html=BOX,
    title="Book1 <Excel>",
    nonce="n0nce",
)


def test_page_has_strict_csp_with_nonce():
    page = render_page(**PAGE_ARGS)
    csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-n0nce'"
    assert f'content="{csp}"' in page
    assert '<script nonce="n0nce">' in page


def test_stage_matches_image_size():
    assert 'id="stage" style="width:1568px;height:882px"' in render_page(**PAGE_ARGS)


def test_background_is_embedded_as_data_uri():
    encoded = base64.b64encode(b"\xff\xd8fake").decode()
    assert f'src="data:image/jpeg;base64,{encoded}"' in render_page(**PAGE_ARGS)


def test_claude_html_is_verbatim_and_title_escaped():
    page = render_page(**PAGE_ARGS)
    assert f'<div id="annotations">{BOX}</div>' in page
    assert "<title>Book1 &lt;Excel&gt;</title>" in page


def test_page_defines_helper_classes_and_arrowhead():
    page = render_page(**PAGE_ARGS)
    for selector in (
        "#annotations .box",
        "#annotations .badge",
        "#annotations .note",
        "#annotations .arrow",
        "#annotations svg.layer",
    ):
        assert selector in page
    assert 'id="arrowhead"' in page


def test_save_page_writes_file(tmp_path):
    directory = tmp_path / "out"
    path = save_page("<html>x</html>", directory)
    assert path.parent == directory
    assert path.name.startswith("annotated-")
    assert path.suffix == ".html"
    assert path.read_text(encoding="utf-8") == "<html>x</html>"


def test_save_page_keeps_only_newest(tmp_path):
    for day in range(1, 5):
        (tmp_path / f"annotated-2000010{day}-000000-000000-aaaaaa.html").write_text("old", encoding="utf-8")
    unrelated = tmp_path / "keep-me.txt"
    unrelated.write_text("x", encoding="utf-8")

    path = save_page("new", tmp_path, keep=3)

    remaining = sorted(p.name for p in tmp_path.glob("annotated-*.html"))
    assert len(remaining) == 3
    assert path.name in remaining
    assert "annotated-20000104-000000-000000-aaaaaa.html" in remaining
    assert "annotated-20000103-000000-000000-aaaaaa.html" in remaining
    assert unrelated.exists()
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_annotate.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'ai_desktop.annotate'`）

- [ ] **Step 3: 実装する**

`src/ai_desktop/annotate.py`:

```python
"""Annotated screenshot pages: Claude's HTML layered over a capture, opened in the browser."""

from __future__ import annotations

import base64
import html as html_lib
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

ANNOTATION_DIR = Path(tempfile.gettempdir()) / "ai-desktop" / "annotations"
KEEP_PAGES = 30

_CSS = """
html, body { margin: 0; background: #1e1e1e; }
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

# Scale the whole stage to the window width, so annotations stay on their image pixels.
_FIT_SCRIPT = """
const stage = document.getElementById("stage");
const viewport = document.getElementById("viewport");
function fit() {
  const scale = document.documentElement.clientWidth / stage.offsetWidth;
  stage.style.transform = "scale(" + scale + ")";
  viewport.style.height = stage.offsetHeight * scale + "px";
}
addEventListener("resize", fit);
fit();
"""


def render_page(
    background_jpeg: bytes,
    image_width: int,
    image_height: int,
    html: str,
    title: str,
    nonce: str,
) -> str:
    """One self-contained page: the capture as background, Claude's HTML on top in image pixels."""
    background = base64.b64encode(background_jpeg).decode("ascii")
    csp = f"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'"
    return (
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        f"<title>{html_lib.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head><body>\n"
        f"{_ARROWHEAD}\n"
        '<div id="viewport">'
        f'<div id="stage" style="width:{image_width}px;height:{image_height}px">'
        f'<img id="shot" src="data:image/jpeg;base64,{background}" alt="">'
        f'<div id="annotations">{html}</div>'
        "</div></div>\n"
        f'<script nonce="{nonce}">{_FIT_SCRIPT}</script>\n'
        "</body></html>\n"
    )


def save_page(page: str, directory: Path, keep: int = KEEP_PAGES) -> Path:
    """Write the page and delete older pages so only the newest `keep` remain."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"annotated-{stamp}-{uuid.uuid4().hex[:6]}.html"
    path.write_text(page, encoding="utf-8")
    others = sorted(p for p in directory.glob("annotated-*.html") if p != path)
    for old in others[: max(0, len(others) - (keep - 1))]:
        old.unlink(missing_ok=True)
    return path


def open_in_browser(path: Path) -> None:
    """Open with the app associated with .html, normally the default browser."""
    os.startfile(path)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `40 passed`

- [ ] **Step 5: コミットする**

```bash
git add src/ai_desktop/annotate.py tests/test_annotate.py
git commit -F - <<'EOF'
feat: render annotated screenshot pages with strict CSP

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: show_annotated ツール

**Goal:** `show_annotated(capture_id, html, title=None)` を MCP ツールとして公開し、ページを保存してブラウザで開く。サーバーの説明文でも、このツールの使い方を Claude に伝える。

**Files:**
- Modify: `src/ai_desktop/server.py`（import、`INSTRUCTIONS`、`MAX_HTML_CHARS`、`show_annotated`）
- Modify: `tests/test_server.py`（ツール数のテスト、新テスト4件）

**Acceptance Criteria:**
- [ ] `list_tools` が5つ（既存4つ＋`show_annotated`）を返す
- [ ] `show_annotated` が `annotate.ANNOTATION_DIR` にページを書き、`annotate.open_in_browser` をそのパスで1回呼び、結果テキストにそのパスが入る
- [ ] ページの `#stage` が撮影画像のサイズ（800×600）、`<title>` が `title` 省略時にメタデータの `source` になる
- [ ] 未知の `capture_id` は、その id を含む `isError` 結果になり、ブラウザは開かない
- [ ] 空・空白だけの `html` は「html が空です」を含む `isError` 結果になり、ブラウザは開かない
- [ ] `uv run pytest -v` が全件 PASS

**Verify:** `uv run pytest -v` → `44 passed`

**Steps:**

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_server.py` を次のように変更する。

1. `from ai_desktop import capture, server` を `from ai_desktop import annotate, capture, server` に変える。
2. `test_exposes_four_tools` を次の内容に置き換える。

```python
def test_exposes_five_tools():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(run()).tools}
    assert names == {
        "list_monitors", "list_windows", "capture_monitor", "capture_window", "show_annotated",
    }
```

3. ファイル末尾に次を追加する。

```python
@pytest.fixture
def opened(monkeypatch, tmp_path):
    paths = []
    monkeypatch.setattr(annotate, "ANNOTATION_DIR", tmp_path)
    monkeypatch.setattr(annotate, "open_in_browser", paths.append)
    return paths


def test_show_annotated_writes_page_and_opens_browser(opened, tmp_path):
    call("capture_window", {"title": "excel"})
    badge = '<div class="badge" style="left:5px;top:5px">1</div>'
    result = call("show_annotated", {"capture_id": "c1", "html": badge})
    assert not result.is_error
    assert len(opened) == 1
    path = opened[0]
    assert path.parent == tmp_path
    assert str(path) in result.content[0].text
    page = path.read_text(encoding="utf-8")
    assert badge in page
    assert 'id="stage" style="width:800px;height:600px"' in page
    assert "<title>window:42 Book1 - Excel</title>" in page


def test_show_annotated_unknown_capture_is_reported(opened):
    result = call("show_annotated", {"capture_id": "c99", "html": "<div></div>"})
    assert result.is_error
    assert "c99" in result.content[0].text
    assert opened == []


@pytest.mark.parametrize("html", ["", "   "])
def test_show_annotated_rejects_empty_html(opened, html):
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "html": html})
    assert result.is_error
    assert "html が空です" in result.content[0].text
    assert opened == []
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL（`test_exposes_five_tools` で `show_annotated` が無い。`show_annotated` 系のテストは unknown tool のエラー）

- [ ] **Step 3: 実装する**

`src/ai_desktop/server.py` の import を次のように変える。

- 既存の `import logging` の下に `import secrets` を追加する。
- `from ai_desktop import capture` を `from ai_desktop import annotate, capture` に変える。

`INSTRUCTIONS` を次の内容に置き換える。

```python
INSTRUCTIONS = """\
Gives you eyes on the user's Windows desktop. When the user asks about their screen, \
what they are looking at, or a specific app window, capture it instead of asking them \
to describe it. For a specific app, call capture_window with part of its title; if \
several windows match, the error lists candidates, so retry with window_id. Every \
capture returns a JPEG plus JSON metadata, where screen coordinates = origin + image \
coordinates / scale (physical pixels). To point at things on screen, call \
show_annotated with the capture's captureId and HTML positioned in that image's pixel \
coordinates; it opens in the user's browser."""
```

`captures = CaptureStore()` の下に、次を追加する。

```python
MAX_HTML_CHARS = 100_000
```

`capture_window` ツールの後ろ（`def main()` の前）に、次を追加する。

```python
@mcp.tool(structured_output=False)
def show_annotated(capture_id: str, html: str, title: str | None = None) -> str:
    """Show the user one of your captures with your annotations drawn on top, in their
    default browser. Use it when pointing at places on screen makes your advice clearer.

    capture_id: the captureId from a capture's metadata (the latest 10 are kept).
    html: elements positioned absolutely with style left/top in that capture's image
    pixels (imageWidth x imageHeight, i.e. the image you saw). Helper classes:
    .box (outline; left/top/width/height), .badge (numbered circle; left/top is its
    center), .note (callout; left/top is its top-left corner), and for arrows
    <svg class="layer"><line class="arrow" x1=".." y1=".." x2=".." y2=".."/></svg>
    (svg.layer covers the image, in image pixels). Scripts and external resources are
    blocked. title: optional page title. The page is saved in the temp folder (latest 30 kept)."""
    if not html.strip():
        raise ToolError("html が空です。枠や注釈の HTML を指定してください。")
    if len(html) > MAX_HTML_CHARS:
        raise ToolError(f"html が長すぎます（{len(html)} 文字）。{MAX_HTML_CHARS} 文字以内にしてください。")
    with _reported():
        background, meta = captures.get(capture_id)
    page = annotate.render_page(
        background,
        meta["imageWidth"],
        meta["imageHeight"],
        html,
        title or meta["source"],
        secrets.token_urlsafe(16),
    )
    path = annotate.save_page(page, annotate.ANNOTATION_DIR)
    annotate.open_in_browser(path)
    return f"ブラウザで表示しました: {path}"
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest -v`
Expected: `44 passed`

- [ ] **Step 5: コミットする**

```bash
git add src/ai_desktop/server.py tests/test_server.py
git commit -F - <<'EOF'
feat: add show_annotated tool to open annotated captures in the browser

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: README と実機での表示確認

**Goal:** README に `show_annotated` と一時フォルダへの保存を書き足し、headless の Claude Code で「撮影 → 注釈付き表示」を実行して、ブラウザ上で注釈が狙った位置に重なっていることを、ブラウザウィンドウの撮影画像で確認する。

**Files:**
- Modify: `README.md`

**Acceptance Criteria:**
- [ ] README のツール表に `show_annotated` の行があり、使い方の例に注釈表示の例がある
- [ ] README の「既知の制限」の「スクショはディスクに保存しません。」が、「撮影ツールはディスクに保存しません。`show_annotated` のページ（スクショ入り）は `%TEMP%\ai-desktop\annotations\` に直近30件まで保存されます。」に置き換わっている
- [ ] `claude -p` の実行で `capture_window` → `show_annotated` が呼ばれ、ツールの結果に `ブラウザで表示しました:` が含まれる
- [ ] `%TEMP%\ai-desktop\annotations\` に新しい `annotated-*.html` ができている
- [ ] 開いたブラウザのウィンドウ（タイトルに `ai-desktop 注釈テスト` を含む）を撮影した画像で、VS Code のスクショの上に、赤枠・番号・吹き出し・矢印が表示されている。赤枠がエクスプローラー領域を、吹き出しがエディタ領域を指している（目視）

**Verify:** Step 3 の `claude -p` の出力に `show_annotated` の呼び出しと `ブラウザで表示しました:` が含まれる。Step 4 で撮ったブラウザ画像を Read で開き、注釈の位置を目視で確認する。

**Steps:**

- [ ] **Step 1: README を更新する**

`README.md` を次のように変更する。

1. 「使い方の例」の箇条書きの最後に、次の1行を追加する。

```markdown
- 「どこを押せばいいか、画面に印をつけて見せて」（注釈付きのスクショがブラウザで開きます）
```

2. 「ツール」の表の最後の行（`capture_window`）の後に、次の行を追加する。

```markdown
| `show_annotated` | 撮影画像を背景に、Claude が書いた枠・番号・吹き出し・矢印を重ねたページをブラウザで開く（`captureId` を指定） |
```

3. 「既知の制限」の `- スクショはディスクに保存しません。` を、次の行に置き換える。

```markdown
- 撮影ツールはディスクに保存しません。`show_annotated` のページ（スクショ入り）は `%TEMP%\ai-desktop\annotations\` に直近30件まで保存されます。
```

4. 「Claude Code への登録」の節の最後に、次の1文を追加する。

```markdown
ツールを追加・更新したあとは、Claude Code のセッションを開き直すと反映されます。
```

- [ ] **Step 2: コミットする**

```bash
git add README.md
git commit -F - <<'EOF'
docs: document show_annotated and annotation page storage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 3: headless の Claude Code で表示を実行する**

`desktop` MCP サーバーは登録済み（`claude mcp list` で確認）。`claude -p` を起動するたびに、このフォルダのコードで新しくサーバーが立ち上がる。ユーザーのデスクトップのウィンドウは開閉・移動しない。ブラウザのタブが1つ開くのは、この機能の正常な動作。

```bash
TOOLS="mcp__desktop__list_windows mcp__desktop__capture_window mcp__desktop__show_annotated"
claude -p "VS Code のウィンドウを capture_window で撮影して。続けて show_annotated を title 'ai-desktop 注釈テスト' で呼び、左側のエクスプローラー領域を .box で囲んで .badge の 1 を付け、エディタ領域の中央付近に .note で『ここがエディタです』と書き、その note からエクスプローラーの枠へ svg.layer の .arrow で矢印を引いて。最後に結果のファイルパスを教えて" --allowedTools $TOOLS --output-format stream-json --verbose
```

`--allowedTools` に空白区切りが通らない場合は、カンマ区切りにする。
Expected: 出力に `capture_window` と `show_annotated` の呼び出しがあり、ツール結果に `ブラウザで表示しました:` とファイルパスが含まれる。

- [ ] **Step 4: ブラウザの表示を撮影して確認する**

ブラウザがページを描き終わるまで数秒待ってから実行する。

```bash
uv run python -c "import os; from ai_desktop.annotate import ANNOTATION_DIR; print(ANNOTATION_DIR, sorted(os.listdir(ANNOTATION_DIR))[-3:])"
PYTHONIOENCODING=utf-8 uv run python - <<'EOF'
from pathlib import Path
from ai_desktop import capture
from ai_desktop.imaging import select_window
capture.enable_dpi_awareness()
window = select_window(capture.list_windows(), "ai-desktop 注釈テスト")
image, info = capture.capture_window(window.id)
image.thumbnail((1400, 1400))
Path("smoke-out").mkdir(exist_ok=True)
image.save("smoke-out/annotated-browser.png")
print(info.title, image.size)
EOF
```

`smoke-out/annotated-browser.png` を Read で開く。
Expected: ページのタイトルを含むブラウザのウィンドウが撮れている。VS Code のスクショの上に赤枠（エクスプローラー領域）、番号1の丸、吹き出し（エディタ領域）、矢印が表示されていて、それぞれ狙った領域に重なっている。ずれている場合は、ずれの方向と量を記録して DONE_WITH_CONCERNS で報告する。

- [ ] **Step 5: ユーザーに VS Code での確認を依頼する**

ユーザーに次を依頼する。
1. VS Code の Claude Code パネルで、新しいセッションを開く（新しいツールを読み込むため）。
2. 「画面を見て、どこを直せばいいか印をつけて見せて」と送る。
3. ブラウザに注釈付きのスクショが開くことを確認する。
