"""A stand-in for Cloudflare's D1 binding, backed by an in-memory sqlite3 database and shaped like the JavaScript
API a Python Worker sees (`prepare(sql).bind(*values)` then `.all()` / `.run()`, and `batch([...])`).

`make_d1()` wraps it in the project's `D1` class with identity hooks instead of Pyodide's, so the real SQL and
the real store classes are exercised against the real schema (migrations/0001_init.sql).
"""

import sqlite3
from pathlib import Path

from morphie.d1 import D1

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "0001_init.sql"


class FakeStatement:
    def __init__(self, conn, sql, params=()):
        self._conn, self._sql, self._params = conn, sql, tuple(params)

    def bind(self, *values):
        # D1 rejects `undefined`; this fake rejects the Python equivalents it can't take either.
        for v in values:
            assert isinstance(v, (str, int, float, type(None))), f"unbindable value {v!r}"
        return FakeStatement(self._conn, self._sql, values)

    def all(self):
        cursor = self._conn.execute(self._sql, self._params)
        rows = [dict(r) for r in cursor.fetchall()]
        return {"results": rows, "success": True, "meta": {"changes": 0}}

    def run(self):
        cursor = self._conn.execute(self._sql, self._params)
        return {"results": [], "success": True, "meta": {"changes": max(cursor.rowcount, 0)}}


class FakeD1Binding:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(MIGRATION.read_text())
        self.round_trips = 0

    def prepare(self, sql):
        self.round_trips += 1
        return FakeStatement(self.conn, sql)

    def batch(self, statements):
        # Atomic, like D1: all statements apply or none do.
        try:
            for s in statements:
                s.run()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return [None for _ in statements]


def make_d1(binding=None) -> D1:
    binding = binding or FakeD1Binding()
    return D1(binding, run_sync=lambda x: x, to_python=lambda x: x, to_js=lambda x: x, null=None)
