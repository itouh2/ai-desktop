# click（Claude が押す左クリック）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ユーザーが注釈ページで「Claude に操作を任せる」をオンにしている間だけ、Claude がページに表示中のウィンドウを左クリックし、すぐ撮り直して返す MCP ツール `click` を加える。

**Architecture:** 許可の状態（オン／オフ）と Claude が押した記録はビューアー（`viewer.py`）が持ち、ページの切り替えは POST `/agent`、表示は SSE の state で行き来する。`click` ツールは `viewer.authorize_click()` で確かめてから、既存の `Pointer.at()`（前面化・座標変換・後片付け・排他ロック）の中で `inputs.click()` を送る。押したあとはフォーカスを戻さないため、`Pointer.at()` に `return_focus` を足す。

**Tech Stack:** Python 3.11+ / uv / mcp 2.x（`MCPServer`）/ ctypes SendInput / http.server + SSE / pytest / tkinter（試験用ウィンドウ）

**Spec:** `docs/superpowers/specs/2026-10-05-claude-click-design.md`

## Global Constraints

- 作業ツリー: `C:\Works\2026\ai-desktop\.worktrees\claude-click`（ブランチ `feature/claude-click`）。元のフォルダ（`C:\Works\2026\ai-desktop`）と `notes/` には触らない
- 新しい依存を加えない（`pyproject.toml` の `dependencies` を変えない）
- `click` が送るのは左クリック 1 回だけ（`inputs.click(x, y)`、`double=False`）。右クリック・ダブルクリック・ドラッグは入れない
- 押せるのは、ページに表示中の撮影と同じウィンドウ（`Target("window", id)` が一致）だけ。モニター全体の撮影では押せない
- 許可は始めオフ。ページの POST `/agent` だけが切り替える（MCP ツールからは変えられない）。接続中のタブが 0 になったらオフ
- `what`: 前後の空白を除いて 1〜60 文字。`wait_seconds`: 0.3〜5 秒に丸める（既定 0.5）
- エラーはすべて `CaptureError`（日本語）で投げ、`server.py` の `_reported()` で `ToolError` にする。文言は spec §6 のとおり
- Claude が押した記録はページで `textContent` で入れる（HTML として解釈しない）。記録は新しい順に最大 5 件、要素は `{"time": "HH:MM:SS", "what": "<what>"}`
- テスト: `uv run --no-sync pytest -q`（plain `uv run` は使わない）。各タスクの終わりで全件 PASS
- コミットの末尾に空行と `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. 許可がオンのまま、ページが別のウィンドウやモニター全体の撮影に切り替わった → 古い `captureId` でも押せない（表示中の撮影の対象で判定）。Task 2 のテスト `test_authorize_follows_the_page_that_is_shown_now`
2. Claude が確かめたあと、押す前にユーザーがオフにした → 押さない。Task 4 のテスト `test_click_is_refused_when_permission_ends_before_the_press`
3. タブを 2 つ開いていて 1 つ閉じた → オンのまま。すべて閉じた → オフ。Task 2 のテスト `test_closing_the_last_tab_turns_the_agent_off`
4. `what` に HTML（`<img src=x onerror=...>`）が入る → ページでは文字として出る。Task 3 のテスト `test_agent_log_is_written_as_text`
5. 押したあと撮り直しに失敗した → クリックは送られ記録にも残り、カーソルは戻る。Task 4 のテスト `test_click_puts_the_cursor_back_when_the_recapture_fails`

---

## ファイル構成

| ファイル | 変更 | タスク |
|---|---|---|
| `src/ai_desktop/pointer.py` | `Pointer.at` に `return_focus` | 1 |
| `src/ai_desktop/viewer.py` | 許可・記録・`authorize_click`・POST `/agent`・SSE・`target` | 2 |
| `src/ai_desktop/annotate.py` | 「Claude に操作を任せる」欄と記録の表示 | 3 |
| `src/ai_desktop/server.py` | `click` ツール、INSTRUCTIONS | 4 |
| `scripts/e2e_click.py`（新規） | 実機確認 | 5 |
| `README.md`、`.claude/skills/ai-desktop-guide/SKILL.md`、`.claude/skills/ai-desktop-guide/references/playbook-game.md` | ドキュメント | 6 |
| `tests/test_pointer.py`、`tests/test_viewer.py`、`tests/test_annotate.py`、`tests/test_server.py` | テスト | 1〜4 |

---

### Task 1: Pointer.at に return_focus を足す

**Files:**
- Modify: `src/ai_desktop/pointer.py`（`Pointer.at`）
- Test: `tests/test_pointer.py`

**Interfaces:**
- Produces: `Pointer.at(capture_id: str, x: float, y: float, keep_clear: Literal["point", "capture"], return_focus: bool = True) -> Iterator[Spot]`。`return_focus=False` のとき、後片付けで操作前の前面ウィンドウを `restore` しない。このとき最小化したブラウザは今どおり `restore` する

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_pointer.py` の末尾。既存の `store`（c1 モニター、c2 ウィンドウ 42）・`control`・`pointer` フィクスチャを使う）

```python
def test_without_return_focus_the_target_stays_in_front(pointer, control):
    control.foreground = 999
    with pointer.at("c2", 10, 20, keep_clear="point", return_focus=False):
        pass
    assert ("bring_to_front", 42) in control.calls
    assert ("restore", 999) not in control.calls


def test_without_return_focus_a_minimized_browser_still_comes_back(pointer, control):
    control.foreground = 999
    control.browser_rect = (3000, 0, 3840, 1000)  # overlaps the monitor capture
    with pointer.at("c1", 49, 98, keep_clear="capture", return_focus=False):
        pass
    assert control.calls[-1] == ("restore", BROWSER)
    assert ("restore", 999) not in control.calls
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest tests/test_pointer.py -q`
Expected: 2 件 FAIL（`TypeError: ... unexpected keyword argument 'return_focus'`）

- [ ] **Step 3: `return_focus: bool = True` を足し、後片付けの `restore(previous)` を `return_focus` が真のときだけにする。docstring に 1 文足す**

- [ ] **Step 4: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS（166 件）

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/pointer.py tests/test_pointer.py
git commit -m "feat: let a point operation leave focus on its target"
```

---

### Task 2: ビューアーに許可と記録を持たせる

**Files:**
- Modify: `src/ai_desktop/viewer.py`
- Test: `tests/test_viewer.py`

**Interfaces:**
- Consumes: `CaptureStore.target(capture_id) -> Target`（既存）
- Produces（Task 3・4 が使う）:
  - `Viewer.set_agent(enabled: bool) -> None`
  - `Viewer.authorize_click(capture_id: str) -> None`（だめなら `CaptureError`）
  - `Viewer.record_click(what: str) -> None`
  - SSE `event: state` の data に `"agent": {"enabled": bool, "clicks": [{"time": "HH:MM:SS", "what": str}, ...]}`
  - 表示内容（SSE `event: view`）に `"target": "window" | "monitor"`
  - POST `/agent` 本文 `{"enabled": bool}` → `{"ok": true}`。`enabled` が `bool` でなければ 400
- 定数（`viewer.py`）: `MAX_CLICK_RECORDS = 5`、`AGENT_OFF_MESSAGE`、`NO_PAGE_FOR_CLICK_MESSAGE`、`MONITOR_CLICK_MESSAGE`、`OTHER_WINDOW_MESSAGE`。文言は spec §6 の表の 1〜4 行目をそのまま使う:
  - `AGENT_OFF_MESSAGE = "ページで『Claude に操作を任せる』がオフです。押してほしいことをユーザーに伝えるか、オンにしてもらってください。"`
  - `NO_PAGE_FOR_CLICK_MESSAGE = "表示中のページがありません。先に show_annotated で対象のウィンドウを表示してください。"`
  - `MONITOR_CLICK_MESSAGE = "画面全体の撮影ではクリックできません。対象のウィンドウを capture_window で撮り、ページに表示してください。"`
  - `OTHER_WINDOW_MESSAGE = "クリックできるのは、ページに表示中のウィンドウだけです。"`

判定の順（`authorize_click`）: オフ → ページなし → `capture_id` の対象がモニター → 表示中の撮影の対象と違う。状態はすべて `self._changed` の下で読み書きし、許可・記録が変わったら `_state_version` を進めて `notify_all()` する（既存の `_set_state` と同じ流れ。状態名は変えない）。接続中のタブが 0 になったら `unregister_client` で許可をオフにする。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_viewer.py`。既存の `store`（c1 モニター 1、c2 ウィンドウ 42）・`viewer`・`post` を使う。必要な撮影は `store.add(b"x", WINDOW_META, Target("window", 42))` などで足す。`import re` を加える）

```python
# --- Claude's clicks: permission and records ----------------------------------------------


def test_agent_is_off_until_the_page_turns_it_on(viewer):
    viewer.publish("c2", "", "Excel")
    with pytest.raises(CaptureError, match="オフです"):
        viewer.authorize_click("c2")
    viewer.set_agent(True)
    viewer.authorize_click("c2")  # no error


def test_authorize_needs_a_shown_page(viewer):
    viewer.set_agent(True)
    with pytest.raises(CaptureError, match="表示中のページがありません"):
        viewer.authorize_click("c2")


def test_authorize_refuses_monitor_captures(viewer):
    viewer.publish("c1", "", "Display")
    viewer.set_agent(True)
    with pytest.raises(CaptureError, match="画面全体の撮影ではクリックできません"):
        viewer.authorize_click("c1")


def test_authorize_allows_a_newer_capture_of_the_shown_window(viewer, store):
    newer = store.add(b"window-jpeg", WINDOW_META, Target("window", 42))
    viewer.publish("c2", "", "Excel")
    viewer.set_agent(True)
    viewer.authorize_click(newer)  # no error


def test_authorize_refuses_another_window(viewer, store):
    other = store.add(b"window-jpeg", WINDOW_META, Target("window", 43))
    viewer.publish("c2", "", "Excel")
    viewer.set_agent(True)
    with pytest.raises(CaptureError, match="表示中のウィンドウだけ"):
        viewer.authorize_click(other)


def test_authorize_follows_the_page_that_is_shown_now(viewer):
    viewer.publish("c2", "", "Excel")
    viewer.set_agent(True)
    viewer.publish("c1", "", "Display")  # the page now shows the whole monitor
    with pytest.raises(CaptureError, match="表示中のウィンドウだけ"):
        viewer.authorize_click("c2")


def test_agent_and_clicks_reach_the_page_state(viewer):
    viewer.set_agent(True)
    viewer.record_click("研究卓を選ぶ")
    _, state = viewer.next_update(0, 0, 0)
    assert state["agent"]["enabled"] is True
    [record] = state["agent"]["clicks"]
    assert record["what"] == "研究卓を選ぶ"
    assert re.fullmatch(r"\d\d:\d\d:\d\d", record["time"])


def test_each_change_moves_the_state_version(viewer):
    _, first = viewer.next_update(0, 0, 0)
    viewer.set_agent(True)
    _, second = viewer.next_update(0, first["version"], 0)
    viewer.record_click("タブを開く")
    _, third = viewer.next_update(0, second["version"], 0)
    assert first["version"] < second["version"] < third["version"]


def test_click_records_keep_the_newest_five(viewer):
    for number in range(1, 8):
        viewer.record_click(str(number))
    _, state = viewer.next_update(0, 0, 0)
    assert [record["what"] for record in state["agent"]["clicks"]] == ["7", "6", "5", "4", "3"]


def test_closing_the_last_tab_turns_the_agent_off(viewer):
    viewer.register_client()
    viewer.register_client()
    viewer.set_agent(True)
    viewer.unregister_client()
    _, state = viewer.next_update(0, 0, 0)
    assert state["agent"]["enabled"] is True
    viewer.unregister_client()
    _, state = viewer.next_update(0, 0, 0)
    assert state["agent"]["enabled"] is False


def test_publish_carries_the_target_kind(viewer):
    viewer.publish("c1", "", "Display")
    assert viewer.next_view(0, 0)["target"] == "monitor"
    viewer.publish("c2", "", "Excel")
    assert viewer.next_view(1, 0)["target"] == "window"


def test_agent_endpoint_checks_auth_and_body(viewer):
    viewer.ensure_started()
    assert post(viewer, "/agent", {"enabled": True}, token="wrong")[0] == 403
    assert post(viewer, "/agent", {"enabled": True}, origin="http://evil.example")[0] == 403
    assert post(viewer, "/agent", {"enabled": "yes"})[0] == 400
    assert post(viewer, "/agent", {})[0] == 400
    assert post(viewer, "/agent", {"enabled": True}) == (200, {"ok": True})
    _, state = viewer.next_update(0, 0, 0)
    assert state["agent"]["enabled"] is True
    assert post(viewer, "/agent", {"enabled": False}) == (200, {"ok": True})
    _, state = viewer.next_update(0, 0, 0)
    assert state["agent"]["enabled"] is False
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest tests/test_viewer.py -q`
Expected: 新しい 12 件が FAIL（`AttributeError: 'Viewer' object has no attribute 'authorize_click'` など）

- [ ] **Step 3: `viewer.py` に定数・状態（`self._agent = False`、`self._clicks: list[dict] = []`）・3 つのメソッド・`publish` の `"target"`・`next_update` の `"agent"`・`unregister_client` のオフ・POST `/agent` を加える**

`record_click` の時刻は `time.strftime("%H:%M:%S")`。新しい記録をリストの先頭に入れ、`MAX_CLICK_RECORDS` を超えた分を捨てる。`next_update` の `"agent"` はコピーを返す（`{"enabled": self._agent, "clicks": [dict(c) for c in self._clicks]}`）。POST `/agent` は既存の `/refresh` などと同じ形で `do_POST` に分岐を足す（認証の確認は分岐の前で済んでいる）。

- [ ] **Step 4: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS（178 件）。既存の `test_events_send_the_state_right_after_connecting` も PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/viewer.py tests/test_viewer.py
git commit -m "feat: keep the user's click permission and Claude's click log in the viewer"
```

---

### Task 3: ページに「Claude に操作を任せる」欄を出す

**Files:**
- Modify: `src/ai_desktop/annotate.py`（`_VIEWER_CSS`、`_VIEWER_SCRIPT`、`render_shell`）
- Test: `tests/test_annotate.py`

**Interfaces:**
- Consumes: SSE state の `agent`（`{"enabled", "clicks"}`）、view の `target`、POST `/agent {"enabled": bool}`（Task 2）
- Produces: 欄の要素 `#agent`（全体）、`#agent-on`（チェックボックス）、`#agent-note`（状態の文）、`#agent-log`（記録の `ol`）

決めた形:

- `render_shell` で `#status` の直後に次を置く（常に出る）:
  `<div id="agent"><label><input id="agent-on" type="checkbox"> Claude に操作を任せる（このウィンドウだけ・左クリック）</label><div id="agent-note"></div><ol id="agent-log"></ol></div>`
- CSS: `#agent` は `position: fixed; top: 12px; left: 12px; z-index: 10`、半透明の暗い背景。`#agent.on` はオレンジ（`#f5a524`）の枠と背景で目立たせる
- スクリプト: 関数 `renderAgent()` が、最後に届いた `agent` と `view` から表示を作る
  - チェックボックスの `checked` を `agent.enabled` に合わせる
  - `#agent` に `on` クラスを付け外しする。オンなら `#agent-note` に「操作を任せています」
  - `view && view.target === "monitor"` のときはチェックボックスを `disabled` にし、`#agent-note` に「画面全体の撮影ではクリックを任せられません」
  - 記録は `li` を作り `item.textContent = record.time + " " + record.what;`
- チェックボックスの `change` で `post("/agent", {enabled: checkbox.checked})`。表示は SSE の state が来たときに合わせる（失敗したら `status(...)` で知らせる）
- state のハンドラーは `buttonState` に加えて `agent` を受け取り `renderAgent()` を呼ぶ。`render(next)` の最後でも `renderAgent()` を呼ぶ
- 既存の `innerHTML` は注釈の 1 か所だけのまま（記録には使わない）

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_annotate.py`）

```python
def test_page_has_the_agent_toggle():
    page = render_shell("n0nce")
    assert '<input id="agent-on" type="checkbox">' in page
    assert "Claude に操作を任せる（このウィンドウだけ・左クリック）" in page
    assert 'post("/agent", {enabled:' in page
    assert '<ol id="agent-log"></ol>' in page


def test_agent_log_is_written_as_text():
    page = render_shell("n0nce")
    assert 'item.textContent = record.time + " " + record.what;' in page
    assert page.count(".innerHTML") == 1  # only the annotations


def test_agent_toggle_shows_its_state_and_refuses_monitor_captures():
    page = render_shell("n0nce")
    assert "#agent.on" in page
    assert "操作を任せています" in page
    assert 'view.target === "monitor"' in page
    assert "画面全体の撮影ではクリックを任せられません" in page
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest tests/test_annotate.py -q`
Expected: 3 件 FAIL

- [ ] **Step 3: 上の「決めた形」のとおり `annotate.py` を変える**

- [ ] **Step 4: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS（181 件）

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/annotate.py tests/test_annotate.py
git commit -m "feat: add the 'let Claude operate' toggle and click log to the viewer page"
```

---

### Task 4: click ツールを加える

**Files:**
- Modify: `src/ai_desktop/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Viewer.authorize_click(capture_id)`、`Viewer.record_click(what)`（Task 2）。`Pointer.at(..., return_focus=False)`（Task 1）。`inputs.click(x, y, double=False)`、`inputs.move(x, y)`（既存）
- Produces: MCP ツール `click(capture_id: str, x: float, y: float, what: str, wait_seconds: float = 0.5) -> list[Image | str]`。メタデータに `"clicked": {"x", "y", "captureId": <元の id>, "what"}`
- 定数（`server.py`）: `CLICK_WAIT_DEFAULT_SECONDS = 0.5`、`CLICK_WAIT_MIN_SECONDS = 0.3`、`CLICK_WAIT_MAX_SECONDS = 5.0`、`MAX_WHAT_CHARS = 60`
- `what` が空・60 文字超のエラー文言: `"what に、何を押すかを 1〜60 文字で書いてください。"`

手順（spec §5）: `what` を strip して検査 → `wait` を 0.3〜5 に丸める → `_reported()` の中で `target = captures.target(capture_id)`、`viewer.authorize_click(capture_id)` → `with pointer.at(capture_id, x, y, keep_clear="point", return_focus=False) as spot:` → その中でまず `viewer.authorize_click(capture_id)` をもう一度 → `try:` で `inputs.click(*spot.screen)`、`viewer.record_click(what)`、`_sleep(wait)`、`_recapture(target)` → `move_mouse` と同じ形でカーソルを `inputs.move(*spot.cursor)` で戻す（失敗の途中では `CaptureError` を抑えて元のエラーを投げ直す）。2 回目の確認は `try` の前なので、そこで拒否されたらカーソルは動かない。

ツールの説明文（docstring、英語。既存のツールと同じ書き方）の要点: ユーザーがページで「Claude に操作を任せる」をオンにしているときだけ、ページに表示中のウィンドウ（そのウィンドウの新しい撮影の座標でもよい）を左クリックし、待って撮り直す。右クリック・ダブルクリック・ドラッグはできない。`what` に何を押すかを書き、押したら必ずチャットにそれを書く。オフのときはエラーになるので、ユーザーに押してもらうか、オンにしてもらう。押したウィンドウは前面のまま。各引数の意味と範囲。

INSTRUCTIONS: move_mouse の文の直後に次の 1 文を足す（`\` で続け、段落を分けない）:

```text
When the user has turned on "Claude に操作を任せる" on the viewer page, you may left-click \
the window shown there with click (capture_id, x, y and a short what describing the target); \
it clicks once, waits, captures the same window again and returns it, and after every click \
you must tell the user in the chat what you clicked. If it is off, ask the user to click or to turn it on. \
```

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_server.py`）

1. `test_exposes_seven_tools` を `test_exposes_eight_tools` にし、集合に `"click"` を加える
2. `test_instructions_are_one_paragraph` に `assert "click" in server.INSTRUCTIONS and "Claude に操作を任せる" in server.INSTRUCTIONS` を加える
3. `FakeViewer` に許可と記録を足す:

```python
    # in FakeViewer.__init__
        self.allowed = True
        self.deny_on_call = None  # deny from this authorize_click call on (1 = the first)
        self.authorized = []
        self.recorded = []

    def authorize_click(self, capture_id):
        self.authorized.append(capture_id)
        if not self.allowed or (self.deny_on_call is not None and len(self.authorized) >= self.deny_on_call):
            raise CaptureError("ページで『Claude に操作を任せる』がオフです。押してほしいことをユーザーに伝えるか、オンにしてもらってください。")

    def record_click(self, what):
        self.recorded.append(what)
```

4. 末尾にフィクスチャとテストを足す（既存の `mouse` フィクスチャの上に、クリックを記録するものを重ねる）:

```python
@pytest.fixture
def hand(mouse, monkeypatch):
    """mouse, but clicks are recorded instead of failing the test."""
    mouse.clicks = []
    monkeypatch.setattr(inputs, "click", lambda x, y, double=False: mouse.clicks.append((x, y, double)))
    return mouse


def test_click_is_refused_without_permission(hand, viewer):
    viewer.allowed = False
    call("capture_window", {"title": "excel"})
    result = call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": "セルを選ぶ"})
    assert result.is_error
    assert "オフです" in result.content[0].text
    assert hand.clicks == [] and hand.moves == []
    assert ("bring_to_front", 42) not in hand.control.calls


def test_click_left_clicks_once_waits_recaptures_and_puts_the_cursor_back(hand, viewer):
    call("capture_window", {"title": "excel"})  # c1; FakeControl puts the window at (100, 200)
    result = call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": "研究卓を選ぶ"})
    assert not result.is_error
    meta = json.loads(result.content[1].text)
    assert meta["captureId"] == "c2"
    assert meta["clicked"] == {"x": 10, "y": 20, "captureId": "c1", "what": "研究卓を選ぶ"}
    assert hand.clicks == [(110, 220, False)]
    assert hand.sleeps == [0.5]
    assert hand.moves == [(5, 6)]
    assert viewer.authorized == ["c1", "c1"]
    assert viewer.recorded == ["研究卓を選ぶ"]


def test_click_is_refused_when_permission_ends_before_the_press(hand, viewer):
    viewer.deny_on_call = 2
    call("capture_window", {"title": "excel"})
    result = call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": "セルを選ぶ"})
    assert result.is_error
    assert hand.clicks == [] and hand.moves == []
    assert viewer.recorded == []


@pytest.mark.parametrize("what", ["", "   ", "あ" * 61])
def test_click_needs_a_short_what(hand, viewer, what):
    call("capture_window", {"title": "excel"})
    result = call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": what})
    assert result.is_error
    assert "1〜60 文字" in result.content[0].text
    assert hand.clicks == []


@pytest.mark.parametrize(("wait", "expected"), [(0, 0.3), (9, 5.0), (1.25, 1.25)])
def test_click_clamps_the_wait(hand, viewer, wait, expected):
    call("capture_window", {"title": "excel"})
    call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": "セルを選ぶ", "wait_seconds": wait})
    assert hand.sleeps == [expected]


def test_click_puts_the_cursor_back_when_the_recapture_fails(hand, viewer, monkeypatch):
    call("capture_window", {"title": "excel"})

    def gone(hwnd):
        raise CaptureError("window_id 42 のウィンドウは存在しません。")

    monkeypatch.setattr(capture, "capture_window", gone)
    result = call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": "セルを選ぶ"})
    assert result.is_error
    assert hand.clicks == [(110, 220, False)]
    assert hand.moves == [(5, 6)]
    assert viewer.recorded == ["セルを選ぶ"]


def test_click_leaves_the_clicked_window_in_front(hand, viewer):
    hand.control.foreground = 999
    call("capture_window", {"title": "excel"})
    call("click", {"capture_id": "c1", "x": 10, "y": 20, "what": "セルを選ぶ"})
    assert ("restore", 999) not in hand.control.calls
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --no-sync pytest tests/test_server.py -q`
Expected: ツール数・INSTRUCTIONS と新しい `click` のテストが FAIL

- [ ] **Step 3: 定数・INSTRUCTIONS の 1 文・`click` ツールを `server.py` に加える（`move_mouse` の後ろ）**

- [ ] **Step 4: テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_desktop/server.py tests/test_server.py
git commit -m "feat: add the click tool for left-clicks the user has allowed on the page"
```

---

### Task 5: 実機確認スクリプト

**Files:**
- Create: `scripts/e2e_click.py`

**Interfaces:**
- Consumes: `scripts/click_target.py`（`TITLE`、出力の JSON `{"single", "double", "enter", "leave"}`、第 1 引数の geometry）、MCP ツール `capture_window`・`show_annotated`・`click`（Task 4）、POST `/agent`（Task 2）、`ai_desktop.control.set_cursor/cursor_pos/foreground_window`、`ai_desktop.capture.list_windows/enable_dpi_awareness`

流れ（`scripts/e2e_viewer.py` と `scripts/e2e_move_mouse.py` の書き方に合わせる。`post_json` は `e2e_viewer.py` から import してよい）:

1. 試験用ウィンドウを `520x320+240+240` で開き、MCP サーバー（`uv run --no-sync ai-desktop`）に stdio でつなぐ
2. `capture_window(title=TITLE)` → `show_annotated(capture_id, html="", title="e2e click")`。返った URL のタブが開くのを 4 秒待つ
3. カーソルをウィンドウの外（左上から 40 px 外）に置く
4. POST `/agent {"enabled": false}` → `click(capture_id, 中央, what="試験用ウィンドウの中央")` → エラーで「オフです」を含むこと、`single` が増えないこと
5. POST `/agent {"enabled": true}` → 同じ `click` → 成功、`single` が 1 増えること、`double` が 0 のまま、`control.foreground_window()` が試験用ウィンドウ、カーソルが 3 の位置に戻ること、メタデータの `clicked.what`
6. POST `/agent {"enabled": false}`、試験用ウィンドウを閉じる（`terminate()` と `wait(timeout=5)`）。最後に `OK` を表示

- [ ] **Step 1: スクリプトを書く**
- [ ] **Step 2: 構文を確かめる**（マウスを動かすので、実行は controller が行う）

Run: `uv run --no-sync python -m py_compile scripts/e2e_click.py`
Expected: 出力なし

- [ ] **Step 3: 単体テストを流す**

Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 4: コミット**

```bash
git add scripts/e2e_click.py
git commit -m "test: add an end-to-end check that click only works while the page allows it"
```

---

### Task 6: ドキュメントとスキル

**Files:**
- Modify: `README.md`
- Modify: `.claude/skills/ai-desktop-guide/SKILL.md`
- Modify: `.claude/skills/ai-desktop-guide/references/playbook-game.md`

**Interfaces:**
- Consumes: `click` の引数と動き（Task 4）、ページの欄（Task 3）

書くこと:

- `README.md`
  - ツール表に `click` の行（ページで任されたときだけ、表示中のウィンドウを左クリックし、`wait_seconds`（0.3〜5 秒、既定 0.5）待って撮り直す。`what` に何を押すかを書く。押したウィンドウは前面のまま）
  - 既知の制限: 左クリックだけ（右クリック・ダブルクリック・ドラッグなし）。許可はページの「Claude に操作を任せる」で、タブをすべて閉じるか MCP が再起動するとオフ。押せるのはページに表示中のウィンドウだけ（画面全体の撮影では押せない）。Claude Code のツール許可で `click` を毎回確認にもできる
  - 実機の動作確認に `uv run python scripts/e2e_click.py  # click の確認（試験用ウィンドウとブラウザのタブが開きます。実行中はマウスに触らない）`
- `SKILL.md`
  - 冒頭のツール一覧を 8 つにし、`click` を加える
  - §4 の注意「クリックはしない。押す操作が必要なら、注釈ページでユーザーに押してもらう。」を「`move_mouse` はクリックしない。押す必要があれば 4.1 節」にする
  - 「## 4. カーソルで説明文を読む」の後ろに「### 4.1 Claude が押す（click）」を足す:
    1. 押して確かめたいこと（物を選んで情報を読む、タブを開くなど）があり、ページに対象のウィンドウを表示しているなら、ユーザーに「ページの『Claude に操作を任せる』をオンにすると、私が押して確かめます」と一度だけ頼む
    2. オンなら `click(capture_id, x, y, what="<何を押すか>")`。`what` は押す物の名前と目的を短く（例:「左下の研究卓を選ぶ」）
    3. 押すたびに、チャットに「押したもの」と「結果（返った画像で読めたこと）」を書く
    4. オフのエラーなら、押してほしい場所を注釈で示してユーザーに押してもらう（前と同じやり方）
    5. 押せるのは左クリックだけ。右クリックのメニュー、ドラッグ、文字入力は、ユーザーに頼む
    6. 何かを決める操作（建てる、捨てる、購入、設定の保存など、元に戻しにくいもの）は、任されていても押す前にユーザーに確かめる。任されているのは、選ぶ・開く・読むための操作
- `playbook-game.md`: 「## 3. 状態をひととおり読む」の箇条に 1 行「物や建物の正体は、クリックして情報欄で確かめる。任されていれば `click`、なければユーザーに押してもらう。見た目で決めない。」

- [ ] **Step 1: 3 つのファイルを書き換える**
- [ ] **Step 2: 確かめる**

Run: `grep -c "click" README.md .claude/skills/ai-desktop-guide/SKILL.md .claude/skills/ai-desktop-guide/references/playbook-game.md`
Expected: どれも 1 以上
Run: `uv run --no-sync pytest -q`
Expected: 全件 PASS

- [ ] **Step 3: コミット**

```bash
git add README.md .claude/skills/ai-desktop-guide/SKILL.md .claude/skills/ai-desktop-guide/references/playbook-game.md
git commit -m "docs: document click and when Claude may press for the user"
```
