"""Recent captures kept in memory, so annotations land on the exact image Claude saw."""

from __future__ import annotations

import threading
from collections import OrderedDict

from ai_desktop.imaging import CaptureError

CAPTURE_LIMIT = 10


class CaptureStore:
    """Background JPEG and metadata of the latest captures, keyed c1, c2, ..."""

    def __init__(self, limit: int = CAPTURE_LIMIT) -> None:
        self._limit = limit
        self._items: OrderedDict[str, tuple[bytes, dict]] = OrderedDict()
        self._next_number = 1
        self._lock = threading.Lock()  # tools may run on parallel worker threads

    def add(self, background_jpeg: bytes, meta: dict) -> str:
        with self._lock:
            capture_id = f"c{self._next_number}"
            self._next_number += 1
            self._items[capture_id] = (background_jpeg, {**meta, "captureId": capture_id})
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
            return capture_id

    def get(self, capture_id: str) -> tuple[bytes, dict]:
        with self._lock:
            item = self._items.get(capture_id)
            if item is None:
                available = ", ".join(self._items) or "なし"
                raise CaptureError(
                    f"capture_id「{capture_id}」は見つかりません"
                    f"（保持しているのは直近 {self._limit} 件: {available}）。"
                    "撮影し直してから指定してください。"
                )
            background_jpeg, meta = item
            return background_jpeg, dict(meta)
