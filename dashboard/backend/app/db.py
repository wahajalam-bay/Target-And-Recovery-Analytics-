"""Small thread-safe Redshift connection pool that only allows read queries.

Timeouts: DB_CONNECT_TIMEOUT_SECONDS (fail fast when the cluster is unreachable) and
DB_TIMEOUT_SECONDS for each query (socket read limit and Redshift statement_timeout).
"""
import logging
import queue
import re
import threading
from contextlib import contextmanager

import pandas as pd
import redshift_connector

from .config import settings

log = logging.getLogger("dashboard.db")

# Only plain reads may reach Redshift from this app.
_READ_ONLY = re.compile(r"^\s*(--[^\n]*\n\s*)*(SELECT|WITH)\b", re.IGNORECASE)
_WRITE_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|UNLOAD|VACUUM)\b",
    re.IGNORECASE)


class ConnectionPool:
    def __init__(self, size: int):
        self._size = size
        self._idle: queue.LifoQueue = queue.LifoQueue(maxsize=size)
        self._created = 0
        self._lock = threading.Lock()

    def _connect(self):
        # Short connect timeout: when the cluster is unreachable (VPN off, IP not allowed)
        # we want to fail in seconds and serve the last saved data, not hang for a minute.
        conn = redshift_connector.connect(
            host=settings.host,
            port=settings.port,
            database=settings.database,
            user=settings.user,
            password=settings.password,
            timeout=settings.connect_timeout,
        )
        conn.autocommit = True
        # The driver keeps the connect timeout on the socket for every later read, so a query
        # slower than a few seconds would fail as "read operation timed out" while still running
        # on the cluster. Give queries their own, longer limit...
        try:
            conn._usock.settimeout(settings.query_timeout)  # noqa: SLF001 - no public API for this
        except Exception:  # noqa: BLE001
            log.warning("could not set the query socket timeout")
        # ...and let Redshift abort anything slower than that itself, so a client-side timeout
        # never leaves an orphaned query holding one of this login's few session slots.
        try:
            cur = conn.cursor()
            cur.execute(f"SET statement_timeout TO {int(settings.query_timeout * 1000) - 5000}")
            cur.close()
        except Exception:  # noqa: BLE001 - session setting only; the query still works without it
            log.warning("could not set statement_timeout on the Redshift session")
        return conn

    def _acquire(self):
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            can_create = self._created < self._size
            if can_create:
                self._created += 1
        if can_create:
            try:
                return self._connect()
            except Exception:
                with self._lock:
                    self._created -= 1
                raise
        return self._idle.get(timeout=settings.query_timeout)

    def _discard(self, conn):
        with self._lock:
            self._created -= 1
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - already broken
            pass

    @contextmanager
    def connection(self):
        conn = self._acquire()
        try:
            yield conn
        except (redshift_connector.InterfaceError, redshift_connector.OperationalError, OSError):
            self._discard(conn)
            raise
        except Exception:
            # Statement errors leave the connection usable (autocommit).
            self._idle.put(conn)
            raise
        else:
            self._idle.put(conn)

    def close_all(self):
        while True:
            try:
                self._discard(self._idle.get_nowait())
            except queue.Empty:
                return


pool = ConnectionPool(settings.pool_size)


def read_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run one read-only query and return a DataFrame. Retries once on a dropped connection."""
    if not _READ_ONLY.match(sql) or _WRITE_WORDS.search(sql):
        raise ValueError("Only read-only SELECT queries are allowed")
    for attempt in (1, 2):
        try:
            with pool.connection() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(sql, params or None)
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                finally:
                    cur.close()
            return pd.DataFrame(list(rows) if rows else [], columns=cols)
        except (redshift_connector.InterfaceError, redshift_connector.OperationalError, OSError):
            if attempt == 2:
                raise
            log.warning("Redshift connection dropped, retrying with a fresh one")
