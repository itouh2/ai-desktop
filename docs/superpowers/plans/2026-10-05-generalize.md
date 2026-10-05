# ai-desktop 汎用化（道具・使い方・知見の分離）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ai-desktop をどのゲーム・アプリにも使える形にする。MCP に「更新」ボタンの常設・`html` の省略・撮影 20 件保持を加え、MCP の登録をこのフォルダに移し、スキルを汎用に書き直し、STS2 の知見を `notes/` に移して層を整える。

**Architecture:** 道具（`src/ai_desktop/`、MCP）・使い方（`.claude/skills/ai-desktop-guide/`）・知見（`notes/<アプリ>/`）の 3 層に分ける。MCP は知見を扱わない。「更新」はページ（`annotate.py`）のボタン → `POST /refresh` → `Viewer.refresh()` → 待っている `wait_for_message` が `via: "refresh"` と撮り直し画像を返す、という既存のボタンと同じ経路で届く。

**Tech Stack:** Python 3.11+ / uv / mcp 2.x（`MCPServer`）/ pytest / 標準ライブラリの HTTP サーバーと SSE / Markdown

**Spec:** `docs/superpowers/specs/2026-10-05-generalize-design.md`

## Global Constraints

- 新しい依存を加えない（`pyproject.toml` の `dependencies` を変えない）
- ユーザー向けの文言は日本語、docstring とコメントは英語（既存に合わせる）
- 入力の検査で返すエラーは `ToolError`（server）または `CaptureError`（viewer。server の `_reported()` で `ToolError` に変わる）
- 「更新」の返事は `{"message": "", "via": "refresh"}`。ボタン名「更新」は予約（`buttons` に入れたら `ToolError`「「更新」はページに常に出ているので、buttons に入れないでください。」）
- 撮影の保持数は 20（`CAPTURE_LIMIT = 20`）
- `.mcp.json` は ai-desktop だけ、args は `["run", "--no-sync", "--directory", "C:/Works/2026/ai-desktop", "ai-desktop"]`
- スキルと notes の中の notes へのパスは相対（`notes/...`）。`docs/games` への参照を残さない（`docs/superpowers/` の古い設計書・計画は除く）
- `SKILL.md` にゲーム固有の語（HP、ターン、カード、敵、レリック、ポーション、デッキ）を書かない
- 知見の移し替えで内容を削らない。重複は 1 か所にまとめる
- テスト: `uv run --no-sync pytest -q`。開始時 151 件。各タスクの終わりで全件 PASS
- コミットメッセージの末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- MCP サーバーのコード変更は、Claude Code の MCP 再接続とビューアーのタブの開き直しまで、動いているセッションには反映されない

## Review Focus

1. 「更新」を続けて 2 回押す（1 回目を Claude が処理中）: 2 回目は「待ち受けていません」で断る。次の待ち受けでまた押せる → Task 2 `test_a_second_refresh_before_the_next_wait_is_refused`
2. 待ち受け中に Claude が入口のないページ（終わりの表示）に替えた: 待ちは `None` で終わり、古い画面からの「更新」は断る → Task 2 `test_refresh_after_the_page_lost_its_inputs_is_refused`
3. Claude が `buttons` に前後の空白付きの「 更新 」を入れる: 予約名として断る → Task 2 `test_show_annotated_rejects_the_reserved_refresh_label`（`" 更新 "` を含む）
4. `html` を引数ごと省く（キーがない）: 空文字と同じく、注釈のないページを出す → Task 1 `test_show_annotated_accepts_empty_or_missing_html`（`{}` を含む）
5. トークン違い・別オリジン（古いタブや他のサイト）からの `/refresh`: 403 → Task 2 `test_refresh_endpoint_checks_auth_and_state`

---

## ファイル構成

| ファイル | 役割 | タスク |
|---|---|---|
| `src/ai_desktop/captures.py` | `CAPTURE_LIMIT = 20` | 1 |
| `src/ai_desktop/server.py` | `html` の省略、予約名、説明文、`INSTRUCTIONS` | 1, 2 |
| `src/ai_desktop/annotate.py` | `REFRESH_LABEL`、「更新」ボタン（HTML・CSS・JS） | 2 |
| `src/ai_desktop/viewer.py` | `Viewer.refresh()`、`/refresh`、コメント | 2 |
| `scripts/e2e_viewer.py` | 実機での「更新」と `html` 省略の確認 | 2（実行は 6） |
| `tests/test_captures.py`、`tests/test_server.py`、`tests/test_viewer.py`、`tests/test_annotate.py` | 上の自動テスト | 1, 2 |
| `.mcp.json`（新規）、`tests/test_project_config.py`（新規） | このフォルダだけの MCP 登録 | 3 |
| `README.md` | ツール一覧、登録手順、notes の案内 | 1, 2, 3, 5 |
| `.claude/skills/ai-desktop-guide/SKILL.md`、`references/playbook-game.md`・`playbook-app.md`・`notes-format.md`（新規） | 汎用のスキルと手引き | 4 |
| `notes/`（新規。`docs/games/slay-the-spire2/` から移す） | 知見 | 5 |
| メモリー（`~/.claude/projects/c--Works-2026-ai-desktop/memory/`） | 「更新」の扱い | 6 |

---

### Task 1: 撮影を 20 件保持し、`html` を省略できるようにする

**Files:**
- Modify: `src/ai_desktop/captures.py:12`
- Modify: `src/ai_desktop/server.py`（`show_annotated` の引数・説明文・空チェック、`move_mouse` の説明文、`INSTRUCTIONS` の最後の文）
- Modify: `README.md`（ツール一覧の `show_annotated` の行）
- Test: `tests/test_captures.py`、`tests/test_server.py`

**Interfaces:**
- Produces: `show_annotated(capture_id: str, html: str = "", title: str | None = None, explanation: str | None = None, buttons: list[str] | None = None, message_box: bool = False) -> str`。`CAPTURE_LIMIT = 20`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_captures.py` に足す:

```python
def test_default_limit_keeps_the_latest_20():
    store = CaptureStore()
    ids = [store.add(bytes([i]), {}) for i in range(21)]
    with pytest.raises(CaptureError):
        store.get(ids[0])
    assert store.get(ids[1])[1] == {"captureId": "c2"}
```

`tests/test_server.py` の `test_show_annotated_rejects_empty_html` を消して、次に置き換える:

```python
@pytest.mark.parametrize("arguments", [{"html": ""}, {"html": "   "}, {}])
def test_show_annotated_accepts_empty_or_missing_html(viewer, arguments):
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", **arguments})
    assert not result.is_error
    assert [html for _, html, _ in viewer.published] == [arguments.get("html", "")]


def test_tool_descriptions_say_20_captures_are_kept():
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    descriptions = {tool.name: tool.description for tool in asyncio.run(run()).tools}
    for name in ("show_annotated", "move_mouse"):
        assert "the latest 20 are kept" in descriptions[name]
```

`test_instructions_are_one_paragraph` に `assert "html may be omitted" in server.INSTRUCTIONS` を足す。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest -q tests/test_captures.py tests/test_server.py`
Expected: 上の新しいテストが FAIL（「html が空です」、`latest 10`、20 件目の追い出し）

- [ ] **Step 3: 実装する**

- `captures.py`: `CAPTURE_LIMIT = 20`
- `server.py`: `show_annotated` の `html` を `html: str = ""` にし、空チェック（「html が空です」）を消す。長さの上限はそのまま。説明文の `html` の項に `Omit it (or pass "") for a page with no annotations, e.g. to end a conversation on the page.` を足す
- `server.py`: `show_annotated` と `move_mouse` の説明文の `(the latest 10 are kept)` を `(the latest 20 are kept)` にする
- `server.py`: `INSTRUCTIONS` の最後の文を `... call show_annotated once without buttons or message_box (html may be omitted) so the page leaves its thinking state.` にする
- `README.md`: ツール一覧の `show_annotated` の行に「`html` は省略でき、その場合は画像と説明文だけのページになる」を足す

- [ ] **Step 4: 全件 PASS を確かめる**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/captures.py src/ai_desktop/server.py README.md tests/test_captures.py tests/test_server.py
git commit -m "feat: keep 20 captures and let show_annotated omit html" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: ページに「更新」ボタンを常に出す

**Files:**
- Modify: `src/ai_desktop/annotate.py`（`REFRESH_LABEL`、`#bar` の HTML、CSS、JS の `refresh()`・`syncControls`・クリックの登録）
- Modify: `src/ai_desktop/viewer.py`（`Viewer.refresh()`、`do_POST` の `/refresh`、`AFTER_CLICK_SECONDS` のコメント）
- Modify: `src/ai_desktop/server.py`（`_clean_buttons` の予約名、`wait_for_message` と `show_annotated` の説明文、`INSTRUCTIONS`）
- Modify: `scripts/e2e_viewer.py`（「更新」と `html` 省略の確認を足し、冒頭の説明を直す）
- Modify: `README.md`（使い方の例、ツール一覧の `show_annotated`・`wait_for_message`、既知の制限の「ボタンで撮り直す」の行）
- Test: `tests/test_viewer.py`、`tests/test_annotate.py`、`tests/test_server.py`

**Interfaces:**
- Consumes: Task 1 の `show_annotated`（`html` 省略可）
- Produces:
  - `ai_desktop.annotate.REFRESH_LABEL: str = "更新"`（ページのボタンの文字と、server の予約名の両方で使う）
  - `Viewer.refresh() -> None`: 待ち受け中なら `{"message": "", "via": "refresh"}` で待っている呼び出しを起こす。待ち受け中でなければ `CaptureError(NOT_WAITING_MESSAGE)`（判定の順は `press` と同じ。待ち受け中は必ずページがある）
  - `POST /refresh`（本文 `{}`）: 200 `{"ok": true}`、断るときは 200 `{"error": "<文言>"}`、トークン・`Origin`・`Host` の不一致は 403
  - `wait_for_message` の `via` に `"refresh"` が加わる

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_viewer.py` に足す:

```python
def test_refresh_wakes_the_waiter(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    thread, results = wait_in_background(viewer)
    viewer.refresh()
    thread.join(5)
    assert results == [{"message": "", "via": "refresh"}]
    assert viewer._state == "thinking"


def test_refresh_without_a_waiter_is_refused(viewer):
    with pytest.raises(CaptureError, match="待ち受けていません"):
        viewer.refresh()
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    with pytest.raises(CaptureError, match="待ち受けていません"):
        viewer.refresh()


def test_a_second_refresh_before_the_next_wait_is_refused(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    thread, results = wait_in_background(viewer)
    viewer.refresh()
    thread.join(5)
    with pytest.raises(CaptureError, match="待ち受けていません"):
        viewer.refresh()
    assert results == [{"message": "", "via": "refresh"}]


def test_refresh_after_the_page_lost_its_inputs_is_refused(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    thread, results = wait_in_background(viewer)
    viewer.publish("c2", "", "Excel")
    thread.join(5)
    assert results == [None]
    with pytest.raises(CaptureError, match="待ち受けていません"):
        viewer.refresh()


def test_refresh_endpoint_checks_auth_and_state(viewer):
    viewer.publish("c2", "<div></div>", "Excel", "", ["できた"])
    assert post(viewer, "/refresh", {}, token="wrong")[0] == 403
    assert post(viewer, "/refresh", {}, origin="https://example.com")[0] == 403
    status, result = post(viewer, "/refresh", {})
    assert status == 200 and "待ち受けていません" in result["error"]
    thread, results = wait_in_background(viewer)
    assert post(viewer, "/refresh", {}) == (200, {"ok": True})
    thread.join(5)
    assert results == [{"message": "", "via": "refresh"}]
```

`tests/test_annotate.py` に足す（あわせて `test_viewer_shell_has_button_bar_and_explanation_panel` の `#bar` の行を、下の 1 つ目の文字列に置き換える）:

```python
def test_viewer_shell_has_a_builtin_refresh_button():
    page = render_shell("n0nce")
    assert (
        '<div id="bar" hidden><button id="refresh" type="button">更新</button>'
        '<span id="buttons"></span><span id="bar-state"></span>'
    ) in page
    assert 'post("/refresh", {})' in page
    assert 'document.getElementById("refresh").disabled = !enabled;' in page
    assert "#bar #refresh {" in page
```

`tests/test_server.py` に足す:

```python
@pytest.mark.parametrize("label", ["更新", " 更新 "])
def test_show_annotated_rejects_the_reserved_refresh_label(viewer, label):
    call("capture_monitor")
    result = call("show_annotated", {"capture_id": "c1", "buttons": ["できた", label]})
    assert result.is_error
    assert "「更新」はページに常に出ている" in result.content[0].text
    assert viewer.published == []


def test_wait_for_message_returns_a_refresh_and_fresh_capture(viewer):
    call("capture_window", {"title": "excel"})
    viewer.reply = {"message": "", "via": "refresh"}
    result = call("wait_for_message", {})
    assert not result.is_error
    meta = json.loads(result.content[1].text)
    assert (meta["message"], meta["via"], meta["captureId"]) == ("", "refresh", "c2")
```

`test_instructions_are_one_paragraph` に `assert "更新" in server.INSTRUCTIONS` と `assert 'via "refresh"' in server.INSTRUCTIONS` を足す。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest -q tests/test_viewer.py tests/test_annotate.py tests/test_server.py`
Expected: 上の新しいテストが FAIL（`refresh` がない、`/refresh` が 404、ボタンがない、予約名を通してしまう）

- [ ] **Step 3: 実装する**

- `annotate.py`
  - `REFRESH_LABEL = "更新"` を `MAX_MESSAGE_CHARS` の近くに置く
  - `render_shell` の `#bar` を、テストの文字列どおり「更新」ボタン → `#buttons` → `#bar-state` の順にする（ボタンの文字は `REFRESH_LABEL`）
  - CSS: `#bar #refresh { background: transparent; border: 1px solid #888; color: #ddd; }` と `#bar #refresh:disabled { border-color: #555; color: #777; }`（枠線だけで、Claude のボタンの赤い塗りつぶしと区別する。`#bar #refresh` は `#bar button:disabled` より強いので、押せないときの見た目も自分で持つ）
  - JS: `syncControls` で `document.getElementById("refresh").disabled = !enabled;`。`async function refresh()` を `press` と同じ形で作る（押した間は無効、`post("/refresh", {})`、`error` が返ったら `renderButtons()` してから `#bar-state` に文言、通信失敗は「送信できませんでした: 」）。`DOMContentLoaded` でクリックに登録する
- `viewer.py`
  - `Viewer.refresh()`（Interfaces のとおり。`_answer({"message": "", "via": "refresh"})`）
  - `do_POST` に `/refresh` を足す。`viewer.refresh()` の `CaptureError` は 200 の `{"error": ...}`、成功は `{"ok": True}`（`/press` と同じ）
  - `AFTER_CLICK_SECONDS` のコメントを `# apps (games especially) may handle a click on a later frame; keep focus and cursor until then` にする
- `server.py`
  - `_clean_buttons`: 空白を除いた後のラベルに `REFRESH_LABEL` があれば `ToolError`（Global Constraints の文言）
  - `wait_for_message` の説明文: `"via": "button" | "text" | "refresh"` とし、`via "refresh" means the user pressed the page's built-in 更新 button (message is ""): read the fresh capture again and show the current step again.` を足す
  - `show_annotated` の説明文に `A page with buttons or message_box also gets a built-in 更新 (refresh) button; never put 更新 in buttons.` を足す
  - `INSTRUCTIONS`: `... show the page again and wait again.` の直後に `Such a page always has a built-in 更新 (refresh) button too, so never put 更新 in buttons; a message with via "refresh" means the user wants you to look again, so read the fresh capture and show the current step again.` を足す（1 段落のまま）
- `scripts/e2e_viewer.py`: 入力欄のページの確認の後に、待ち受け中に `post_json(url, "/refresh", {})` を送り、`wait_for_message` が画像と `("", "refresh")` を返すことを確かめる。最後に `html` を省いた `show_annotated`（`title` だけ）がエラーにならないことを確かめる。冒頭の説明に 5・6 番として足す
- `README.md`: 使い方の例の「手順をボタンで案内して」に「『更新』を押すと Claude が画面を見直します」を足す。ツール一覧の `show_annotated` に「ボタンや入力欄のあるページには『更新』が常に出る」、`wait_for_message` の `via` に `"refresh"` を足す。既知の制限の「ボタンで撮り直すのは」を「ボタンや『更新』で撮り直すのは」にする

- [ ] **Step 4: 全件 PASS を確かめる**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/annotate.py src/ai_desktop/viewer.py src/ai_desktop/server.py scripts/e2e_viewer.py README.md tests/test_viewer.py tests/test_annotate.py tests/test_server.py
git commit -m "feat: add a built-in refresh button to the viewer page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: MCP をこのフォルダだけに登録する

**Files:**
- Create: `.mcp.json`
- Create: `tests/test_project_config.py`
- Modify: `README.md`（「Claude Code への登録」）

**Interfaces:**
- Produces: リポジトリ直下の `.mcp.json`（Task 6 でユーザー全体の登録を消したあと、これだけが残る）

- [ ] **Step 1: 失敗するテストを書く**

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_project_mcp_json_registers_only_ai_desktop():
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert config == {
        "mcpServers": {
            "ai-desktop": {
                "command": "uv",
                "args": ["run", "--no-sync", "--directory", "C:/Works/2026/ai-desktop", "ai-desktop"],
            }
        }
    }
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest -q tests/test_project_config.py`
Expected: FAIL（`FileNotFoundError: .mcp.json`）

- [ ] **Step 3: `.mcp.json` を作り、README を直す**

- `.mcp.json` はテストの辞書どおり（2 スペースの字下げ、末尾に改行）
- `README.md` の「Claude Code への登録」の `claude mcp add --scope user ...` の手順を次の内容に替える: 「このフォルダの `.mcp.json` に登録してある。Claude Code をこのフォルダで開くと、初回だけ使ってよいかの確認が出るので許可する」「`claude mcp get ai-desktop` で `Scope: Project config` と出れば OK」「以前ユーザー全体に登録していたら `claude mcp remove ai-desktop -s user` で消す（残っていると別のフォルダでも動いてしまう）」。`--no-sync` の理由の段落は残す

- [ ] **Step 4: 全件 PASS を確かめる**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add .mcp.json tests/test_project_config.py README.md
git commit -m "chore: register the MCP server for this folder only" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: スキルを汎用に書き直し、手引きを 3 つ足す

**Files:**
- Modify: `.claude/skills/ai-desktop-guide/SKILL.md`（全体を書き直す）
- Create: `.claude/skills/ai-desktop-guide/references/playbook-game.md`
- Create: `.claude/skills/ai-desktop-guide/references/playbook-app.md`
- Create: `.claude/skills/ai-desktop-guide/references/notes-format.md`

**Interfaces:**
- Consumes: Task 1・2 の振る舞い（`html` 省略、「更新」の常設、`via: "refresh"`、20 件）
- Produces: Task 5 が従う `notes-format.md` の型（フォルダの形、置き分け、確かさの印、README のひな形）

- [ ] **Step 1: `SKILL.md` を書き直す**

仕様書 §6.1 の 6 節（見出しは `## 1. 撮影の選び方` 〜 `## 6. 場面別の手引き`）で書く。今の SKILL.md の注釈・待ち受け（null が 5 回で止める）・カーソルの手順は残し、次を替える。

- 「更新」はページに常にある。`buttons` に入れない。`via` ごとの反応に `refresh`（撮り直し画像で読み直し、今の手順を出し直す）を足す
- 終わり方: ユーザーは入力欄に「終わり」と書く。Claude は入口なしで 1 回表示する（`html` は省略可）
- 例は「できた」「保存した」「見つからない」など汎用のものにする。説明文の 1 行目の例は「画面の状態、数値、残り時間など」
- 保持数は 20 件
- 知見は `notes/README.md`（索引）→ アプリのフォルダの順に読み、書き方は `references/notes-format.md`

`description` は次の文にする:

```text
ai-desktop MCP（mcp__ai-desktop__* ツール）でユーザーの Windows 画面を見て助ける手順。ゲームの相談・プレイの案内にも、アプリの操作・設定の案内にも使う。(1)「画面を見て」「このウィンドウどう？」「今の状態でアドバイスして」など画面・アプリ・ゲームについて聞かれたとき、(2)「どこを押せばいい？」「印をつけて見せて」など画面上の場所を示したいとき、(3)「手順をボタンで案内して」「一緒に進めて」「ブラウザから質問したい」など、注釈ページを Claude への入口（ボタン・入力欄・更新）にしてやりとりしながら案内するときに使う。撮影の選び方、注釈 HTML、ページでのやりとり、move_mouse で説明文を読む手順、アプリごとの知見（notes/）の読み書き、場面別の手引き（ゲーム／アプリ操作）を含む。
```

- [ ] **Step 2: `references/playbook-game.md` を書く**

仕様書 §6.2 の項目に加え、STS2 のノートから移す次のコツを入れる（Task 5 で notes からは消す）。

- 状態アイコン、相手の予告、持ち物、見切れた手札の説明はカーソルで読む。ゲームの説明文は画面の中に描かれるので `capture_window` の画像でよい。説明が出るのが遅いゲームは `wait_seconds` を 1.5〜2 にする
- 配る途中・エフェクト・開始の文字などの演出中は、数秒おいて撮り直す
- 「ターン終了した」が押されても、ゲームが追いついていないことがある。ターン数と資源を見てから案内する
- ボタンと入力欄の両方を出す（ボタンで表せない発言が来る）
- 説明文に、使う順番と数字（守りの量など）を書く
- 危ない場面の前に、持ち物（レリック、消耗品）を確かめる
- 読めないものは推測で埋めず、カーソルで読むか、ユーザーに確かめる

- [ ] **Step 3: `references/playbook-app.md` を書く**

仕様書 §6.3 の項目どおり。

- [ ] **Step 4: `references/notes-format.md` を書く**

仕様書 §6.4 の項目どおり。最後に、アプリの `README.md` のひな形（`## 概要`、`## 画面の見方`、`## ルールと注意`、`## 用語`、`## 未確認` の見出しと、各節に何を書くかの 1 行）を載せる。

- [ ] **Step 5: 確かめる**

Run: `grep -nE "HP|ターン|カード|敵|レリック|ポーション|デッキ" .claude/skills/ai-desktop-guide/SKILL.md`
Expected: 出力なし

Run: `grep -rn "docs/games\|直近 10" .claude/skills/ai-desktop-guide`
Expected: 出力なし

Run: `grep -c "references/playbook-game.md\|references/playbook-app.md\|references/notes-format.md\|notes/README.md" .claude/skills/ai-desktop-guide/SKILL.md`
Expected: 4 以上

- [ ] **Step 6: コミット**

```bash
git add .claude/skills/ai-desktop-guide
git commit -m "docs: rewrite the guide skill for any game or app and add playbooks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: notes を作り、STS2 の知見を移して整える

**Files:**
- Move: `docs/games/slay-the-spire2/` → `notes/slay-the-spire-2/`（`necrobinder.md` と `regent.md` は `characters/` の下へ）
- Create: `notes/README.md`、`notes/slay-the-spire-2/enemies.md`・`events.md`・`items.md`、`characters/silent.md`、`sessions/2026-10-04-silent.md`・`2026-10-05-necrobinder.md`・`2026-10-05-regent.md`
- Modify: `notes/slay-the-spire-2/README.md`（ゲーム全体の内容に整理）、`README.md`（notes の案内）

**Interfaces:**
- Consumes: Task 4 の `notes-format.md`（型と置き分け）。Task 4 が移したコツ（ゲーム用の手引きに入ったもの）は notes から消してよい

- [ ] **Step 1: 移す前の項目の一覧を作る**

表の 1 列目（カード名、敵名、イベント名など）を一覧にする。`smoke-out/` は git に入らない。

```bash
uv run --no-sync python - <<'EOF'
import pathlib
skip = {"カード", "敵", "イベント", "名前", "役割", "要素", "項目", "Task"}
names = []
for path in sorted(pathlib.Path("docs/games/slay-the-spire2").glob("*.md")):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ") and not line.startswith("|---"):
            cell = line.split("|")[1].strip()
            if cell and cell not in skip:
                names.append(cell)
out = pathlib.Path("smoke-out")
out.mkdir(exist_ok=True)
(out / "notes-inventory.txt").write_text("\n".join(names), encoding="utf-8")
print(len(names), "names")
EOF
```

Expected: `N names`（N は 100 前後）

- [ ] **Step 2: `git mv` で移す**

```bash
mkdir -p notes
git mv docs/games/slay-the-spire2 notes/slay-the-spire-2
mkdir -p notes/slay-the-spire-2/characters notes/slay-the-spire-2/sessions
git mv notes/slay-the-spire-2/necrobinder.md notes/slay-the-spire-2/characters/necrobinder.md
git mv notes/slay-the-spire-2/regent.md notes/slay-the-spire-2/characters/regent.md
```

- [ ] **Step 3: 仕様書 §7.2 の表どおりに中身を置き分ける**

- `README.md` は `notes-format.md` のひな形の見出し（概要、画面の見方、ルールと注意、用語、未確認）にそろえる
- 敵の表は `enemies.md` に 1 つにまとめる（今の 3 ファイルの敵の節）。同じ敵は 1 行にまとめ、どのキャラのランで見たかを書き添える
- `characters/*.md` から `README.md`、`enemies.md` などへのリンクは相対（`../README.md`）
- Task 4 で手引きに移したアプリを問わないコツ（今の README §6 の大半、regent §6 の一般的な教訓）は notes から消す。STS2 固有の座標の目安とボタンの位置は `README.md`「画面の見方」に残す
- `notes/README.md` は仕様書 §7.1 の索引の表（Slay the Spire 2 の 1 行）と、「新しいアプリを扱ったら 1 行足す」の一文
- リポジトリの `README.md` に「アプリやゲームごとの知見は `notes/` にたまる（索引は `notes/README.md`）」を足す

- [ ] **Step 4: 抜けとリンク切れがないことを確かめる**

```bash
uv run --no-sync python - <<'EOF'
import pathlib, re
names = pathlib.Path("smoke-out/notes-inventory.txt").read_text(encoding="utf-8").splitlines()
files = list(pathlib.Path("notes").rglob("*.md"))
text = "\n".join(p.read_text(encoding="utf-8") for p in files)
print("missing:", [n for n in names if n not in text])
broken = []
for path in files:
    for target in re.findall(r"\]\(([^)#]+\.md)\)", path.read_text(encoding="utf-8")):
        if not (path.parent / target).exists():
            broken.append((str(path), target))
print("broken:", broken)
EOF
```

Expected: `missing: []` と `broken: []`

Run: `grep -rn "docs/games" README.md .claude notes`
Expected: 出力なし

- [ ] **Step 5: コミット**

```bash
git add -A notes docs/games README.md
git commit -m "docs: move the Slay the Spire 2 notes to notes/ and layer them" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 実機で確かめ、MCP の登録を切り替える

このタスクは、ユーザーとやりとりできるメインのセッションで行う（サブエージェントにしない）。

**Files:**
- Modify: `~/.claude/projects/c--Works-2026-ai-desktop/memory/viewer-refresh-button.md` と `MEMORY.md` の 1 行
- Modify: `docs/superpowers/specs/2026-10-05-generalize-design.md`（状態を「実装済み」に）

**Interfaces:**
- Consumes: Task 1〜5 のすべて

- [ ] **Step 1: 全件 PASS を確かめる**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 2: 実機の通し確認**

Run: `uv run --no-sync python scripts/e2e_viewer.py`（ブラウザのタブと試験用ウィンドウが開く。実行中はマウスに触らない）
Expected: 最後まで assert で止まらず、「更新」の行で `('', 'refresh')`、`html` を省いた表示がエラーにならない

- [ ] **Step 3: ユーザー全体の登録を消す**

Run: `claude mcp remove ai-desktop -s user`
Expected: ユーザー全体の設定から消えたという表示

Run: `claude mcp get ai-desktop`（このフォルダで）
Expected: `Scope: Project config`

Run: `cd C:/Works/2026/AiGameCompanion && claude mcp get ai-desktop`
Expected: ai-desktop が見つからない

- [ ] **Step 4: メモリーを直す**

`viewer-refresh-button.md` の本文を「『更新』はページに常に出る（2026-10-05 の汎用化で MCP に組み込み）。buttons に『更新』を入れない（入れるとエラー）。ボタンはその場面で済ませた操作の名前にし、『やめる』は出さない。終わりは入力欄に『終わり』」に直し、`MEMORY.md` のその行の説明も合わせる

- [ ] **Step 5: ユーザーに再接続と確認を頼む**

ユーザーに次を頼み、結果を一緒に確かめる。

1. 古いビューアーのタブを閉じる
2. Claude Code をこのフォルダで開き直し、ai-desktop の使用を許可する
3. Claude がウィンドウを撮り、ボタン付きのページを出す。ユーザーが「更新」を押し、Claude に `via: "refresh"` と撮り直し画像が届く

- [ ] **Step 6: 仕様書の状態を直してコミット**

仕様書の `状態` を `実装済み（2026-10-05）` にする。

```bash
git add docs/superpowers/specs/2026-10-05-generalize-design.md
git commit -m "docs: mark the generalization design as implemented" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
