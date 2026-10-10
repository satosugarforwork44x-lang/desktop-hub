"""store.py — Hub全体の保存先（SQLite 1ファイル）。
JSONファイル+ロックの方式で起きた「同時書き込みで壊れる／ロックが残る」問題を避けるため、
SQLite（同時アクセスに強い、ファイル1つのデータベース）を使う。中身は scope/key → JSON値 の単純な表。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # check_same_thread=False: HTTPサーバーの複数スレッドから使うため（排他は self._lock で行う）
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # 書き込み中も読み出しを止めない
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
            " PRIMARY KEY (scope, key))"
        )
        self._conn.commit()

    def get(self, scope: str, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE scope=? AND key=?", (scope, key)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, scope: str, key: str, value: Any) -> None:
        text = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(scope, key, value) VALUES(?,?,?)"
                " ON CONFLICT(scope, key) DO UPDATE SET value=excluded.value",
                (scope, key, text),
            )
            self._conn.commit()

    def delete(self, scope: str, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE scope=? AND key=?", (scope, key))
            self._conn.commit()

    def items(self, scope: str) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM kv WHERE scope=?", (scope,)).fetchall()
        return {k: json.loads(v) for k, v in rows}

    def scoped(self, prefix: str) -> "ScopedStore":
        return ScopedStore(self, prefix)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class ScopedStore:
    """モジュールごとの保存領域。scope名の先頭にモジュールIDを付けて衝突を防ぐ。"""

    def __init__(self, store: Store, prefix: str):
        self._store, self._prefix = store, prefix

    def get(self, scope: str, key: str, default: Any = None) -> Any:
        return self._store.get(f"{self._prefix}.{scope}", key, default)

    def set(self, scope: str, key: str, value: Any) -> None:
        self._store.set(f"{self._prefix}.{scope}", key, value)

    def items(self, scope: str) -> dict[str, Any]:
        return self._store.items(f"{self._prefix}.{scope}")
