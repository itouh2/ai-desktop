import pytest

from ai_desktop.captures import CaptureStore
from ai_desktop.imaging import CaptureError


def test_ids_are_sequential():
    store = CaptureStore()
    assert store.add(b"a", {}) == "c1"
    assert store.add(b"b", {}) == "c2"


def test_get_returns_stored_capture():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {"imageWidth": 10})
    assert store.get(capture_id) == (b"jpeg", {"imageWidth": 10})


def test_oldest_capture_is_evicted_past_limit():
    store = CaptureStore(limit=3)
    ids = [store.add(bytes([i]), {}) for i in range(4)]
    assert ids == ["c1", "c2", "c3", "c4"]
    with pytest.raises(CaptureError):
        store.get("c1")
    assert store.get("c4") == (bytes([3]), {})


def test_unknown_id_lists_available_ids():
    store = CaptureStore()
    store.add(b"a", {})
    store.add(b"b", {})
    with pytest.raises(CaptureError) as error:
        store.get("c9")
    message = str(error.value)
    assert "c9" in message
    assert "c1, c2" in message
    assert "撮影し直して" in message
