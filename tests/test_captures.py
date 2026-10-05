import pytest

from ai_desktop.captures import CaptureStore, Target
from ai_desktop.imaging import CaptureError


def test_ids_are_sequential():
    store = CaptureStore()
    assert store.add(b"a", {}) == "c1"
    assert store.add(b"b", {}) == "c2"


def test_get_returns_stored_capture():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {"imageWidth": 10})
    assert store.get(capture_id) == (b"jpeg", {"imageWidth": 10, "captureId": "c1"})


def test_store_keeps_its_own_copy_of_meta():
    store = CaptureStore()
    meta = {"imageWidth": 10}
    capture_id = store.add(b"jpeg", meta)
    assert "captureId" not in meta
    meta["imageWidth"] = 99
    first = store.get(capture_id)[1]
    assert first == {"imageWidth": 10, "captureId": capture_id}
    first["imageWidth"] = 77
    first["extra"] = True
    assert store.get(capture_id)[1] == {"imageWidth": 10, "captureId": capture_id}


def test_oldest_capture_is_evicted_past_limit():
    store = CaptureStore(limit=3)
    ids = [store.add(bytes([i]), {}) for i in range(4)]
    assert ids == ["c1", "c2", "c3", "c4"]
    with pytest.raises(CaptureError):
        store.get("c1")
    assert store.get("c4") == (bytes([3]), {"captureId": "c4"})


def test_default_limit_keeps_the_latest_20():
    store = CaptureStore()
    ids = [store.add(bytes([i]), {}) for i in range(21)]
    with pytest.raises(CaptureError):
        store.get(ids[0])
    assert store.get(ids[1])[1] == {"captureId": "c2"}


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


def test_target_is_stored_with_the_capture():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {}, Target("window", 42))
    assert store.target(capture_id) == Target("window", 42)


def test_target_missing_or_unknown_is_an_error():
    store = CaptureStore()
    capture_id = store.add(b"jpeg", {})
    with pytest.raises(CaptureError, match="操作の対象を記録していません"):
        store.target(capture_id)
    with pytest.raises(CaptureError, match="c9"):
        store.target("c9")
