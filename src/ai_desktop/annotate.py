"""The viewer page: a capture as background with Claude's HTML on top, updated live."""

from __future__ import annotations

_CSS = """
html, body { margin: 0; background: #1e1e1e; }
html { overflow-y: scroll; }
#viewport { position: relative; width: 100%; overflow: hidden; }
#stage { position: relative; transform-origin: 0 0; }
#shot { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
#annotations { position: absolute; inset: 0; isolation: isolate;
  font-family: system-ui, "Yu Gothic UI", sans-serif; }
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

VIEWER_TITLE_PREFIX = "ai-desktop | "
MAX_MESSAGE_CHARS = 1000
REFRESH_LABEL = "更新"  # the page's built-in refresh button; reserved, so Claude's buttons cannot use it

_VIEWER_CSS = """
#stage { cursor: crosshair; }
#status { position: fixed; top: 12px; right: 12px; z-index: 10; display: none; padding: 8px 14px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.78); color: #fff;
  font: 14px/1.5 system-ui, "Yu Gothic UI", sans-serif; }
#status.show { display: block; }
#status.error { background: #e5484d; }
#agent { position: fixed; top: 12px; left: 12px; z-index: 10; box-sizing: border-box; max-width: 320px;
  padding: 8px 12px; border: 2px solid transparent; border-radius: 6px; background: rgba(0, 0, 0, 0.78);
  color: #fff; font: 14px/1.5 system-ui, "Yu Gothic UI", sans-serif; }
#agent.on { border-color: #f5a524; background: rgba(245, 165, 36, 0.92); color: #1a1a1a; }
#agent label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
#agent input:disabled { cursor: default; }
#agent-note:empty, #agent-log:empty { display: none; }
#agent-log { margin: 6px 0 0; padding-left: 22px; font-size: 13px; }
#layout { display: flex; flex-direction: column; }
#viewport { margin: 0 auto; }
#side { box-sizing: border-box; max-height: 30vh; overflow-y: auto; padding: 12px 16px; color: #eee;
  border-top: 1px solid #333; font: 15px/1.7 system-ui, "Yu Gothic UI", sans-serif; white-space: pre-wrap; }
#bar { position: sticky; bottom: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  padding: 8px 12px; background: #2a2a2a; font: 14px system-ui, "Yu Gothic UI", sans-serif; }
#bar[hidden], #side[hidden], #compose[hidden] { display: none; }
#bar button { padding: 6px 14px; border: 0; border-radius: 6px; background: #e5484d; color: #fff;
  font: inherit; font-weight: 700; cursor: pointer; }
#bar button:disabled { background: #555; color: #aaa; cursor: default; }
#bar #refresh { background: transparent; border: 1px solid #888; color: #ddd; }
#bar #refresh:disabled { border-color: #555; color: #777; }
#bar-state { margin-left: auto; color: #ccc; }
#compose { display: flex; align-items: flex-end; gap: 8px; width: 100%; }
#message { flex: 1; box-sizing: border-box; min-height: 36px; max-height: 160px; padding: 6px 10px;
  border: 1px solid #555; border-radius: 6px; background: #1e1e1e; color: #eee; resize: none;
  font: inherit; line-height: 1.5; }
#message:focus { outline: 2px solid #e5484d; outline-offset: -1px; }
"""

# The live viewer: receives views over SSE, scales the stage, and posts clicks back.
_VIEWER_SCRIPT = """
const token = new URLSearchParams(location.search).get("t");
let view = null;
let busy = false;
let pending = null;
let statusTimer = null;
let buttonState = "idle";
let sending = false;
let agent = {enabled: false, clicks: []};
// The permission panel's elements, taken once at startup before any annotation HTML is on the page,
// so nothing drawn later can stand in for them.
let agentPanel = null;
let agentOn = null;
let agentNote = null;
let agentLog = null;
const STATE_TEXT = {
  waiting: "",
  thinking: "考え中…",
  idle: "Claude が待ち受けると送れます",
  error: "撮影できませんでした。チャットを確認してください",
};

function fit() {
  if (!view) return;
  // Read top to bottom: the image takes what the explanation and the reply bar below leave free.
  const viewport = document.getElementById("viewport");
  const below = document.getElementById("side").offsetHeight + document.getElementById("bar").offsetHeight;
  const room = Math.max(240, innerHeight - below);
  const scale = Math.min(document.getElementById("layout").clientWidth / view.width, room / view.height);
  document.getElementById("stage").style.transform = "scale(" + scale + ")";
  viewport.style.width = view.width * scale + "px";
  viewport.style.height = view.height * scale + "px";
}

function renderButtons() {
  const labels = view ? view.buttons : [];
  const messageBox = Boolean(view && view.messageBox);
  document.getElementById("bar").hidden = labels.length === 0 && !messageBox;
  document.getElementById("compose").hidden = !messageBox;
  document.getElementById("buttons").replaceChildren(...labels.map((label) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => press(label));
    return button;
  }));
  syncControls();
  document.getElementById("bar-state").textContent = STATE_TEXT[buttonState] || "";
  fit();
}

// Draws the "let Claude operate" panel from the last agent state the server sent and the shown view.
// The checkbox always follows the server's state; Claude's click records go in as text, never HTML.
// A monitor capture cannot be handed over, but the switch only locks while the permission is off, so
// the user can always take it back.
function renderAgent() {
  const monitor = Boolean(view && view.target === "monitor");
  agentOn.checked = agent.enabled;
  agentOn.disabled = monitor && !agent.enabled;
  agentPanel.classList.toggle("on", agent.enabled);
  agentNote.textContent = monitor
    ? "画面全体の撮影ではクリックを任せられません"
    : (agent.enabled ? "操作を任せています" : "");
  agentLog.replaceChildren(...agent.clicks.map((record) => {
    const item = document.createElement("li");
    item.textContent = record.time + " " + record.what;
    return item;
  }));
}

// Asks the server to switch the permission. The page is not changed here: it follows the next state
// event. If the request fails, the checkbox goes back to what the server last said and the reason shows.
// Turning it on names the target this page shows, so the server refuses it if the page has just changed.
async function setAgent(enabled) {
  try {
    const body = enabled ? {enabled: true, target: view ? view.targetKey : ""} : {enabled: false};
    const response = await post("/agent", body);
    const result = await response.json();
    if (result.error) {
      renderAgent();
      status(result.error, true);
    }
  } catch (error) {
    renderAgent();
    status("切り替えられませんでした: " + error, true);
  }
}

function syncControls() {
  const enabled = buttonState === "waiting" && !sending;
  for (const button of document.querySelectorAll("#buttons button")) button.disabled = !enabled;
  document.getElementById("refresh").disabled = !enabled;
  document.getElementById("send").disabled = !enabled;
}

function fitMessage() {
  const input = document.getElementById("message");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight + 2, 160) + "px";
  fit();
}

async function sendMessage() {
  const input = document.getElementById("message");
  const text = input.value.trim();
  if (!text || sending) return;
  if (buttonState !== "waiting") {
    document.getElementById("bar-state").textContent = "Claude が待ち受けると送れます";
    return;
  }
  sending = true;
  syncControls();
  try {
    const response = await post("/message", {text: text});
    const result = await response.json();
    if (result.error) {
      document.getElementById("bar-state").textContent = result.error;
    } else {
      input.value = "";
      fitMessage();
    }
  } catch (error) {
    document.getElementById("bar-state").textContent = "送信できませんでした: " + error;
  } finally {
    sending = false;
    syncControls();
  }
}

// Runs send, the POST of a reply to Claude (a button or 更新). The caller has already switched its
// control off, and it stays off until Claude's state changes; if the server refuses the reply or
// sending fails, the controls come back and the reason is shown.
async function sendReply(send) {
  try {
    const response = await send();
    const result = await response.json();
    if (result.error) {
      renderButtons();
      document.getElementById("bar-state").textContent = result.error;
    }
  } catch (error) {
    renderButtons();
    document.getElementById("bar-state").textContent = "送信できませんでした: " + error;
  }
}

function press(label) {
  for (const button of document.querySelectorAll("#buttons button")) button.disabled = true;
  return sendReply(() => post("/press", {button: label}));
}

function refresh() {
  document.getElementById("refresh").disabled = true;
  return sendReply(() => post("/refresh", {}));
}

function status(text, isError) {
  clearTimeout(statusTimer);
  const box = document.getElementById("status");
  box.textContent = text;
  box.className = text ? (isError ? "show error" : "show") : "";
}

function render(next) {
  view = next;
  document.title = "ai-desktop | " + next.title;
  const stage = document.getElementById("stage");
  stage.style.width = next.width + "px";
  stage.style.height = next.height + "px";
  document.getElementById("shot").src =
    "/image/" + encodeURIComponent(next.captureId) + "?t=" + encodeURIComponent(token);
  document.getElementById("annotations").innerHTML = next.html;
  // Annotation HTML must not reach the page's own controls: a label could point at one and a style
  // sheet could move one under the user's next click, so neither is kept.
  for (const label of document.querySelectorAll("#annotations label[for]")) label.removeAttribute("for");
  for (const sheet of document.querySelectorAll("#annotations style")) sheet.remove();
  const side = document.getElementById("side");
  side.textContent = next.explanation || "";
  side.hidden = !next.explanation;
  renderButtons();
  renderAgent();
  status("", false);
  fit();
}

function post(path, body) {
  return fetch(path + "?t=" + encodeURIComponent(token), {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-AI-Desktop-Token": token},
    body: JSON.stringify(body),
  });
}

async function operate(event, double) {
  if (!view || busy) return;
  const rect = document.getElementById("stage").getBoundingClientRect();
  const scale = rect.width / view.width;
  const x = (event.clientX - rect.left) / scale;
  const y = (event.clientY - rect.top) / scale;
  busy = true;
  status(double ? "ダブルクリック中…" : "クリック中…", false);
  try {
    const response = await post("/click", {captureId: view.captureId, x: x, y: y, double: double});
    const result = await response.json();
    if (result.error) {
      status(result.error, true);
    } else {
      status("クリックしました（ページは更新されません）", false);
      statusTimer = setTimeout(() => status("", false), 1500);
    }
  } catch (error) {
    status("操作できませんでした: " + error, true);
  } finally {
    busy = false;
  }
}

addEventListener("DOMContentLoaded", () => {
  agentPanel = document.getElementById("agent");
  agentOn = document.querySelector("#agent input");
  agentNote = document.getElementById("agent-note");
  agentLog = document.getElementById("agent-log");
  const input = document.getElementById("message");
  input.addEventListener("keydown", (event) => {
    // Enter sends, Shift+Enter breaks the line; Enter that confirms an IME conversion does neither.
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    sendMessage();
  });
  input.addEventListener("input", fitMessage);
  document.getElementById("send").addEventListener("click", sendMessage);
  document.getElementById("refresh").addEventListener("click", refresh);
  agentOn.addEventListener("change", () => setAgent(agentOn.checked));
  renderAgent();
  document.getElementById("stage").addEventListener("click", (event) => {
    clearTimeout(pending);
    if (event.target.closest("#annotations .note, #annotations .badge, #annotations a, #annotations button")) {
      status("吹き出しや番号の上はクリックしても送信しません", false);
      statusTimer = setTimeout(() => status("", false), 1500);
      return;
    }
    if (event.detail >= 2) {
      operate(event, true);
      return;
    }
    pending = setTimeout(() => operate(event, false), 300);
  });
  const events = new EventSource("/events?t=" + encodeURIComponent(token));
  events.addEventListener("view", (event) => {
    const next = JSON.parse(event.data);
    render(next);
    post("/ack", {version: next.version});
  });
  events.addEventListener("state", (event) => {
    const next = JSON.parse(event.data);
    buttonState = next.state;
    agent = next.agent;
    renderButtons();
    renderAgent();
  });
  events.addEventListener("error", () => {
    status("サーバーとの接続が切れました。Claude Code のセッションを確認してください。", true);
  });
});
addEventListener("resize", fit);
"""


def content_security_policy(nonce: str) -> str:
    """CSP for the viewer page: only its own nonce'd script, same-origin images and requests."""
    return (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        f"script-src 'nonce-{nonce}'; connect-src 'self'"
    )


def render_shell(nonce: str) -> str:
    """The viewer page skeleton; content arrives over /events and is drawn by the script."""
    return (
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        "<title>ai-desktop</title>\n"
        f"<style>{_CSS}{_VIEWER_CSS}</style>\n"
        f'<script nonce="{nonce}">{_VIEWER_SCRIPT}</script>\n'
        "</head><body>\n"
        f"{_ARROWHEAD}\n"
        '<div id="status"></div>\n'
        '<div id="agent"><label><input type="checkbox"> '
        "Claude に操作を任せる（このウィンドウだけ・左クリック）</label>"
        '<div id="agent-note"></div><ol id="agent-log"></ol></div>\n'
        '<div id="layout">\n'
        '<div id="viewport"><div id="stage">'
        '<img id="shot" alt="">'
        '<div id="annotations"></div>'
        "</div></div>\n"
        '<aside id="side" hidden></aside>\n'
        f'<div id="bar" hidden><button id="refresh" type="button">{REFRESH_LABEL}</button>'
        '<span id="buttons"></span><span id="bar-state"></span>'
        f'<div id="compose" hidden><textarea id="message" rows="1" maxlength="{MAX_MESSAGE_CHARS}" '
        'placeholder="メッセージ（Enter で送信、Shift+Enter で改行）"></textarea>'
        '<button id="send" type="button">送信</button></div></div>\n'
        "</div>\n"
        "</body></html>\n"
    )
