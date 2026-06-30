from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS title_resolver_cache (
    cache_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_title_resolver_cache_expires_at
ON title_resolver_cache(expires_at);
"""


class TitleResolverCache:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        return con

    def get(self, cache_key: str) -> dict[str, Any] | None:
        now = time.time()
        con = self._connect()
        try:
            row = con.execute(
                "SELECT * FROM title_resolver_cache WHERE cache_key=? AND expires_at>?",
                (cache_key, now),
            ).fetchone()
            con.execute(
                "DELETE FROM title_resolver_cache WHERE cache_key=? AND expires_at<=?",
                (cache_key, now),
            )
            con.commit()
        finally:
            con.close()
        if not row:
            return None
        payload = json.loads(str(row["payload_json"]))
        if isinstance(payload, dict):
            payload.setdefault("cache", {})
            payload["cache"]["hit"] = True
        return payload

    def set(self, cache_key: str, status: str, payload: dict[str, Any], ttl_sec: int) -> None:
        if ttl_sec <= 0:
            return
        now = time.time()
        cached = dict(payload)
        cached.setdefault("cache", {})
        cached["cache"]["hit"] = False
        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO title_resolver_cache(cache_key, status, payload_json, created_at, expires_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (
                    cache_key,
                    status,
                    json.dumps(cached, ensure_ascii=False, default=str),
                    now,
                    now + ttl_sec,
                ),
            )
            con.execute("DELETE FROM title_resolver_cache WHERE expires_at<=?", (now,))
            con.commit()
        finally:
            con.close()
