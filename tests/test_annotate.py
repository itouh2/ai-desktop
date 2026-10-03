import base64
import pathlib

from ai_desktop.annotate import render_page, save_page

BOX = '<div class="box" style="left:10px;top:20px;width:30px;height:40px"></div>'
PAGE_ARGS = dict(
    background_jpeg=b"\xff\xd8fake",
    image_width=1568,
    image_height=882,
    html=BOX,
    title="Book1 <Excel>",
    nonce="n0nce",
)


def test_page_has_strict_csp_with_nonce():
    page = render_page(**PAGE_ARGS)
    csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-n0nce'"
    assert f'content="{csp}"' in page
    assert '<script nonce="n0nce">' in page


def test_fit_script_is_in_head_before_claude_html():
    page = render_page(**PAGE_ARGS)
    script = page.index('<script nonce="n0nce">')
    assert script < page.index("</head>")
    assert script < page.index('<div id="annotations">')
    assert "DOMContentLoaded" in page
    assert "html { overflow-y: scroll; }" in page


def test_stage_matches_image_size():
    assert 'id="stage" style="width:1568px;height:882px"' in render_page(**PAGE_ARGS)


def test_background_is_embedded_as_data_uri():
    encoded = base64.b64encode(b"\xff\xd8fake").decode()
    assert f'src="data:image/jpeg;base64,{encoded}"' in render_page(**PAGE_ARGS)


def test_claude_html_is_verbatim_and_title_escaped():
    page = render_page(**PAGE_ARGS)
    assert f'<div id="annotations">{BOX}</div>' in page
    assert "<title>Book1 &lt;Excel&gt;</title>" in page


def test_page_defines_helper_classes_and_arrowhead():
    page = render_page(**PAGE_ARGS)
    for selector in (
        "#annotations .box",
        "#annotations .badge",
        "#annotations .note",
        "#annotations .arrow",
        "#annotations svg.layer",
    ):
        assert selector in page
    assert 'id="arrowhead"' in page


def test_save_page_writes_file(tmp_path):
    directory = tmp_path / "out"
    path = save_page("<html>x</html>", directory)
    assert path.parent == directory
    assert path.name.startswith("annotated-")
    assert path.suffix == ".html"
    assert path.read_text(encoding="utf-8") == "<html>x</html>"


def test_save_page_keeps_only_newest(tmp_path):
    for day in range(1, 5):
        (tmp_path / f"annotated-2000010{day}-000000-000000-aaaaaa.html").write_text("old", encoding="utf-8")
    unrelated = tmp_path / "keep-me.txt"
    unrelated.write_text("x", encoding="utf-8")

    path = save_page("new", tmp_path, keep=3)

    remaining = sorted(p.name for p in tmp_path.glob("annotated-*.html"))
    assert len(remaining) == 3
    assert path.name in remaining
    assert "annotated-20000104-000000-000000-aaaaaa.html" in remaining
    assert "annotated-20000103-000000-000000-aaaaaa.html" in remaining
    assert unrelated.exists()


def test_save_page_survives_locked_old_page(tmp_path, monkeypatch):
    for day in range(1, 5):
        (tmp_path / f"annotated-2000010{day}-000000-000000-aaaaaa.html").write_text("old", encoding="utf-8")
    real_unlink = pathlib.Path.unlink

    def locked_unlink(self, *args, **kwargs):
        if self.name.startswith("annotated-2000"):
            raise PermissionError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", locked_unlink)

    path = save_page("new", tmp_path, keep=3)

    assert path.exists()
