import pytest

from ai_desktop import inputs
from ai_desktop.imaging import CaptureError

MOVE_FLAGS = inputs.MOUSEEVENTF_MOVE | inputs.MOUSEEVENTF_ABSOLUTE | inputs.MOUSEEVENTF_VIRTUALDESK


class FakeUser32:
    """Records SendInput batches; the virtual desktop spans two monitors, the left one at x=-1920."""

    def __init__(self, short=False):
        self.batches = []
        self.short = short
        # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN
        self.metrics = {76: -1920, 77: 0, 78: 5760, 79: 2160}

    def SendInput(self, count, array, size):  # noqa: N802 - Win32 name
        self.batches.append([array[i] for i in range(count)])
        return 0 if self.short else count

    def GetSystemMetrics(self, index):  # noqa: N802 - Win32 name
        return self.metrics[index]


@pytest.fixture
def user32(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(inputs, "_user32", fake)
    return fake


def test_move_sends_one_absolute_move_without_buttons(user32):
    inputs.move(100, 200)
    assert len(user32.batches) == 1 and len(user32.batches[0]) == 1
    event = user32.batches[0][0]
    assert event.type == inputs.INPUT_MOUSE
    assert event.u.mi.dwFlags == MOVE_FLAGS


def test_move_normalizes_across_the_virtual_desktop(user32):
    inputs.move(-1920, 0)
    inputs.move(3839, 2159)
    first, last = user32.batches[0][0].u.mi, user32.batches[1][0].u.mi
    assert (first.dx, first.dy) == (0, 0)
    assert (last.dx, last.dy) == (65535, 65535)


@pytest.fixture
def sleeps(monkeypatch):
    slept = []
    monkeypatch.setattr(inputs, "_sleep", slept.append)
    return slept


def test_click_rests_on_the_point_before_pressing(user32, sleeps):
    # Games pick what is under the cursor once a frame; a press in the same frame as the move
    # lands on whatever the cursor was over before (seen in Balatro, 2026-10-05).
    inputs.click(100, 200)
    flags = [[event.u.mi.dwFlags for event in batch] for batch in user32.batches]
    assert flags == [
        [MOVE_FLAGS],
        [MOVE_FLAGS | inputs.MOUSEEVENTF_LEFTDOWN],
        [MOVE_FLAGS | inputs.MOUSEEVENTF_LEFTUP],
    ]
    assert sleeps == [inputs.HOVER_SECONDS, inputs.PRESS_SECONDS]


def test_double_click_presses_twice(user32, sleeps):
    inputs.click(100, 200, double=True)
    assert [len(batch) for batch in user32.batches] == [1, 1, 1, 1, 1]
    assert sleeps == [inputs.HOVER_SECONDS, inputs.PRESS_SECONDS, inputs.DOUBLE_CLICK_GAP_SECONDS, inputs.PRESS_SECONDS]


def test_drag_presses_moves_in_steps_and_releases_at_the_end(user32, sleeps):
    # Games follow the cursor once a frame: the move goes in small steps between press and release.
    inputs.drag((100, 200), (300, 400))
    flags = [[event.u.mi.dwFlags for event in batch] for batch in user32.batches]
    steps = inputs.DRAG_STEPS
    assert flags == (
        [[MOVE_FLAGS], [MOVE_FLAGS | inputs.MOUSEEVENTF_LEFTDOWN]]
        + [[MOVE_FLAGS]] * steps
        + [[MOVE_FLAGS | inputs.MOUSEEVENTF_LEFTUP]]
    )
    assert sleeps == [inputs.HOVER_SECONDS, inputs.PRESS_SECONDS] + [inputs.DRAG_STEP_SECONDS] * steps + [
        inputs.HOVER_SECONDS
    ]


def test_drag_steps_end_exactly_on_the_end_point(monkeypatch, sleeps):
    points = []
    monkeypatch.setattr(inputs, "_mouse_at", lambda x, y, flags: points.append((x, y, flags)) or (x, y, flags))
    monkeypatch.setattr(inputs, "_send", lambda *events: None)
    inputs.drag((100, 200), (300, 401))
    moves = [(x, y) for x, y, flags in points if flags == 0]
    assert moves[0] == (100, 200)  # the hover before the press
    assert moves[-1] == (300, 401)
    assert len(moves) == 1 + inputs.DRAG_STEPS
    assert points[-1] == (300, 401, inputs.MOUSEEVENTF_LEFTUP)


def test_drag_releases_the_button_when_a_move_fails(monkeypatch, sleeps):
    sent = []

    def send(*events):
        event = events[0]
        if event[2] == 0 and len(sent) == 3:  # the second step of the move fails
            raise CaptureError("入力を送れませんでした（Win32 エラー 5）。")
        sent.append(event)

    monkeypatch.setattr(inputs, "_mouse_at", lambda x, y, flags: (x, y, flags))
    monkeypatch.setattr(inputs, "_send", send)
    with pytest.raises(CaptureError):
        inputs.drag((100, 200), (300, 400))
    assert sent[-1][2] == inputs.MOUSEEVENTF_LEFTUP


def test_tap_alt_presses_and_releases_alt(user32):
    inputs.tap_alt()
    down, up = user32.batches[0]
    assert (down.type, down.u.ki.wVk, down.u.ki.dwFlags) == (inputs.INPUT_KEYBOARD, inputs.VK_MENU, 0)
    assert (up.u.ki.wVk, up.u.ki.dwFlags) == (inputs.VK_MENU, inputs.KEYEVENTF_KEYUP)


def test_short_send_is_an_error(monkeypatch):
    monkeypatch.setattr(inputs, "_user32", FakeUser32(short=True))
    with pytest.raises(CaptureError, match="入力を送れませんでした"):
        inputs.move(100, 200)
