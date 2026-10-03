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
html { overflow-y: scroll; }
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
function fit() {
  const stage = document.getElementById("stage");
  const viewport = document.getElementById("viewport");
  const scale = document.documentElement.clientWidth / stage.offsetWidth;
  stage.style.transform = "scale(" + scale + ")";
  viewport.style.height = stage.offsetHeight * scale + "px";
}
addEventListener("DOMContentLoaded", fit);
addEventListener("resize", fit);
"""

VIEWER_TITLE_PREFIX = "ai-desktop | "

_VIEWER_CSS = """
#stage { cursor: crosshair; }
#status { position: fixed; top: 12px; right: 12px; z-index: 10; display: none; padding: 8px 14px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.78); color: #fff;
  font: 14px/1.5 system-ui, "Yu Gothic UI", sans-serif; }
#status.show { display: block; }
#status.error { background: #e5484d; }
"""

# The live viewer: receives views over SSE, scales the stage, and posts clicks back.
_VIEWER_SCRIPT = """
const token = new URLSearchParams(location.search).get("t");
let view = null;
let busy = false;
let pending = null;

function fit() {
  if (!view) return;
  const scale = document.documentElement.clientWidth / view.width;
  document.getElementById("stage").style.transform = "scale(" + scale + ")";
  document.getElementById("viewport").style.height = view.height * scale + "px";
}

function status(text, isError) {
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
    status(result.error || "", Boolean(result.error));
  } catch (error) {
    status("操作できませんでした: " + error, true);
  } finally {
    busy = false;
  }
}

addEventListener("DOMContentLoaded", () => {
  document.getElementById("stage").addEventListener("click", (event) => {
    clearTimeout(pending);
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
        '<div id="viewport"><div id="stage">'
        '<img id="shot" alt="">'
        '<div id="annotations"></div>'
        "</div></div>\n"
        "</body></html>\n"
    )


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
        f'<script nonce="{nonce}">{_FIT_SCRIPT}</script>\n'
        "</head><body>\n"
        f"{_ARROWHEAD}\n"
        '<div id="viewport">'
        f'<div id="stage" style="width:{image_width}px;height:{image_height}px">'
        f'<img id="shot" src="data:image/jpeg;base64,{background}" alt="">'
        f'<div id="annotations">{html}</div>'
        "</div></div>\n"
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
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass  # pruning is best-effort; a locked old page must not fail the save
    return path


def open_in_browser(path: Path) -> None:
    """Open with the app associated with .html, normally the default browser."""
    os.startfile(path)
