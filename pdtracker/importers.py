"""Bring client records in from outside: a CSV typed by hand, or an export from any case system.

Most practice management systems (Clio, Docketwise, INSZoom, LollyLaw, eImmigration and
others) can export a CSV, so a column mapping in config is the portable way to sync them.
A direct database or API sync is a class with the same 'rows()' method.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Protocol

from .models import Client

FIELDS = ["name", "category", "chargeability", "priority_date", "case_type", "receipt_number",
          "beneficiary_dob", "responsible_email", "notes", "active", "external_id",
          "petitioner", "case_status", "attorney", "outside_status"]


class ClientFeed(Protocol):
    def rows(self) -> Iterable[dict]: ...


class CsvFeed:
    def __init__(self, path: str | Path, columns: dict | None = None):
        self.path = Path(path)
        self.columns = columns or {}

    def rows(self):
        with self.path.open(newline="", encoding="utf-8-sig") as f:
            for raw in csv.DictReader(f):
                row = {}
                for fld in FIELDS:
                    header = self.columns.get(fld, fld)
                    if header in raw and raw[header] not in (None, ""):
                        row[fld] = raw[header].strip()
                yield row


def sync(store, feed: ClientFeed) -> dict:
    """Add or update clients. Rows with an external_id update the matching client; others are added."""
    existing = {c.external_id: c for c in store.list_clients(include_inactive=True) if c.external_id}
    added, updated, errors = 0, 0, []
    for n, row in enumerate(feed.rows(), start=2):
        try:
            client = Client.from_dict(row)
            # Hand entry may leave blanks, but an import row must be complete, so a stray or half-filled
            # line in a spreadsheet doesn't become a client.
            if not row.get("name") or client.missing:
                raise ValueError("missing " + ", ".join((["name"] if not row.get("name") else []) + client.missing))
        except (ValueError, TypeError, KeyError) as e:
            errors.append(f"row {n}: {e}")
            continue
        match = existing.get(client.external_id) if client.external_id else None
        if match:
            client.id = match.id
            updated += 1
        else:
            added += 1
        store.save_client(client)
    return {"added": added, "updated": updated, "errors": errors}


def export_csv(store, path: str | Path) -> int:
    clients = store.list_clients(include_inactive=True)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id"] + FIELDS)
        w.writeheader()
        for c in clients:
            d = c.to_dict()
            w.writerow({k: d.get(k) for k in ["id"] + FIELDS})
    return len(clients)
