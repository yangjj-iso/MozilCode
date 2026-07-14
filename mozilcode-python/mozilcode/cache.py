"""进程内文件内容缓存。

线程安全的 path -> content 字典，供 ReadFile/WriteFile 等工具减少重复读盘。
"""

from __future__ import annotations

import threading


class FileCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> str | None:
        with self._lock:
            return self._store.get(path)


    def put(self, path: str, content: str) -> None:
        with self._lock:
            self._store[path] = content


    def invalidate(self, path: str) -> None:
        with self._lock:
            self._store.pop(path, None)


    def clear(self) -> None:
        with self._lock:
            self._store.clear()


    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
