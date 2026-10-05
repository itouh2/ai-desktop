"""Recent captures kept in memory, so annotations land on the exact image Claude saw."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from ai_desktop.imaging import CaptureError

CAPTURE_LIMIT = 20


@dataclass(frozen=True)
class Target:
    """What a capture was taken of, so it can be clicked and captured again."""

    kind: Literal["monitor", "window"]
    id: int


class CaptureStore:
    """Background JPEG, metadata and target of the latest captures, keyed c1, c2, ..."""

    def __init__(self, limit: int = CAPTURE_LIMIT) -> None:
        self._limit = limit
        self._items: OrderedDict[str, tuple[bytes, dict, Target | None]] = OrderedDict()
        self._next_number = 1
        self._lock = threading.Lock()  # tools may run on parallel worker threads

    def add(self, background_jpeg: bytes, meta: dict, target: Target | None = None) -> str:
        with self._lock:
            capture_id = f"c{self._next_number}"
            self._next_number += 1
            self._items[capture_id] = (background_jpeg, {**meta, "captureId": capture_id}, target)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
            return capture_id

    def get(self, capture_id: str) -> tuple[bytes, dict]:
        with self._lock:
            background_jpeg, meta, _target = self._item(capture_id)
            return background_jpeg, dict(meta)

    def target(self, capture_id: str) -> Target:
        with self._lock:
            target = self._item(capture_id)[2]
        if target is None:
            raise CaptureError(f"capture_id「{capture_id}」は操作の対象を記録していません。撮影し直してください。")
        return target

    def _item(self, capture_id: str) -> tuple[bytes, dict, Target | None]:
        item = self._items.get(capture_id)
        if item is None:
            available = ", ".join(self._items) or "なし"
            raise CaptureError(
                f"capture_id「{capture_id}」は見つかりません"
                f"（保持しているのは直近 {self._limit} 件: {available}）。"
                "撮影し直してから指定してください。"
            )
        return item
