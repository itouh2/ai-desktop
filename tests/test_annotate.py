from ai_desktop.annotate import VIEWER_TITLE_PREFIX, content_security_policy, render_shell


def test_viewer_csp_allows_only_own_script_and_same_origin():
    assert content_security_policy("n0nce") == (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        "script-src 'nonce-n0nce'; connect-src 'self'"
    )


def test_viewer_shell_has_nonce_script_and_empty_stage():
    page = render_shell("n0nce")
    assert '<script nonce="n0nce">' in page
    assert page.index('<script nonce="n0nce">') < page.index("</head>")
    assert '<div id="status"></div>' in page
    assert '<div id="stage"><img id="shot" alt=""><div id="annotations"></div></div>' in page
    assert 'new EventSource("/events?t="' in page
    assert '"X-AI-Desktop-Token": token' in page


def test_success_status_timer_is_cancelled_by_later_statuses():
    page = render_shell("n0nce")
    assert "let statusTimer = null;" in page
    assert "clearTimeout(statusTimer)" in page
    assert "statusTimer = setTimeout(" in page


def test_viewer_shell_keeps_helper_classes_and_title_prefix():
    page = render_shell("n0nce")
    for selector in ("#annotations .box", "#annotations .badge", "#annotations .note", "#annotations .arrow"):
        assert selector in page
    assert 'id="arrowhead"' in page
    assert VIEWER_TITLE_PREFIX == "ai-desktop | "
    assert 'document.title = "ai-desktop | " + next.title' in page


def test_clicks_on_notes_and_badges_are_not_forwarded():
    page = render_shell("n0nce")
    assert 'event.target.closest("#annotations .note, #annotations .badge, #annotations a, #annotations button")' in page
    assert "吹き出しや番号の上はクリックしても送信しません" in page
    assert ".box" not in page.split('event.target.closest("')[1].split('")')[0]


def test_viewer_shell_has_button_bar_and_explanation_panel():
    page = render_shell("n0nce")
    assert (
        '<div id="bar" hidden><button id="refresh" type="button">更新</button>'
        '<span id="buttons"></span><span id="bar-state"></span>'
    ) in page
    assert '<aside id="side" hidden></aside>' in page
    assert "button.textContent = label;" in page
    assert 'side.textContent = next.explanation || "";' in page
    assert 'post("/press", {button: label})' in page
    assert 'events.addEventListener("state"' in page


def test_viewer_shell_has_a_builtin_refresh_button():
    page = render_shell("n0nce")
    assert (
        '<div id="bar" hidden><button id="refresh" type="button">更新</button>'
        '<span id="buttons"></span><span id="bar-state"></span>'
    ) in page
    assert 'post("/refresh", {})' in page
    assert 'document.getElementById("refresh").addEventListener("click", refresh);' in page
    assert 'document.getElementById("refresh").disabled = !enabled;' in page
    assert "#bar #refresh {" in page


def test_viewer_shell_reads_top_to_bottom_image_explanation_then_replies():
    page = render_shell("n0nce")
    body = page.split("<body>")[1]
    assert body.index('id="viewport"') < body.index('id="side"') < body.index('id="bar"')
    # The image shrinks to leave room for the explanation and the reply bar below it.
    assert "innerHeight" in page.split("function fit()")[1].split("}\n")[0]


def test_viewer_shell_has_a_message_box_that_sends_on_enter():
    page = render_shell("n0nce")
    assert '<div id="compose" hidden><textarea id="message" rows="1" maxlength="1000"' in page
    assert 'document.getElementById("compose").hidden = !messageBox;' in page
    assert '<button id="send" type="button">送信</button>' in page
    assert 'post("/message", {text: text})' in page
    # Shift+Enter and the Enter that confirms an IME conversion must not send.
    assert 'event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229' in page
    assert "event.preventDefault();\n    sendMessage();" in page


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
