"""SQLite 落库：把采集结果持久化、去重、变成可查询的数据资产。

「工具 → 产品」的关键一步：工具只打印结果，产品把结果沉淀成数据。这里：
- items 表 —— 归一化后的每一条记录，按 (source, platform, native_id) 唯一约束去重，
  重复采集同一批数据不会产生重复行。
- runs 表 —— 每次采集任务的元信息（目标、引擎、条数、token 成本、耗时），
  便于对账成本与排查问题。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sources.base import CollectedItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    platform     TEXT NOT NULL,
    target       TEXT NOT NULL,
    success      INTEGER NOT NULL,
    n_items      INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    duration_s   REAL NOT NULL DEFAULT 0,
    errors       TEXT NOT NULL DEFAULT '[]',
    started_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    platform     TEXT NOT NULL,
    native_id    TEXT NOT NULL,
    url          TEXT NOT NULL DEFAULT '',
    data         TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE(source, platform, native_id)
);
"""


class Store:
    """线程安全的 SQLite 存储（FastAPI 并发下复用同一连接）。"""

    def __init__(self, path: str):
        self.path = path
        # SQLite 不会自动建父目录，先确保目录存在
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
        return self._conn

    def save_run(self, run: dict[str, Any]) -> None:
        conn = self._connect()
        with self._lock:
            conn.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, source, platform, target, success, n_items,
                    total_tokens, duration_s, errors, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run["run_id"],
                    run["source"],
                    run["platform"],
                    run["target"],
                    int(run.get("success", False)),
                    int(run.get("n_items", 0)),
                    int(run.get("total_tokens", 0)),
                    float(run.get("duration_s", 0.0)),
                    json.dumps(run.get("errors", []), ensure_ascii=False),
                    run.get("started_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def upsert_items(self, items: list[CollectedItem]) -> int:
        """写入并去重，返回新增条数。"""
        if not items:
            return 0
        conn = self._connect()
        inserted = 0
        with self._lock:
            for it in items:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO items
                       (source, platform, native_id, url, data, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        it.source,
                        it.platform,
                        it.native_id,
                        it.url,
                        json.dumps(it.data, ensure_ascii=False),
                        it.collected_at,
                    ),
                )
                inserted += cur.rowcount
            conn.commit()
        return inserted

    def query(self, source: str | None = None, platform: str | None = None,
              limit: int = 100) -> list[dict]:
        conn = self._connect()
        sql = "SELECT source, platform, native_id, url, data, collected_at FROM items"
        conds, args = [], []
        if source:
            conds.append("source = ?")
            args.append(source)
        if platform:
            conds.append("platform = ?")
            args.append(platform)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        rows = conn.execute(sql, args).fetchall()
        return [
            {
                "source": r[0],
                "platform": r[1],
                "native_id": r[2],
                "url": r[3],
                "data": json.loads(r[4]),
                "collected_at": r[5],
            }
            for r in rows
        ]

    def counts(self) -> dict[str, int]:
        conn = self._connect()
        return {
            "items": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
