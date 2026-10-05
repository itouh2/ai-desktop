# ai-desktop: Claude が押すクリック（click）設計書

- 日付: 2026-10-05
- 状態: 設計承認済み・実装前
- 前提: [move_mouse](2026-10-05-move-mouse-design.md)、[汎用化](2026-10-05-generalize-design.md)、[ページのボタン](2026-10-03-page-buttons-design.md)

## 1. 目的

Claude が撮影画像の 1 点を自分で左クリックし、すぐ撮り直した結果を受け取れるようにする。

きっかけは RimWorld の案内（2026-10-05）。物や建物の正体を確かめるには、それをクリックして左下の情報を読む必要がある。今はユーザーに頼んで押してもらっており、手間がかかるうえ、Claude が見た目で判断して 2 回誤った（`notes/rimworld/README.md` の「ルールと注意」）。選ぶ・タブを開く・情報を読む、の確認のための左クリックを Claude に任せられるようにする。

ユーザーの依頼（要旨）:

1. 撮影画像の座標を指定して左クリックし、すぐ撮り直して結果を返す道具。`move_mouse` に「押す」を足した形
2. 注釈ページに「Claude に操作を任せる」の切り替えを置き、オンのときだけ押せる。対象は撮影中のウィンドウだけ
3. 1 回ごとに、何を押したかをチャットに書く。右クリックのメニューとドラッグは最初は入れない

## 2. 決定事項

| 項目 | 決定 | 理由 |
|---|---|---|
| クリックの種類 | 左クリックだけ。右クリック・ダブルクリック・ドラッグは次の段階 | ユーザーの選択（2026-10-05） |
| 許可の切り替え | ページの「Claude に操作を任せる」。始めはオフ。ユーザーが切るまでオン。ページ（タブ）をすべて閉じたら、また MCP が再起動したらオフ。オンの間は、どの表示でもユーザーが切れる | ユーザーの選択。何度も確かめる場面で手間がない |
| 守られたウィンドウ | Claude Code が動くアプリ（エディター・ターミナル・Claude アプリ）と注釈ページのブラウザは、許可がオンでも押さない（§2.1） | ユーザーの選択（2026-10-05）。Claude が自分の確認ダイアログを押せないようにする |
| 押せる対象 | ページに表示中の撮影と**同じウィンドウ**だけ。その新しい撮影の画像でも押せる。別のウィンドウ、モニター全体の撮影では押せない | ユーザーの選択。ユーザーが見ている対象と一致する |
| 方式 | 新しいツール `click` を足す（`move_mouse` に混ぜない）。許可の状態はビューアーが持つ | Claude Code のツール許可で `move_mouse` と `click` を分けて扱える |
| 何を押したかの記録 | `what`（何を押すかの短い説明）を必須の引数にする。結果に含め、ページにも直近の記録を出す。チャットへの記述はスキルと INSTRUCTIONS で指示する | チャットとページの両方に残る |
| 押したあとのフォーカス | 押したウィンドウを前面のままにする（操作前のウィンドウに戻さない） | 押した結果をユーザーがそのまま見て、続けて操作できる |
| 押したあとの待ち | `wait_seconds`（既定 0.5 秒）。0.3〜5 秒に丸める | 0.3 秒未満だとゲームがクリックを取りこぼす（2026-10-03 の実測。`viewer.AFTER_CLICK_SECONDS`） |
| カーソル | 撮り直したあと、元の位置に戻す | `move_mouse` と同じ。ユーザーのカーソルを置き去りにしない |

### 2.1 守られたウィンドウ（追加: 2026-10-05）

ページに表示するウィンドウを選ぶのは Claude なので、許可がオンのとき、Claude が Claude Code の画面（エディターやターミナル）を撮って表示すれば、Claude Code の許可ダイアログの「許可」を自分で押せてしまう。これは Claude Code の確認の仕組みを迂回する経路になる。

そのため `click` は、押す前に対象のウィンドウを `capture.list_windows()` で引き、次のどれかなら許可がオンでも拒否する。

- 実行ファイル名（`WindowInfo.app`、大文字小文字を区別しない）が次のどれか: `code.exe`、`code - insiders.exe`、`cursor.exe`、`windsurf.exe`、`windowsterminal.exe`、`openconsole.exe`、`conhost.exe`、`cmd.exe`、`powershell.exe`、`pwsh.exe`、`claude.exe`
- タイトルが注釈ページの接頭辞 `ai-desktop | ` で始まる（注釈ページのブラウザ）
- 一覧に見つからない（閉じた）

一覧は `server.py` の定数 `PROTECTED_APPS` に置く。ブラウザで動く Claude（claude.ai）や、一覧にない別のエディターは防げない（既知の制限として README に書く）。

## 3. スコープ

### 含める

- MCP ツール `click`（§5）
- ビューアーの許可の状態、操作の記録、ページからの切り替え要求（POST `/agent`）、SSE での配信（§4.2）
- ページの「Claude に操作を任せる」欄と、Claude が押した記録の表示（§4.3）
- `Pointer.at` の `return_focus` 引数（§4.1）
- テスト、実機確認スクリプト、README とスキルの更新（§7、§8）

### 含めない

- 右クリック、ダブルクリック、ドラッグ、スクロール、キー入力（次の段階。`inputs.py` に足す）
- ユーザーがマウスを操作中かどうかの検知
- 押す前のユーザーの都度確認（許可は切り替え 1 つ。Claude Code のツール許可で都度確認にもできる）
- `notes/` の更新（RimWorld の notes はユーザーの作業中なので触らない）

## 4. 構成

```text
click(capture_id, x, y, what, wait_seconds)                      ← server.py
  ├─ viewer.authorize_click(capture_id)        許可・対象の確認      ← viewer.py
  └─ pointer.at(capture_id, x, y, keep_clear="point", return_focus=False)  ← pointer.py
       ├─ viewer.authorize_click(capture_id)   押す直前にもう一度
       ├─ inputs.click(sx, sy)                 左クリック            ← inputs.py
       ├─ viewer.record_click(what)            ページに記録
       ├─ 待つ → 撮り直し                                            ← capture.py
       └─ 後片付け: カーソルを元へ（inputs.move）。フォーカスは戻さない

ページ（ブラウザ）
  「Claude に操作を任せる」☑ ── POST /agent {"enabled": true|false} ──→ viewer.set_agent()
  ←── SSE event: state {"state", "agent": {"enabled", "clicks": [...]}} ──
```

### 4.1 `pointer.py`（変更）

`Pointer.at(capture_id, x, y, keep_clear, return_focus=True)` に `return_focus` を足す。

- `True`（既定）: 今と同じ。後片付けで、操作前に前面だったウィンドウを前面に戻す
- `False`: 前面に戻さない。自分で最小化したブラウザは、今と同じく元に戻す

### 4.2 `viewer.py`（変更）

状態を 2 つ加える。どちらも `self._changed` の下で読み書きし、変わったら `_state_version` を進めて SSE で配る。

- `self._agent = False`: 「Claude に操作を任せる」
- `self._clicks: list[dict]`: Claude が押した記録。新しい順に最大 5 件。要素は `{"time": "HH:MM:SS", "what": "<what>"}`

加えるメソッド:

| メソッド | 中身 |
|---|---|
| `set_agent(enabled: bool)` | 許可を切り替える。ページから呼ばれる |
| `authorize_click(capture_id)` | 押してよいか確かめ、だめなら理由つきの `CaptureError`（§6） |
| `record_click(what)` | 記録の先頭に足し、5 件を超えた分を捨てる |

変えるメソッド:

- `unregister_client()`: 接続中のタブが 0 になったら `_agent = False`（ページを閉じたらオフ）
- `next_update()`: 状態の項目に `"agent": {"enabled": bool, "clicks": [...]}` を加える
- `publish()`: 表示内容に `"target": "window" | "monitor"`（撮影の対象の種類）を加える。ページはモニター撮影のとき切り替えを使えなくする

`authorize_click(capture_id)` の判定（この順）:

1. `_agent` がオフ → 拒否
2. 表示中のページがない → 拒否
3. `capture_id` の対象がモニター → 拒否
4. `capture_id` の対象のウィンドウが、表示中のページの撮影の対象と違う → 拒否

POST `/agent`（ページから）: 本文 `{"enabled": true|false}`。トークン・Origin・Host の確認は他の POST と同じ。`enabled` が真偽値でなければ 400。成功で `{"ok": true}`。

### 4.3 `annotate.py`（変更）

ページの左上に、常に出る欄 `#agent` を置く（右上は一時的な通知の `#status` が使う）。

- チェックボックス「Claude に操作を任せる（このウィンドウだけ・左クリック）」
- オンの間は欄の色を変え（オレンジ）、「操作を任せています」と出す
- Claude が押した記録（最大 5 件、`時刻 what`）。`textContent` で入れる（HTML として解釈しない）
- 表示中の撮影がモニター全体のときは「画面全体の撮影ではクリックを任せられません」と出し、許可がオフならチェックボックスを使えなくする。許可がオンの間は、どの表示でもチェックボックスを使える（ユーザーがいつでも切れるように）
- チェックボックスを変えると POST `/agent`。サーバーが返す状態（SSE）で表示を合わせる（複数のタブでも同じ表示になる）

### 4.4 `server.py`（変更）

ツール `click` を加える（§5）。守られたウィンドウの一覧 `PROTECTED_APPS` と、確かめる関数 `_ensure_clickable(window_id: int) -> None`（§2.1）を加える。INSTRUCTIONS に 1 文足す（§8）。

## 5. ツール仕様: `click`

```text
click(capture_id: str, x: float, y: float, what: str, wait_seconds: float = 0.5)
  -> [JPEG, JSON メタデータ]
```

- `capture_id`: 撮影の `captureId`。ページに表示中の撮影と同じウィンドウのもの
- `x`, `y`: その撮影画像のピクセル座標
- `what`: 何を押すかの短い説明（例: 「左下の研究卓を選ぶ」）。前後の空白を除いて 1〜60 文字。空・長すぎはエラー
- `wait_seconds`: 押してから撮り直すまでの待ち。0.3〜5 秒に丸める（範囲外はエラーにせず丸める）
- 戻り値: 撮り直した画像と、既存の撮影と同じメタデータ（新しい `captureId`）。メタデータに次を加える
  - `"clicked": {"x": <x>, "y": <y>, "captureId": "<元の captureId>", "what": "<what>"}`
- 送るのは左クリック 1 回（`inputs.click(sx, sy)`、`double=False`）だけ

手順:

1. `what` と `wait_seconds` を整える
2. `viewer.authorize_click(capture_id)`（だめなら何も動かさずにエラー）
3. `_ensure_clickable(target.id)`（守られたウィンドウなら何も動かさずにエラー）
4. `pointer.at(capture_id, x, y, keep_clear="point", return_focus=False)` の中で
   1. もう一度 `viewer.authorize_click(capture_id)`（前面化の間に切られた場合に備える）
   2. `inputs.click(*spot.screen)`
   3. `viewer.record_click(what)`
   4. `wait` 秒待つ
   5. 同じ対象を撮り直す
   6. 後片付け: カーソルを `inputs.move(*spot.cursor)` で戻す（失敗の途中でも戻す。戻すことの失敗で元のエラーを隠さない）

ツールの説明文（モデル向け）の要旨: 「ユーザーがページで『Claude に操作を任せる』をオンにしているときだけ、ページに表示中のウィンドウを左クリックする。何を押すかを `what` に書き、押したあと必ずチャットに何を押したかを書く。オフならエラーになるので、ユーザーに頼むか、押してもらう。」

## 6. エラー処理

すべて `CaptureError` を投げ、`_reported()` で `ToolError` にする。どれも、マウスを動かす前に止める（押す直前の 2 回目の確認で拒否された場合は、前面化のあと・押す前に止める）。

| 状況 | 文言 |
|---|---|
| 許可がオフ | 「ページで『Claude に操作を任せる』がオフです。押してほしいことをユーザーに伝えるか、オンにしてもらってください。」 |
| 表示中のページがない | 「表示中のページがありません。先に show_annotated で対象のウィンドウを表示してください。」 |
| モニター全体の撮影 | 「画面全体の撮影ではクリックできません。対象のウィンドウを capture_window で撮り、ページに表示してください。」 |
| 表示中と別のウィンドウ | 「クリックできるのは、ページに表示中のウィンドウだけです。」 |
| 守られたウィンドウ（§2.1） | 「このウィンドウ（<app>）は Claude には押させません。Claude Code が動くアプリと注釈ページは、ユーザーが押してください。」 |
| 対象のウィンドウが一覧にない | 「対象のウィンドウが見つかりません。撮影し直してください。」 |
| `what` が空・60 文字超 | 「what に、何を押すかを 1〜60 文字で書いてください。」 |
| 座標が画像の外、前面化の失敗、ブラウザ自身、別の操作が実行中 | `Pointer.at` の既存の文言 |
| 撮り直しの失敗 | 既存の撮影のエラー。カーソルは戻してから返す |

## 7. テスト

- `tests/test_pointer.py`: `return_focus=False` で、操作前のウィンドウを前面に戻さない（最小化したブラウザは戻す）
- `tests/test_viewer.py`:
  - `authorize_click` の 4 つの拒否と、許可されるとき（新しい撮影でも同じウィンドウなら許可）
  - `set_agent` と `record_click` で状態の版が進み、`next_update` の状態に `agent` が載る。記録は 5 件まで、新しい順
  - 最後のタブが閉じたら許可がオフになる
  - POST `/agent`: トークン・Origin の確認、`enabled` が真偽値でなければ 400、成功で許可が変わる
  - `publish` の表示内容に `target` が載る
- `tests/test_server.py`: `click` が
  - 許可されないとき、マウスを動かさずにエラー
  - 許可されたとき、画面の点を 1 回だけ左クリック（`double=False`）、待ち、撮り直し、カーソルを戻し、記録し、`clicked` を返す
  - 押す直前の確認で拒否されたら押さない
  - `what` の検査、`wait_seconds` を 0.3〜5 に丸める
  - 撮り直しに失敗してもカーソルを戻す
  - 操作前のウィンドウに前面を戻さない
  - 守られたウィンドウ（`PROTECTED_APPS` の各アプリ、`ai-desktop | ` で始まるタイトル）と、一覧にないウィンドウは、許可がオンでも押さない
  - ツールは 8 つ
- `tests/test_annotate.py`: ページに `#agent` 欄とチェックボックスがあり、記録は `textContent` で入れ、POST `/agent` を送る。モニター表示でもオンの間はチェックボックスを使える
- 実機確認 `scripts/e2e_click.py`（新規）: 試験用ウィンドウ（`scripts/click_target.py`）を撮ってページに表示し、ページと同じ要求で許可をオフ・オンにして `click` を呼ぶ。オフでは試験用ウィンドウのクリック数が増えないこと、オンでは 1 増えること、試験用ウィンドウが前面に残ること、カーソルが戻ることを確かめる

検証コマンド: `uv run --no-sync pytest -q`（全件 PASS）

## 8. ドキュメント

- `server.py` の INSTRUCTIONS: `click` の 1 文（ページで任されたときだけ、表示中のウィンドウを左クリックする。押すたびにチャットに何を押したかを書く）
- `README.md`: ツール一覧に `click`、既知の制限（左クリックだけ、許可はページ、表示中のウィンドウだけ）、実機確認のコマンド
- `.claude/skills/ai-desktop-guide/SKILL.md`: ツール数を 8 に、「Claude が押す」節を加える（許可の頼み方、`what` の書き方、チャットへの記述、押したあとの確かめ方、オフのときはユーザーに押してもらう）。§4 の「クリックはしない」の注意を `click` への案内に直す
- `.claude/skills/ai-desktop-guide/references/playbook-game.md`: 「物の正体はクリックして確かめる。任されていれば `click`、なければユーザーに頼む」を 1 行

## 9. 実装の順番（計画の目安）

1. `Pointer.at` の `return_focus`
2. ビューアーの許可と記録（状態、`authorize_click`、`record_click`、POST `/agent`、SSE、`target`）
3. ページの「Claude に操作を任せる」欄
4. `click` ツール
5. 実機確認スクリプト
6. ドキュメントとスキル

## 10. 将来の検討事項

- 右クリック（メニュー）、ダブルクリック、ドラッグ（範囲指定・ゾーン）、キー入力
- 押す範囲を、ページで指定した枠の中だけに絞る
- ユーザーがマウスを操作中なら押さない検知
- 許可の自動オフ（一定時間）を選べるようにする
