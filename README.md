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

登録後、Claude Code のセッションを開き直すとツールが使えるようになります。初回は Claude Code の許可確認が出ます（「常に許可」を選ぶと、以降は確認なしで撮影されます）。
ツールを追加・更新したあとは、Claude Code のセッションを開き直すと反映されます。

## 使い方の例

- 「今の画面を見てアドバイスして」
- 「Excel のウィンドウを見て、この表の改善点を教えて」
- 「2番目のモニターに何が映ってる？」
- 「どこを押せばいいか、画面に印をつけて見せて」（注釈付きのスクショがブラウザに表示されます。ページ上をクリックすると実際の画面もクリックされます）

## ツール

| ツール | 内容 |
|---|---|
| `list_monitors` | モニター一覧（id・名前・プライマリか・位置とサイズ） |
| `list_windows` | 表示中のウィンドウ一覧（最小化中も含む。id・タイトル・アプリ・位置とサイズ・最小化中か・アクティブか） |
| `capture_monitor` | モニター全体を撮影（省略時はプライマリ） |
| `capture_window` | ウィンドウを撮影（`window_id` か `title` の部分一致） |
| `show_annotated` | 撮影画像を背景に、Claude が書いた枠・番号・吹き出し・矢印を重ねてブラウザに表示する（撮影メタデータの `captureId` を `capture_id` に指定）。開いているタブは使い回す。ページ上のクリック・ダブルクリックは実際の画面に伝わる（ページは更新されず、注釈は残る） |

撮影結果は JPEG（長辺 1568px 以下）と座標メタデータです。画面座標 = `origin + 画像上の座標 ÷ scale`（物理ピクセル）。

## 既知の制限

- 最小化中のウィンドウは撮影できません。
- DRM 保護された内容は黒く写ることがあります。
- 管理者権限で動いているウィンドウは撮影できない場合があります。
- スクショはディスクに保存しません。注釈ページは MCP サーバー内の Web サーバー（127.0.0.1 のみ）から配信され、Claude Code のセッションが終わると表示できなくなります。
- 画面全体の撮影でクリック位置がブラウザと重なるときは、ブラウザを一時的に最小化してから実際の画面をクリックします。ビューアーのタブと同じブラウザのウィンドウにある別のタブは操作できません（対象のタブは別ウィンドウに分けてください）。
- ウィンドウを前面に出すために Alt キーを一瞬押すので、まれにアプリのメニューバーが反応することがあります。
- 管理者権限で動いているアプリは、ページからクリックできません。
- `show_annotated` のページは外部からの読み込みを遮断していますが、ページ移動（`<meta http-equiv="refresh">` など）は防げません。画面に怪しい指示が映っているときは注意してください。

## 実機の動作確認

```powershell
uv run python scripts/smoke.py   # smoke-out/ に monitor.png と window.png を保存
uv run python scripts/control_smoke.py   # クリック・前面化・最小化の確認（試験用ウィンドウが開きます）
uv run python scripts/e2e_viewer.py      # タブの再利用とページ経由のクリックの確認（ブラウザのタブが開きます）
```

設計の詳細は [docs/superpowers/specs/2026-10-03-desktop-vision-mcp-design.md](docs/superpowers/specs/2026-10-03-desktop-vision-mcp-design.md) を参照してください。
