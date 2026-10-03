# ai-desktop: 注釈付きスクショ表示 設計書

- 日付: 2026-10-03
- 状態: 設計承認済み・実装前
- 前提: [デスクトップ撮影 MCP サーバー（MVP）](2026-10-03-desktop-vision-mcp-design.md)

## 1. 目的

Claude が撮影したスクショを背景にし、その上に Claude が書いた HTML（枠・番号・吹き出し・矢印など）を重ねて、既定のブラウザで表示する。「このボタンを押してください」「ここを直すと良い」といったアドバイスを、画面上の位置で示せるようにする。

透明なオーバーレイウィンドウを画面に直接重ねる方式は採らない。クリックの素通りや映り込みの扱いが複雑なためで、普通のブラウザのタブに表示する。

## 2. スコープ

### 含める

- 撮影結果に `captureId` を付け、直近の撮影をサーバーのメモリに保持する
- 新しいツール `show_annotated`：指定した撮影画像を背景にして HTML を重ねたページを作り、既定のブラウザで開く
- 見た目をそろえるための部品クラス（`.box`、`.badge`、`.note`、`.arrow`）

### 含めない

- 透明オーバーレイ、画面上への直接描画
- ページ上での操作（クリック・入力の受け付け）、JavaScript による動き
- 専用ビューアーウィンドウ、VS Code 内での表示
- ページの共有やアップロード

## 3. 決定事項

| 項目 | 決定 | 理由 |
|---|---|---|
| 表示先 | 既定のブラウザの新しいタブ | 追加の依存がなく、拡大や保存もブラウザの機能でできる |
| ページの置き場所 | 一時フォルダに HTML ファイルを書く | ユーザーの判断で「ディスクに保存しない」方針の縛りは外した。Web サーバーを持つより単純で、あとから見返せる |
| 注釈の書き方 | 自由な HTML＋部品クラス | 表現の自由度と見た目の統一を両立する |

## 4. 構成

```
capture_monitor / capture_window
   └─ 撮影画像を JPEG（品質 90、元の解像度）にして CaptureStore に保存 → captureId を発行
      メタデータに captureId を追加して返す

show_annotated(capture_id, html, title)
   ├─ CaptureStore から背景画像とメタデータを取得
   ├─ annotate.render_page で 1 ファイル完結の HTML を生成
   ├─ annotate.save_page で一時フォルダに保存（古いものを削除）
   └─ annotate.open_in_browser で既定のブラウザで開く
```

### ファイル

| パス | 責務 |
|---|---|
| `src/ai_desktop/captures.py`（新規） | `CaptureStore`：直近の撮影をメモリに保持する。Windows 非依存 |
| `src/ai_desktop/annotate.py`（新規） | ページの生成・保存・ブラウザ起動。`render_page` と `save_page` は Windows 非依存 |
| `src/ai_desktop/server.py`（変更） | `captureId` の付与、`show_annotated` ツール、サーバー説明文の更新 |
| `tests/test_captures.py`（新規） | `CaptureStore` |
| `tests/test_annotate.py`（新規） | ページ生成と保存 |
| `tests/test_server.py`（変更） | `captureId`、`show_annotated` |
| `README.md`（変更） | 新ツールと一時フォルダへの保存の説明 |

## 5. 詳細

### 5.1 CaptureStore

- `add(background_jpeg: bytes, meta: dict) -> str`：`c1`、`c2`… と連番の id を発行して保存する。保持は直近 **10 件**で、超えたら古いものから捨てる。
- `get(capture_id) -> (bytes, dict)`：見つからなければ `CaptureError` を送出する。メッセージには、保持中の id 一覧と「撮影し直してください」という案内を含める。
- MCP のツールはワーカースレッドで並行に動くことがあるので、内部はロックで守る。
- 背景はデコード済みの画像ではなく、JPEG のバイト列で持つ。3840×2560 の画像をデコードしたまま持つと 1 枚約 29MB になるが、JPEG なら 1〜2MB で済む。

### 5.2 撮影結果のメタデータ

既存のキーに `captureId` を追加する。

```json
{ "source": "window:132456 Book1 - Excel", "originX": 120, "originY": 80,
  "originalWidth": 1600, "originalHeight": 900,
  "imageWidth": 1568, "imageHeight": 882, "scale": 0.98, "captureId": "c3" }
```

### 5.3 show_annotated ツール

- 入力
  - `capture_id`（必須）
  - `html`（必須。空白だけは不可、最大 100,000 文字）
  - `title`（省略可。省略時はメタデータの `source`）
- 出力: テキスト「ブラウザで表示しました: <ファイルパス>」
- エラー（`ToolError`）: html が空、html が長すぎる、`capture_id` が見つからない
- 注釈の座標系: その撮影の**縮小画像のピクセル座標**（`imageWidth × imageHeight`）。Claude が見ている画像の座標をそのまま使え、換算は要らない。

### 5.4 ページの構造

1 つで完結する HTML ファイルにする。背景画像は base64 で埋め込む。

- `#stage`：幅 `imageWidth`px × 高さ `imageHeight`px の枠
  - `#shot`：背景画像（元の解像度）。枠いっぱいに表示するので、高 DPI の画面でもくっきり見える
  - `#annotations`：Claude の HTML をそのまま入れる層
- ブラウザの幅に合わせて `#stage` 全体を CSS の `transform: scale()` で拡大縮小する。そのための小さなスクリプト（ナンス付き）だけを埋め込む。枠ごと拡大縮小するので、注釈の位置はずれない。
- SVG の矢印用に、`id="arrowhead"` の矢じりマーカーを定義しておく。

### 5.5 部品クラス

| クラス | 見た目 | 位置の指定 |
|---|---|---|
| `.box` | 赤い角丸の枠 | `left`/`top`/`width`/`height`（style） |
| `.badge` | 赤い丸に白い数字 | `left`/`top` は**丸の中心** |
| `.note` | 白い吹き出し（左に赤い線） | `left`/`top`（左上） |
| `.arrow` | 赤い矢印線（SVG の `line`/`path` に付ける） | `<svg class="layer">` の中で画像座標を使う |

`<svg class="layer">` は `#stage` 全体を覆う SVG で、中の座標はそのまま画像のピクセル座標になる。

### 5.6 セキュリティ

Claude が生成した HTML をそのまま表示するので、ページに CSP（Content-Security-Policy）を入れる。

```
default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-<毎回ランダム>'
```

- 外部からの読み込み（画像・フォント・スクリプト）はすべて遮断する。ただし CSP ではページ移動は止められないため、Claude の HTML に `<meta http-equiv="refresh">` などが含まれると、開いた時点で外部 URL へ移動しうる（§7）。
- Claude の HTML に含まれる `<script>` は、ナンスがないので実行されない。
- `title` は HTML エスケープする。

### 5.7 ファイルの保存

- 保存先: `%TEMP%\ai-desktop\annotations\`
- ファイル名: `annotated-YYYYMMDD-HHMMSS-ffffff-<ランダム6桁>.html`
- 保持: 新しい順に **30 件**。保存のたびに、それより古いものを削除する。
- ブラウザで開くのは `os.startfile`（.html に関連付いた既定のブラウザ）。

**プライバシー**: このページにはスクショが埋め込まれるため、一時フォルダにスクショ入りのファイルが最大 30 件残る。MVP の「スクショをディスクに保存しない」方針は、`show_annotated` についてのみ外す（ユーザー承認済み）。撮影ツール自体は今までどおりディスクに書かない。

## 6. テスト

### 自動テスト（pytest）

- `test_captures.py`：連番の id、取り出し、11 件目で最古が消えること、未知の id のエラー（保持中の id を含む）
- `test_annotate.py`：
  - CSP とナンス付きスクリプトが入っていること
  - `#stage` のサイズが画像サイズと一致すること
  - 背景が data URI で埋め込まれていること
  - Claude の HTML がそのまま入り、`title` はエスケープされること
  - 保存で古いファイルが削除され、指定件数だけ残ること
- `test_server.py`：
  - 撮影結果のメタデータに `captureId` が入ること
  - ツールが 5 つになること
  - `show_annotated` がファイルを書いてブラウザを開くこと（ブラウザ起動は差し替える）
  - 未知の `capture_id`、空の html がエラーになること

### 実機確認

`claude -p` で、撮影 → `show_annotated` の流れを実行する。開いたブラウザのウィンドウを `capture_window` で撮り、枠や番号が狙った位置に重なっていることを目で確認する。最後に、ユーザーが VS Code の Claude Code から試す。

## 7. 既知の制限

- ページは静的。スクリプトを使った動きやクリック操作はできない。
- `.html` の関連付けが既定のブラウザ以外になっている環境では、そのアプリで開く。
- 撮影から 10 件以上あとでは、古い `captureId` は使えない（撮り直しが必要）。
- 注釈 HTML に `<meta http-equiv="refresh">`、`<link rel="dns-prefetch">`、`<form>`、リンクなどが含まれると、外部へのページ移動や DNS 問い合わせが起こりうる。URL に含めた文字列（画面から読み取った内容など）が外部に送られる経路になるため、画面上の指示（プロンプトインジェクション）に注意する。2026-10-03 のレビューで指摘、ユーザー判断で今回は未対応。
