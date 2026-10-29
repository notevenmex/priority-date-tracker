"""Where clients and bulletins are kept. Every store has the same small interface.

MemoryStore is for tests, SqliteStore for a single office PC, and SharePointStore
(sharepoint.py) for the cloud version. A store for a case management system's database
only needs these methods.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .models import Bulletin, Client, month_key


class Store(Protocol):
    def list_clients(self, include_inactive: bool = False) -> list[Client]: ...
    def get_client(self, client_id: str) -> Client | None: ...
    def save_client(self, client: Client) -> Client: ...
    def delete_client(self, client_id: str) -> None: ...
    def save_bulletin(self, bulletin: Bulletin) -> None: ...
    def get_bulletin(self, month: str) -> Bulletin | None: ...
    def bulletin_months(self) -> list[str]: ...
    def is_processed(self, month: str) -> bool: ...
    def mark_processed(self, month: str) -> None: ...
    def record_statuses(self, month: str, rows: list) -> None: ...


def previous_bulletin(store, month: str) -> Bulletin | None:
    earlier = [m for m in store.bulletin_months() if m < month_key(month)]
    return store.get_bulletin(earlier[-1]) if earlier else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self):
        self.clients: dict[str, Client] = {}
        self.bulletins: dict[str, Bulletin] = {}
        self.processed: set[str] = set()
        self.statuses: dict[str, dict] = {}

    def list_clients(self, include_inactive=False):
        return [c for c in self.clients.values() if include_inactive or c.active]

    def get_client(self, client_id):
        return self.clients.get(client_id)

    def save_client(self, client):
        client.id = client.id or uuid.uuid4().hex[:8]
        self.clients[client.id] = client
        return client

    def delete_client(self, client_id):
        self.clients.pop(client_id, None)

    def save_bulletin(self, bulletin):
        self.bulletins[bulletin.month] = bulletin

    def get_bulletin(self, month):
        return self.bulletins.get(month_key(month))

    def bulletin_months(self):
        return sorted(self.bulletins)

    def is_processed(self, month):
        return month_key(month) in self.processed

    def mark_processed(self, month):
        self.processed.add(month_key(month))

    def record_statuses(self, month, rows):
        for r in rows:
            self.statuses[r.client.id] = {"month": month, "final_action": r.final_action,
                                          "dates_for_filing": r.dates_for_filing}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    status_month TEXT,
    final_action_status TEXT,
    filing_status TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS bulletins (
    month TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    saved_at TEXT,
    processed_at TEXT
);
"""


class SqliteStore:
    """One file holds everything. Back it up with the office's normal file backups."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    def list_clients(self, include_inactive=False):
        sql = "SELECT data FROM clients" + ("" if include_inactive else " WHERE active = 1")
        clients = [Client.from_dict(json.loads(r["data"])) for r in self.db.execute(sql)]
        return sorted(clients, key=lambda c: c.name.lower())

    def get_client(self, client_id):
        row = self.db.execute("SELECT data FROM clients WHERE id = ?", (client_id,)).fetchone()
        return Client.from_dict(json.loads(row["data"])) if row else None

    def save_client(self, client):
        client.id = client.id or uuid.uuid4().hex[:8]
        with self.db:
            self.db.execute(
                "INSERT INTO clients (id, data, active, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, active = excluded.active, "
                "updated_at = excluded.updated_at",
                (client.id, json.dumps(client.to_dict()), int(client.active), _now()))
        return client

    def delete_client(self, client_id):
        with self.db:
            self.db.execute("DELETE FROM clients WHERE id = ?", (client_id,))

    def save_bulletin(self, bulletin):
        with self.db:
            self.db.execute(
                "INSERT INTO bulletins (month, data, saved_at) VALUES (?, ?, ?) "
                "ON CONFLICT(month) DO UPDATE SET data = excluded.data, saved_at = excluded.saved_at",
                (bulletin.month, json.dumps(bulletin.to_dict()), _now()))

    def get_bulletin(self, month):
        row = self.db.execute("SELECT data FROM bulletins WHERE month = ?", (month_key(month),)).fetchone()
        return Bulletin.from_dict(json.loads(row["data"])) if row else None

    def bulletin_months(self):
        return [r["month"] for r in self.db.execute("SELECT month FROM bulletins ORDER BY month")]

    def is_processed(self, month):
        row = self.db.execute("SELECT processed_at FROM bulletins WHERE month = ?", (month_key(month),)).fetchone()
        return bool(row and row["processed_at"])

    def mark_processed(self, month):
        with self.db:
            self.db.execute("UPDATE bulletins SET processed_at = ? WHERE month = ?", (_now(), month_key(month)))

    def record_statuses(self, month, rows):
        with self.db:
            for r in rows:
                self.db.execute(
                    "UPDATE clients SET status_month = ?, final_action_status = ?, filing_status = ? WHERE id = ?",
                    (month, r.final_action, r.dates_for_filing, r.client.id))

    def last_statuses(self) -> dict[str, dict]:
        return {r["id"]: dict(r) for r in self.db.execute(
            "SELECT id, status_month, final_action_status, filing_status FROM clients")}
