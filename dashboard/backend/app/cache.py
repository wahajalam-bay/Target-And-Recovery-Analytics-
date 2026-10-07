"""TTL cache with one loader per key, so concurrent requests don't repeat the same query.

If a reload fails (Redshift unreachable, connection limit reached) the previous value is
served instead of an error, and the loader is not tried again for RETRY_AFTER seconds, so
page requests never wait on a failing database while a good copy exists.
"""
import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger("dashboard.cache")
RETRY_AFTER = 30.0


class TTLCache:
    def __init__(self):
        self._data: dict[Any, tuple[float, Any]] = {}
        self._failed_at: dict[Any, float] = {}
        self._locks: dict[Any, threading.Lock] = {}
        self._guard = threading.Lock()

    def get_or_load(self, key, ttl: float, loader: Callable[[], Any]):
        hit = self._data.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            hit = self._data.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            failed = self._failed_at.get(key)
            if hit and failed and time.time() - failed < RETRY_AFTER:
                return hit[1]  # recently failed: serve the last good value, try again later
            try:
                value = loader()
            except Exception as e:  # noqa: BLE001
                self._failed_at[key] = time.time()
                if hit:
                    log.warning("reload of %s failed (%s); serving previous data", key, str(e)[:120])
                    return hit[1]
                raise
            self._failed_at.pop(key, None)
            self._data[key] = (time.time(), value)
            return value

    def touch(self, key):
        """Mark a cached value as current again (the source was checked and has not changed)."""
        hit = self._data.get(key)
        if hit:
            self._data[key] = (time.time(), hit[1])
            self._failed_at.pop(key, None)

    def put(self, key, value):
        self._data[key] = (time.time(), value)
        self._failed_at.pop(key, None)

    def clear(self):
        self._data.clear()
