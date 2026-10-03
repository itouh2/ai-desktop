# ai-desktop: デスクトップ撮影 MCP サーバー 設計書（MVP）

- 日付: 2026-10-03
- 状態: 設計承認済み・実装前

## 1. 目的

VS Code の Claude Code（IDE の AI プラグイン）から、ユーザーのデスクトップ画面を AI が自分で撮影して見られるようにする。ユーザーはチャットで「今の画面を見てアドバイスして」「Excel のウィンドウを見て」と頼むだけでよい。

アドバイスを考えるのは Claude Code 側の Claude である。本サーバーは「目」だけを提供し、画像と座標情報を返す。

用途は限定しない（汎用）。

## 2. スコープ

### MVP に含める

- モニター一覧の取得
- ウィンドウ一覧の取得
- モニター全体の撮影
- 特定ウィンドウの撮影（ID 指定、またはタイトルの部分一致）
- 撮影画像の縮小と JPEG 化、および座標メタデータの返却

### MVP に含めない

- 画面操作ツール（クリック・入力など）。将来は pywinauto / PyAutoGUI で追加する
- 範囲を指定した拡大撮影
- ホットキー、常駐 UI
- 画像のディスク保存
- macOS / Linux 対応（Windows 専用）

将来の操作ツールに備え、座標メタデータは MVP から返す（§5.3）。

## 3. 全体構成

```
VS Code の Claude Code ──(stdio / MCP)──▶ ai-desktop MCP サーバー（Python, uv 管理）
                                            ├─ pywin32 / ctypes : モニター・ウィンドウの列挙、PrintWindow によるウィンドウ撮影、DPI 設定
                                            ├─ mss              : モニター撮影
                                            └─ Pillow           : 縮小・JPEG エンコード
```

### 技術スタック

| 項目 | 採用 |
|---|---|
| 言語 | Python 3.12（`requires-python >= 3.11`） |
| パッケージ管理 | uv |
| MCP | 公式 Python SDK `mcp`（`FastMCP`、stdio トランスポート） |
| 撮影 | `mss`（モニター）、`pywin32` と `ctypes`（ウィンドウ） |
| 画像 | `Pillow` |
| テスト | `pytest` |

Python を選んだのは、将来の操作機能で pywinauto（UI Automation）と PyAutoGUI を使いたいためである。

### 登録方法

```
claude mcp add --scope user desktop -- uv run --directory C:/Works/2026/ai-desktop ai-desktop
```

`--scope user` で登録するので、どのプロジェクトからでも使える。

## 4. ファイル構成

```
ai-desktop/
├─ pyproject.toml             # 依存定義、エントリポイント ai-desktop = ai_desktop.server:main
├─ README.md                  # セットアップと登録手順
├─ src/ai_desktop/
│  ├─ __init__.py
│  ├─ server.py               # FastMCP の生成、ツール4つの定義、main()
│  ├─ capture.py              # Win32 依存: DPI 設定、モニター・ウィンドウの列挙、撮影
│  └─ imaging.py              # Windows 非依存の純粋処理: 縮小計算、JPEG 化、メタデータ、ウィンドウ選択
└─ tests/
   ├─ test_imaging.py
   └─ test_matching.py
```

### 各ユニットの責務

- **`imaging.py`**: OS に依存しない純粋な関数だけを置く。どの OS でもテストできる。
  - `fit_size(width, height, max_edge=1568) -> (new_width, new_height, scale)`
  - `encode_jpeg(image, quality=85) -> bytes`
  - `build_meta(source, origin_x, origin_y, original_size, image_size, scale) -> dict`
  - `image_to_screen(meta, x, y) -> (screen_x, screen_y)`: メタデータの変換式を表す関数。テストで仕様を固定するために用意し、将来の操作ツールでも使う
  - `select_window(windows, title) -> WindowInfo`: タイトルでウィンドウを1つ選ぶ（§6.2）。該当なし・複数該当のときは `CaptureError` を送出する
- **`capture.py`**: Win32 API に触れるコードはすべてここに置く。
  - `enable_dpi_awareness()`
  - `list_monitors() -> list[MonitorInfo]`
  - `list_windows() -> list[WindowInfo]`
  - `capture_monitor(monitor_id: int | None) -> (PIL.Image, MonitorInfo)`
  - `capture_window(hwnd: int) -> (PIL.Image, WindowInfo)`
- **`server.py`**: 入力の検証、`capture` と `imaging` の呼び出し、MCP の戻り値の組み立てだけを行う。
- **`CaptureError`**: ユーザー向けのメッセージを持つ例外。`imaging.py` に定義し、`capture.py` からも使う。

`MonitorInfo` / `WindowInfo` は dataclass とし、`imaging.py` に置く（`select_window` のテストで Win32 なしに作れるようにするため）。

## 5. ツール仕様

ツールのエラーは例外として送出する。FastMCP がこれを `isError` 付きのツール結果に変換するので、Claude はメッセージを読んで次の手を判断できる。

### 5.1 `list_monitors`

- 入力: なし
- 出力: JSON テキスト。モニターの配列

```json
[{ "id": 1, "name": "\\\\.\\DISPLAY1", "primary": true,
   "x": 0, "y": 0, "width": 2560, "height": 1440 }]
```

- `id` は `EnumDisplayMonitors` の列挙順で 1 から振る。
- `primary` は `GetMonitorInfo` の `MONITORINFOF_PRIMARY` フラグで判定する。
- 座標とサイズは物理ピクセル（仮想デスクトップ座標）。

### 5.2 `list_windows`

- 入力: なし
- 出力: JSON テキスト。ウィンドウの配列（`EnumWindows` の順、つまり Z オーダーの手前から）

```json
[{ "id": 132456, "title": "Book1 - Excel", "app": "EXCEL.EXE",
   "x": 120, "y": 80, "width": 1600, "height": 900,
   "minimized": false, "focused": true }]
```

- `id` はウィンドウハンドル（HWND）の整数値。
- `app` はプロセスの実行ファイル名。取得できない場合は空文字。
- 次の条件をすべて満たすウィンドウだけを含める。
  - `IsWindowVisible` が真
  - タイトルが空でない
  - DWM でクロークされていない（`DWMWA_CLOAKED` が 0）。非表示の UWP ウィンドウを除くため
- 位置とサイズは `GetWindowRect` の値（物理ピクセル）。

### 5.3 `capture_monitor` / `capture_window` の共通出力

戻り値は次の2つのコンテンツ。

1. **画像**: JPEG（`image/jpeg`）
2. **テキスト**: 座標メタデータの JSON

```json
{ "source": "window:132456 Book1 - Excel",
  "originX": 120, "originY": 80,
  "originalWidth": 1600, "originalHeight": 900,
  "imageWidth": 1568, "imageHeight": 882, "scale": 0.98 }
```

- `source`: モニターなら `monitor:<id> <name>`、ウィンドウなら `window:<id> <title>`。
- `originX/Y`: 撮影範囲の左上の画面座標（物理ピクセル）。
- 変換式: **画面座標 = origin + 画像上の座標 ÷ scale**（`image_to_screen` で実装）。
- `scale` は縦横共通の値。四捨五入による縦横の誤差は 1px 未満なので許容する。

### 5.4 `capture_monitor`

- 入力: `monitor_id`（整数、省略可）。省略時はプライマリモニター。
- 処理: `list_monitors` で範囲を求め、`mss` でその範囲を撮影する。
- エラー: 存在しない `monitor_id` を指定した場合は、有効な id の一覧を含めて `CaptureError` を送出する。

### 5.5 `capture_window`

- 入力: `window_id`（整数）と `title`（文字列）のうち、**ちょうど一方**を指定する。
  - 両方を指定、またはどちらも未指定の場合はエラー。
- `title` で指定した場合は `select_window` で1つに絞る（§6.2）。
- 処理: `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` で撮影する。撮影範囲は `GetWindowRect` と一致させ、`origin` もこの左上とする。
- エラー:

| 状況 | メッセージの内容 |
|---|---|
| `window_id` のウィンドウが存在しない | 「`list_windows` で確認してください」 |
| ウィンドウが最小化中（`IsIconic`） | 「最小化中のため撮影できません。元に戻してから再実行してください」 |
| `PrintWindow` が失敗した | 失敗した旨と Win32 のエラー番号 |

### ツールの説明文

各ツールには、Claude が適切に呼び出せるような説明文を付ける。例えば `capture_monitor` には「ユーザーが画面・デスクトップ・今見ているものについて尋ねたときに使う」と書く。また、ウィンドウの撮影ではまず `title` を試し、候補が複数返ったら `window_id` で撮り直すよう促す。具体的な文言は実装計画で決める。

## 6. 処理の詳細

### 6.1 画像処理

- `fit_size`: `scale = min(1.0, max_edge / max(width, height))`。新しいサイズは `round(width * scale)`、`round(height * scale)` で、それぞれ最小 1。拡大はしない。
- 縮小には `Image.LANCZOS` を使う。
- JPEG は品質 85。入力が RGBA などの場合は RGB に変換してからエンコードする。

### 6.2 ウィンドウの選択（`select_window`）

1. 大文字小文字を区別せず、`title` を部分一致で含むウィンドウを集める。
2. 0 件: 「一致するウィンドウがありません。`list_windows` で確認してください」で `CaptureError` を送出する。
3. 1 件: そのウィンドウを返す。
4. 複数件: タイトルが完全一致（大文字小文字は区別しない）するウィンドウがちょうど1つあれば、それを返す。それ以外は候補（id とタイトル、最大 20 件）を列挙して `CaptureError` を送出する。

### 6.3 DPI

`main()` の冒頭、Win32 や mss を呼ぶ前に `enable_dpi_awareness()` を実行する。

- まず `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)` を試す。
- 失敗したら `SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)` にフォールバックする。

これで全 API の座標が物理ピクセルにそろう。

### 6.4 stdio の扱い

stdio サーバーなので、標準出力には MCP のメッセージ以外を書かない。ログは標準エラー出力に出す。

## 7. 既知の制限

- 最小化中のウィンドウは撮影できない。
- DRM で保護された内容（動画配信など）は黒く写ることがある。
- 管理者権限で動くウィンドウは、通常権限のサーバーからは撮影できない場合がある。
- `PrintWindow` が黒い画像を返すアプリが一部ある。MVP では代替手段（画面からの切り抜きなど）を実装しない。
- ウィンドウ画像には、`GetWindowRect` に含まれる見えない枠（数 px）が入ることがある。

## 8. テスト

### 自動テスト（pytest、Windows 非依存）

- `test_imaging.py`
  - `fit_size`: 長辺が上限超（横長・縦長）、ちょうど上限、上限未満（scale 1.0、拡大しない）
  - `image_to_screen`: origin とスケールの組み合わせで、期待する画面座標に戻ること
  - `encode_jpeg`: RGBA 入力でも JPEG バイト列（`FF D8` で始まる）を返すこと
  - `build_meta`: キー名と値が §5.3 と一致すること
- `test_matching.py`（`select_window`）
  - 0 件 → `CaptureError`
  - 1 件 → そのウィンドウ
  - 複数件のうち完全一致が1つ → そのウィンドウ
  - 複数件で完全一致なし → 候補を含む `CaptureError`
  - 大文字小文字の違いを無視すること

### 手動の受け入れテスト（Claude Code に登録して確認）

1. 「今の画面を見てアドバイスして」で `capture_monitor` が呼ばれ、画面の内容に基づいた回答が返る。
2. 「（起動中のアプリ名）のウィンドウを見て」で、他のウィンドウの裏に隠れていても撮影できる。
3. Chrome と VS Code のウィンドウが黒くならずに写る。
4. 表示スケール 125% / 150% の環境で、画像が切れたりずれたりしない。
5. （マルチモニター環境があれば）2 番目のモニターを指定して撮影できる。
6. 存在しないタイトルや複数該当するタイトルを指定すると、Claude がエラー内容を受けて `list_windows` や `window_id` 指定でリカバリーする。

## 9. 完了条件

- §8 の自動テストがすべて通る。
- §8 の手動テスト 1〜4（と、環境があれば 5・6）を確認済み。
- README に、セットアップ（`uv sync`）と `claude mcp add` での登録手順が書かれている。
