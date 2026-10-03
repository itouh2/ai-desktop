import pytest

from ai_desktop.imaging import CaptureError, WindowInfo, select_window


def window(id: int, title: str) -> WindowInfo:
    return WindowInfo(
        id=id, title=title, app="app.exe", x=0, y=0, width=800, height=600,
        minimized=False, focused=False,
    )


WINDOWS = [
    window(1, "Book1 - Excel"),
    window(2, "Inbox - Outlook"),
    window(3, "ChatGPT - Google Chrome"),
    window(4, "ChatGPT"),
    window(5, "Claude - Google Chrome"),
]


def test_no_match_raises_with_hint():
    with pytest.raises(CaptureError, match="list_windows"):
        select_window(WINDOWS, "Photoshop")


def test_single_match_is_returned():
    assert select_window(WINDOWS, "excel").id == 1


def test_match_ignores_case():
    assert select_window(WINDOWS, "OUTLOOK").id == 2


def test_exact_title_wins_among_several_matches():
    assert select_window(WINDOWS, "chatgpt").id == 4


def test_ambiguous_match_lists_candidates():
    with pytest.raises(CaptureError) as error:
        select_window(WINDOWS, "Google Chrome")
    message = str(error.value)
    assert "window_id" in message
    assert "id=3" in message
    assert "id=5" in message
    assert "ChatGPT - Google Chrome" in message


def test_identical_titles_are_ambiguous():
    twins = [window(1, "ChatGPT"), window(2, "ChatGPT"), window(3, "Notes")]
    with pytest.raises(CaptureError) as error:
        select_window(twins, "ChatGPT")
    message = str(error.value)
    assert "id=1" in message
    assert "id=2" in message
    assert "id=3" not in message


def test_candidate_list_is_capped():
    many = [window(i, f"Untitled {i}") for i in range(25)]
    with pytest.raises(CaptureError) as error:
        select_window(many, "Untitled")
    message = str(error.value)
    assert "id=19" in message
    assert "id=20" not in message
    assert "ほか 5 件" in message
