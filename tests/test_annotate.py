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


def test_viewer_shell_keeps_helper_classes_and_title_prefix():
    page = render_shell("n0nce")
    for selector in ("#annotations .box", "#annotations .badge", "#annotations .note", "#annotations .arrow"):
        assert selector in page
    assert 'id="arrowhead"' in page
    assert VIEWER_TITLE_PREFIX == "ai-desktop | "
    assert 'document.title = "ai-desktop | " + next.title' in page
