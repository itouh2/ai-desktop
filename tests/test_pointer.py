import pytest
from fakes import BROWSER, FakeControl

from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta
from ai_desktop.pointer import Pointer, Spot

MONITOR_META = build_meta("monitor:1 DISPLAY1", 0, 0, (3200, 1600), (1568, 784), 0.49)
WINDOW_META = build_meta("window:42 Book1 - Excel", -100, 50, (800, 600), (800, 600), 1.0)


@pytest.fixture
def store():
    store = CaptureStore()
    store.add(b"monitor-jpeg", MONITOR_META, Target("monitor", 1))  # c1
    store.add(b"window-jpeg", WINDOW_META, Target("window", 42))  # c2
    return store


@pytest.fixture
def control():
    return FakeControl()


@pytest.fixture
def pointer(store, control):
    return Pointer(store, control, settle_seconds=0)


def test_window_target_is_brought_to_front_and_followed(pointer, control):
    with pointer.at("c2", 10, 20, keep_clear="point") as spot:
        assert spot == Spot(screen=(110, 220), cursor=(5, 6))
    assert control.calls == [
        ("find_window", "ai-desktop | "),
        ("cursor_pos",),
        ("bring_to_front", 42),
        ("window_origin", 42),
        ("restore", BROWSER),
    ]


def test_point_mode_minimizes_only_when_the_point_is_under_the_browser(pointer, control):
    control.browser_rect = (3000, 0, 3840, 1000)  # overlaps the capture, not the point (100, 200)
    with pointer.at("c1", 49, 98, keep_clear="point") as spot:
        assert spot.screen == (100, 200)
    assert not any(call[0] == "minimize" for call in control.calls)


def test_capture_mode_minimizes_when_the_browser_overlaps_the_capture(pointer, control):
    control.browser_rect = (3000, 0, 3840, 1000)
    with pointer.at("c1", 49, 98, keep_clear="capture"):
        assert ("minimize", BROWSER) in control.calls
    assert control.calls[-1] == ("restore", BROWSER)


def test_capture_mode_leaves_a_browser_beside_the_capture(pointer, control):
    control.browser_rect = (3840, 0, 7680, 2160)
    with pointer.at("c1", 49, 98, keep_clear="capture"):
        pass
    assert not any(call[0] == "minimize" for call in control.calls)


def test_browser_that_will_not_minimize_stops_the_operation(pointer, control):
    control.minimize_ok = False
    with pytest.raises(CaptureError, match="最小化できなかった"):
        with pointer.at("c1", 49, 98, keep_clear="capture"):
            pytest.fail("the body must not run")
    assert control.calls[-1] == ("restore", BROWSER)


def test_target_that_will_not_come_to_front_stops_the_operation(pointer, control):
    control.front_ok = False
    with pytest.raises(CaptureError, match="前面に出せませんでした"):
        with pointer.at("c2", 10, 20, keep_clear="point"):
            pytest.fail("the body must not run")
    assert control.calls[-1] == ("restore", BROWSER)


def test_point_outside_the_image_is_rejected_before_anything(pointer, control):
    with pytest.raises(CaptureError, match="画像の外"):
        with pointer.at("c2", 800, 10, keep_clear="point"):
            pass
    assert control.calls == []


def test_the_viewer_browser_itself_is_rejected(pointer, control):
    control.browser = 42
    with pytest.raises(CaptureError, match="同じウィンドウ"):
        with pointer.at("c2", 10, 20, keep_clear="point"):
            pass
    assert not any(call[0] in ("bring_to_front", "minimize") for call in control.calls)


def test_errors_in_the_body_still_restore_and_unlock(pointer, control):
    with pytest.raises(RuntimeError):
        with pointer.at("c2", 10, 20, keep_clear="point"):
            raise RuntimeError("boom")
    assert control.calls[-1] == ("restore", BROWSER)
    assert pointer.lock.acquire(blocking=False)
    pointer.lock.release()


def test_only_one_operation_at_a_time(pointer):
    pointer.lock.acquire()
    try:
        with pytest.raises(CaptureError, match="ほかの操作を実行中"):
            with pointer.at("c2", 10, 20, keep_clear="point"):
                pass
    finally:
        pointer.lock.release()
