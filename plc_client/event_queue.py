"""Durable FIFO queue backed by SQLite."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class EventQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS dead_letters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                reason TEXT NOT NULL,
                http_status INTEGER,
                failed_at TEXT NOT NULL
            )""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def put(self, event: dict) -> bool:
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("INSERT OR IGNORE INTO events(event_id, payload) VALUES (?, ?)", (event["event_id"], json.dumps(event)))
            return cursor.rowcount == 1

    def peek(self) -> dict | None:
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute("SELECT payload FROM events ORDER BY id LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def remove(self, event_id: str) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute("DELETE FROM events WHERE event_id = ?", (event_id,))

    def __len__(self) -> int:
        with self._lock, closing(self._connect()) as db, db:
            return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def dead_letter(self, event: dict, reason: str, http_status: int | None = None) -> None:
        """Atomically move an event out of the retry queue; secrets are never accepted."""
        safe_reason = str(reason)[:500]
        with self._lock, closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO dead_letters(event_id, payload, reason, http_status, failed_at) VALUES (?, ?, ?, ?, ?)",
                (event["event_id"], json.dumps(event), safe_reason, http_status, datetime.now(timezone.utc).isoformat()),
            )
            db.execute("DELETE FROM events WHERE event_id = ?", (event["event_id"],))

    def dead_letter_count(self) -> int:
        with self._lock, closing(self._connect()) as db, db:
            return db.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]

    def list_dead_letters(self) -> list[dict]:
        with self._lock, closing(self._connect()) as db, db:
            rows = db.execute("SELECT event_id, payload, reason, http_status, failed_at FROM dead_letters ORDER BY id").fetchall()
        return [
            {"event_id": row[0], "event": json.loads(row[1]), "reason": row[2], "http_status": row[3], "failed_at": row[4]}
            for row in rows
        ]


def _inspect() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Inspect the local SPTS PLC event queue")
    parser.add_argument("queue_path")
    parser.add_argument("--dead-letters", action="store_true")
    args = parser.parse_args()
    queue = EventQueue(args.queue_path)
    if args.dead_letters:
        print(json.dumps(queue.list_dead_letters(), indent=2))
    else:
        print(json.dumps({"queue_depth": len(queue), "dead_letter_count": queue.dead_letter_count()}, indent=2))


if __name__ == "__main__":
    _inspect()
