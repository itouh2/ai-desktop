# ai-desktop: Claude が動かすマウス移動（move_mouse）設計書

- 日付: 2026-10-05
- 状態: 設計承認済み・実装前
- 前提: [ビューアーのクリック連動](2026-10-03-viewer-click-design.md)、[ページのボタン](2026-10-03-page-buttons-design.md)

## 1. 目的

Claude が自分でマウスカーソルを画面の 1 点へ動かし、その状態を撮影できるようにする。カーソルを乗せたときにだけ出る説明文（ツールチップ、状態アイコンの説明、ゲームの敵の意図など）を読むのが主な用途。

きっかけ: Slay the Spire 2 の助言セッション（2026-10-04〜05）で、状態アイコンや敵の意図の説明文が読めず、被ダメージの見積もりを誤った（[docs/games/slay-the-spire2](../../games/slay-the-spire2/README.md)）。ただしツールはゲーム専用にせず、どのアプリにも使える汎用の機能にする。将来はクリック、ドラッグ、スクロール、キー入力へ広げる。

## 2. スコープ

### 含める

- MCP ツール `move_mouse`: 撮影画像の 1 点へカーソルを移動し、待ってから同じ対象を撮り直す（§5）
- マウスとキーの送信をまとめた新モジュール `inputs.py`（§4.1）
- 画面の 1 点を操作する前後の準備と後片付けをまとめた新モジュール `pointer.py`。既存のクリック中継（`Viewer.perform_click`）もこれを使うようにする（§4.2）
- テスト、実機確認スクリプト、ドキュメントとスキルの更新（§7、§8）

### 含めない

- Claude 自身のクリック、ドラッグ、スクロール、キー入力（次の段階。`inputs.py` に足す形で作る）
- 1 回の呼び出しで複数の点を巡回すること（1 回 1 点。必要なら繰り返し呼ぶ）
- 撮影範囲の切り抜き（毎回、対象全体を撮る）
- 「ユーザーが操作中なら止める」検知（将来の検討事項。§10）

## 3. 決定事項

| 項目 | 決定 | 理由 |
|---|---|---|
| 最初の段階の範囲 | 移動＋撮影まで。クリックはしない | ホバーの説明文を読む目的に足り、誤操作の心配がない |
| 動かしてよいとき | Claude Code のツール許可に任せる | ユーザーの判断（2026-10-05） |
| 戻り値 | 1 点につき対象全体を 1 枚（既存の撮影と同じ形） | 説明文がどこに出ても取りこぼさない。そのまま `show_annotated` に使える |
| 入力の送信方式 | 既存の Win32 `SendInput` を広げる（PyAutoGUI は不採用） | §3.1 |
| 移動の送り方 | `SendInput` の絶対座標の移動イベント（`SetCursorPos` ではない） | 実際のマウス入力と同じ経路で届き、アプリがカーソルの乗りを検知しやすい |
| モジュール名 | `inputs.py`（`input.py` ではない） | 組み込みの `input` を隠さないため |

### 3.1 PyAutoGUI を採用しない理由

ユーザーの依頼で検討した（2026-10-05）。

- 公式 FAQ で「プライマリモニターしか扱えない」とされている。前回の Slay the Spire 2 はサブモニター（x=3900 付近）にあり、そのままでは正しく動かない恐れがある
- Windows では import 時に `SetProcessDPIAware()` を呼ぶ。ai-desktop の `enable_dpi_awareness()` と設定がぶつかる恐れがある
- 既定で FAILSAFE（画面の角で例外）と PAUSE（操作ごとに 0.1 秒）が付き、依存も増える（pyscreeze、pymsgbox など）
- 今回の範囲（移動＋撮影）では、PyAutoGUI を使う利点がない

将来、高水準の操作（なめらかな移動、文字列の入力など）が欲しくなり、複数モニターの問題が解決していれば、`inputs.py` の中身だけを差し替えて採用を検討する。pynput（仮想デスクトップ座標に対応、入力の監視ができる）も候補。

## 4. 構成

```text
move_mouse(capture_id, x, y, wait_seconds, restore_cursor)      ← server.py
  └─ Pointer.at(capture_id, x, y, keep_clear="capture")          ← pointer.py
       ├─ 排他ロック、範囲チェック、ブラウザ自身の拒否
       ├─ 対象の前面化、画面座標への変換、ブラウザの最小化
       ├─ inputs.move(sx, sy) → 待つ → 撮り直し                  ← inputs.py / capture.py
       └─ 後片付け: カーソル（inputs.move で元の位置へ）、ブラウザ

ページからのクリック（既存）
  Viewer.perform_click
  └─ Pointer.at(capture_id, x, y, keep_clear="point")
       └─ control.click → inputs.click
```

### 4.1 `inputs.py`（新規）: マウスとキーの送信

- `control.py` から移すもの: `MOUSEINPUT` などの構造体、`_user32.SendInput` の宣言、`_mouse_at`、`_key`、`_send`、関連する定数
- 公開する関数
  - `move(x, y)`: 物理ピクセルの絶対座標へ移動する。`MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK` のみで、ボタンのフラグは付けない
  - `click(x, y, double=False)`: 今の `control.click` をそのまま移す
  - `tap_alt()`: 前面化で使う Alt の押下と解放（今の `bring_to_front` の中の処理）
- 送信に失敗したら、今と同じく `CaptureError`（「入力を送れませんでした（Win32 エラー N）。」）

### 4.2 `pointer.py`（新規）: 1 点を操作する前後の処理

`Viewer.perform_click` の準備と後片付けを切り出す。

```python
class Pointer:
    def __init__(self, store: CaptureStore, control: Any, settle_seconds: float = SETTLE_SECONDS): ...

    @contextmanager
    def at(self, capture_id: str, x: float, y: float, keep_clear: Literal["point", "capture"]) -> Iterator[tuple[int, int]]:
        ...
```

`at` の手順:

1. 排他ロックを取る（取れなければ「ほかの操作を実行中です。終わるまで待ってください。」）
2. 撮影のメタデータを読み、(x, y) が画像内か確かめる（外なら「位置が画像の外です。」）
3. ビューアーのブラウザを探す。対象がウィンドウで、それがブラウザ自身なら拒否する（今のクリックと同じ文言）
4. カーソルの元の位置を覚える
5. 対象がウィンドウなら前面化し（失敗なら「対象のウィンドウを前面に出せませんでした。」）、現在位置から画面座標を求める（`image_to_screen`）
6. 対象がモニターでブラウザがあるとき、`keep_clear` に応じてブラウザを最小化する
   - `"point"`: 画面座標がブラウザの枠内のときだけ（今のクリックと同じ）
   - `"capture"`: ブラウザが撮影範囲（`originX`〜`originX+originalWidth` など）に重なるとき（今の撮り直しと同じ判定）
   - 最小化できなければ「ブラウザを最小化できなかったため、操作しませんでした。」
7. 画面座標と元のカーソル位置を持つ `Spot` を `yield` する
8. 後片付け（例外でも必ず）: ブラウザを元に戻してロックを外す。カーソルは戻さない（呼び出し側の役目）

カーソルを戻す処理は、呼び出し側で行う。クリックは今どおり `control.set_cursor` で戻し、`move_mouse` は `inputs.move` で戻す（アプリにカーソルが離れたことを伝え、説明文を閉じさせるため）。`Spot` は小さなデータクラス（`screen: tuple[int, int]`、`cursor: tuple[int, int]`）。

```python
with pointer.at(capture_id, x, y, keep_clear="capture") as spot:
    spot.screen  # (sx, sy)
    spot.cursor  # 元の位置
```

ロックは `Viewer` と `move_mouse` で共有する（`Viewer` は `Pointer` を受け取り、その `at` を使う）。

### 4.3 `control.py`（変更）

- ウィンドウ操作だけを残す: `find_window`、`foreground_window`、`window_origin`、`window_rect`、`bring_to_front`、`minimize`、`is_minimized`、`restore`、`cursor_pos`
- `click` と `set_cursor` は名前を残し、中身は `inputs` に任せる（`Viewer` とテスト用の偽物の形を変えない）
- `bring_to_front` の Alt 押しは `inputs.tap_alt()` を使う

## 5. ツール仕様: `move_mouse`

```text
move_mouse(capture_id: str, x: float, y: float, wait_seconds: float = 0.5, restore_cursor: bool = True)
  -> [JPEG, JSON メタデータ]
```

- `capture_id`: 撮影の `captureId`（直近 10 件）
- `x`, `y`: その撮影画像のピクセル座標（`imageWidth × imageHeight`）
- `wait_seconds`: 移動後、撮影までの待ち時間。0〜5 秒に丸める（範囲外はエラーにせず丸める）
- `restore_cursor`: `True`（既定）なら撮影後にカーソルを元の位置へ戻す。`False` なら移動先に置いたまま
- 戻り値: 撮り直した画像と、既存の撮影と同じメタデータ（新しい `captureId` 付き）。メタデータに次を加える
  - `"hover": {"x": <x>, "y": <y>, "captureId": "<元の captureId>"}`
  - `"cursorRestored": true | false`
- **クリックや押下のイベントは一切送らない**

ツールの説明文（モデル向け）の要旨: 「カーソルを乗せたときだけ出る説明文やホバー表示を読みたいときに使う。クリックはしない。ユーザーのマウスを数秒動かすので、ユーザーが操作していないときに使う。」

## 6. エラー処理

| 状況 | 動き |
|---|---|
| `captureId` が古い・存在しない | 既存の `CaptureStore` のメッセージ |
| 座標が画像の外 | 「位置が画像の外です。」マウスは動かさない |
| 対象がビューアーのブラウザ自身 | 拒否（既存の文言） |
| 対象ウィンドウが閉じた・最小化中・前面化に失敗 | 動かす前に止め、理由を返す |
| ブラウザを最小化できない | 撮影せずに止める |
| ページからのクリックなど、別の操作が実行中 | 「ほかの操作を実行中です。」待たない |
| 移動・待ち・撮影の途中で失敗 | カーソル（`restore_cursor=True` のとき）とブラウザを必ず戻してからエラーを返す |

すべて `CaptureError` を投げ、`server.py` の `_reported()` で `ToolError` に変える（既存の流儀）。

## 7. テスト

- `tests/test_inputs.py`（新規）: `SendInput` を偽物に差し替え、送られる構造体を確かめる
  - `move`: 1 イベント、絶対座標・仮想デスクトップ・移動のフラグのみ、ボタンのフラグなし。仮想デスクトップの左上が負の座標でも正しく正規化される
  - `click`: 今のクリックのイベント列と同じ
  - 送信数が足りないと `CaptureError`
- `tests/test_pointer.py`（新規）: 偽の control で `Pointer.at` を確かめる
  - ウィンドウ対象: 前面化してから現在位置で座標変換する
  - モニター対象: `keep_clear="point"` はブラウザ内の点だけ最小化、`"capture"` は撮影範囲に重なれば最小化
  - 範囲外、ブラウザ自身、前面化失敗、最小化失敗はそれぞれのエラー
  - 例外でもブラウザを戻し、ロックを外す。同時に 2 つは走らない
- `tests/test_viewer.py`（更新）: クリックの既存テストが `Pointer` 経由でも通る。前後処理の細かいテストは `test_pointer.py` へ移す
- `tests/test_server.py`（更新）: ツール数を 7 にする（今の 6 つ＋`move_mouse`）。`move_mouse` が移動 → 待ち → 撮り直しを行い、戻り値に新しい `captureId` と `hover`、`cursorRestored` がある。`restore_cursor=False` で戻さない。`wait_seconds` を丸める。クリックが一度も呼ばれない
- 実機確認 `scripts/e2e_move_mouse.py`（新規）: 実際の MCP サーバーを stdio で起動し、tkinter の試験ウィンドウ（カーソルが乗ると表示文字が変わる）に `move_mouse` を呼ぶ。撮影に変わった文字が写ること、カーソルが元に戻ることを確かめる。サブモニターがあれば、そちらでも 1 回確かめる
- 手動確認: Slay the Spire 2 で状態アイコンの説明文が写るか、ユーザーと一緒に確かめ、適切な `wait_seconds` を記録する

検証コマンド: `uv run --no-sync pytest -q`（全件 PASS）

## 8. ドキュメント

- `server.py` の `INSTRUCTIONS`: `move_mouse` の 1 文を足す（説明文を読みたいときに使う、クリックしない、ユーザーの操作中は避ける）
- `README.md`: ツール一覧に `move_mouse` を加える
- `.claude/skills/ai-desktop-guide/SKILL.md`: 「説明文を読む」手順を短く足す
- `docs/games/slay-the-spire2/README.md`: 実務メモに「状態アイコンや敵の意図は `move_mouse` で説明文を読む」を足す

## 9. 実装の順番（計画の目安）

1. `inputs.py` を作り、`control.py` から送信処理を移す（動作は変えない）
2. `pointer.py` を作り、`Viewer.perform_click` を `Pointer` 経由にする（動作は変えない）
3. `move_mouse` ツールを加える
4. 実機確認スクリプトとドキュメント

1 と 2 は振る舞いを変えない作り直しなので、既存のテストが全件 PASS のまま進める。

## 10. 将来の検討事項

- クリック、ドラッグ、スクロール、キー入力のツール（`inputs.py` に足す）
- ユーザーが直前にマウスを動かしていたら止める検知（pynput の監視、または `GetLastInputInfo`）
- 複数の点をまとめて巡回するツール
- PyAutoGUI / pynput への差し替え（§3.1）
- 既知の制限: ウィンドウ撮影（PrintWindow）は、別ウィンドウとして出るツールチップを写さない。一般的な Windows アプリではモニター撮影の画像に対して `move_mouse` を使う（README とスキルに記載）。必要になれば、`move_mouse` にウィンドウ対象でもモニター範囲で撮る選択肢を足す
