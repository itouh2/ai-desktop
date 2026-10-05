import pytest
from fakes import BROWSER, FakeControl

from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError, build_meta
from ai_desktop.pointer import COVERED_MESSAGE, Pointer, Spot

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
    return Pointer(store, control, settle_seconds=0, focus_seconds=0)


def test_window_target_is_brought_to_front_and_followed(pointer, control):
    with pointer.at("c2", 10, 20, keep_clear="point") as spot:
        assert spot == Spot(screen=(110, 220), cursor=(5, 6))
    assert control.calls == [
        ("find_window", "ai-desktop | "),
        ("cursor_pos",),
        ("foreground_window",),
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


def test_focus_goes_back_to_the_window_that_had_it_and_the_browser_is_left_alone(store):
    control = FakeControl(foreground=999)
    with Pointer(store, control, settle_seconds=0, focus_seconds=0).at("c2", 10, 20, keep_clear="point"):
        pass
    restores = [call for call in control.calls if call[0] == "restore"]
    assert restores == [("restore", 999)]


def test_a_browser_minimized_by_this_call_comes_back_before_focus_returns(store):
    control = FakeControl(foreground=999, browser_rect=(3000, 0, 3840, 1000))
    with Pointer(store, control, settle_seconds=0, focus_seconds=0).at("c1", 49, 98, keep_clear="capture"):
        pass
    restores = [call for call in control.calls if call[0] == "restore"]
    assert restores == [("restore", BROWSER), ("restore", 999)]


def test_a_minimized_browser_that_was_in_front_is_restored_once(store):
    control = FakeControl(foreground=BROWSER, browser_rect=(3000, 0, 3840, 1000))
    with Pointer(store, control, settle_seconds=0, focus_seconds=0).at("c1", 49, 98, keep_clear="capture"):
        pass
    restores = [call for call in control.calls if call[0] == "restore"]
    assert restores == [("restore", BROWSER)]


def test_no_foreground_window_means_nothing_to_give_focus_back_to(store):
    control = FakeControl(foreground=0)
    with Pointer(store, control, settle_seconds=0, focus_seconds=0).at("c2", 10, 20, keep_clear="point"):
        pass
    assert not any(call[0] == "restore" for call in control.calls)


def test_without_return_focus_the_target_stays_in_front(pointer, control):
    control.foreground = 999
    with pointer.at("c2", 10, 20, keep_clear="point", return_focus=False):
        pass
    assert ("bring_to_front", 42) in control.calls
    assert ("restore", 999) not in control.calls


def test_must_hit_target_refuses_a_point_covered_by_another_window(pointer, control):
    control.covered_by = 555  # e.g. an always-on-top window over the target
    with pytest.raises(CaptureError) as refused:
        with pointer.at("c2", 10, 20, keep_clear="point", must_hit_target=True):
            pytest.fail("the body must not run")
    assert str(refused.value) == COVERED_MESSAGE
    assert ("window_at", 110, 220) in control.calls
    assert control.calls[-1] == ("restore", BROWSER)
    assert pointer.lock.acquire(blocking=False)
    pointer.lock.release()


def test_must_hit_target_passes_when_the_target_is_under_the_point(pointer, control):
    with pointer.at("c2", 10, 20, keep_clear="point", must_hit_target=True) as spot:
        assert spot.screen == (110, 220)
    calls = control.calls
    assert calls.index(("bring_to_front", 42)) < calls.index(("window_at", 110, 220))


def test_must_hit_target_is_ignored_for_monitor_targets(pointer, control):
    control.browser_rect = (3840, 0, 7680, 2160)
    with pointer.at("c1", 49, 98, keep_clear="point", must_hit_target=True) as spot:
        assert spot.screen == (100, 200)
    assert not any(call[0] == "window_at" for call in control.calls)


def test_without_return_focus_a_minimized_browser_still_comes_back(pointer, control):
    control.foreground = 999
    control.browser_rect = (3000, 0, 3840, 1000)  # overlaps the monitor capture
    with pointer.at("c1", 49, 98, keep_clear="capture", return_focus=False):
        pass
    assert control.calls[-1] == ("restore", BROWSER)
    assert ("restore", 999) not in control.calls


def test_a_window_brought_to_the_front_gets_time_to_take_focus(store, monkeypatch):
    # Balatro dropped clicks sent 0.25 s after it got focus back (2026-10-05).
    slept = []
    monkeypatch.setattr("ai_desktop.pointer.time.sleep", slept.append)
    control = FakeControl(foreground=999)
    with Pointer(store, control, settle_seconds=0, focus_seconds=0.5).at("c2", 10, 20, keep_clear="point"):
        assert slept == [0.5]


def test_a_window_already_in_front_is_not_kept_waiting(store, monkeypatch):
    slept = []
    monkeypatch.setattr("ai_desktop.pointer.time.sleep", slept.append)
    control = FakeControl(foreground=42)
    with Pointer(store, control, settle_seconds=0, focus_seconds=0.5).at("c2", 10, 20, keep_clear="point"):
        assert slept == []


def test_an_end_point_is_followed_and_checked_like_the_start(pointer, control):
    with pointer.at("c2", 10, 20, keep_clear="point", must_hit_target=True, to=(30, 40)) as spot:
        assert spot == Spot(screen=(110, 220), cursor=(5, 6), end=(130, 240))
    assert ("window_at", 110, 220) in control.calls
    assert ("window_at", 130, 240) in control.calls


def test_an_end_point_outside_the_image_is_rejected_before_anything(pointer, control):
    with pytest.raises(CaptureError, match="画像の外"):
        with pointer.at("c2", 10, 20, keep_clear="point", to=(10, 600)):
            pytest.fail("the body must not run")
    assert control.calls == []


def test_must_hit_target_refuses_an_end_point_covered_by_another_window(pointer, control):
    control.covered_at = {(130, 240): 555}  # the start is clear, the end is under another window
    with pytest.raises(CaptureError) as refused:
        with pointer.at("c2", 10, 20, keep_clear="point", must_hit_target=True, to=(30, 40)):
            pytest.fail("the body must not run")
    assert str(refused.value) == COVERED_MESSAGE
    assert pointer.lock.acquire(blocking=False)
    pointer.lock.release()


def test_without_an_end_point_the_spot_has_none(pointer):
    with pointer.at("c2", 10, 20, keep_clear="point") as spot:
        assert spot.end is None
