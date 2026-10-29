"""Cloud store: clients and bulletins live in two SharePoint lists in the office's own tenant.

Staff add and edit clients straight in the SharePoint list (in a browser, Teams or the Lists
app), so the cloud version needs no login screen of its own. The tracker writes each client's
status back into read-only-by-convention columns, which makes the list itself the dashboard.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .categories import CATEGORIES, COUNTRIES
from .graph import GraphClient, GraphError
from .models import Bulletin, Client, month_key, parse_date

# Internal column names have no spaces so they are stable across tenants and languages.
CLIENT_COLUMNS = [
    {"name": "Category", "choice": {"choices": list(CATEGORIES)}},
    {"name": "Chargeability", "choice": {"choices": list(COUNTRIES)}},
    {"name": "PriorityDate", "dateTime": {"format": "dateOnly"}},
    {"name": "CaseType", "text": {}},
    {"name": "ReceiptNumber", "text": {}},
    {"name": "BeneficiaryDOB", "dateTime": {"format": "dateOnly"}},
    {"name": "ResponsibleEmail", "text": {}},
    {"name": "ExternalId", "text": {}},
    {"name": "Active", "boolean": {}, "defaultValue": {"value": "1"}},
    {"name": "Notes", "text": {"allowMultipleLines": True}},
    {"name": "Petitioner", "text": {}},
    {"name": "CaseStatus", "text": {}},
    {"name": "Attorney", "text": {}},
    {"name": "OutsideStatus", "text": {}},
    # Written by the tracker
    {"name": "FinalActionStatus", "text": {}},
    {"name": "FilingStatus", "text": {}},
    {"name": "StatusMonth", "text": {}},
]

BULLETIN_COLUMNS = [
    {"name": "Data", "text": {"allowMultipleLines": True}},
    {"name": "Processed", "boolean": {}},
]


class SharePointStore:
    def __init__(self, graph: GraphClient, site_id: str, clients_list: str, bulletins_list: str,
                 timezone: str = "UTC"):
        self.graph = graph
        self.site = site_id
        self.clients_list = clients_list
        self.bulletins_list = bulletins_list
        self.tz = ZoneInfo(timezone)

    # helpers

    def _items(self, list_name: str) -> list[dict]:
        return self.graph.get_all(f"/sites/{self.site}/lists/{list_name}/items?expand=fields&$top=500")

    def _date(self, value) -> date | None:
        """SharePoint returns date-only columns as a UTC timestamp of local midnight."""
        if not value:
            return None
        text = str(value)
        if "T" in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.astimezone(self.tz).date()
        return parse_date(text)

    @staticmethod
    def _date_out(d: date | None):
        # Noon UTC lands on the same calendar day in every office timezone between UTC-11 and UTC+11.
        return f"{d.isoformat()}T12:00:00Z" if d else None

    def _client_from(self, item: dict) -> Client | None:
        f = item.get("fields", {})
        try:
            return Client(
                id=str(item["id"]), name=f.get("Title", ""), category=f.get("Category", ""),
                chargeability=f.get("Chargeability", "ROW"), priority_date=self._date(f.get("PriorityDate")),
                case_type=f.get("CaseType") or "", receipt_number=f.get("ReceiptNumber") or "",
                beneficiary_dob=self._date(f.get("BeneficiaryDOB")),
                responsible_email=f.get("ResponsibleEmail") or "", notes=f.get("Notes") or "",
                active=bool(f.get("Active", True)), external_id=f.get("ExternalId") or "",
                petitioner=f.get("Petitioner") or "", case_status=f.get("CaseStatus") or "",
                attorney=f.get("Attorney") or "", outside_status=f.get("OutsideStatus") or "")
        except (ValueError, TypeError):
            return None        # half-filled row; skipped rather than failing the whole run

    def _client_fields(self, c: Client) -> dict:
        return {
            "Title": c.name, "Category": c.category, "Chargeability": c.chargeability,
            "PriorityDate": self._date_out(c.priority_date), "CaseType": c.case_type,
            "ReceiptNumber": c.receipt_number, "BeneficiaryDOB": self._date_out(c.beneficiary_dob),
            "ResponsibleEmail": c.responsible_email, "Notes": c.notes, "Active": c.active,
            "ExternalId": c.external_id, "Petitioner": c.petitioner, "CaseStatus": c.case_status,
            "Attorney": c.attorney, "OutsideStatus": c.outside_status,
        }

    # clients

    def list_clients(self, include_inactive=False):
        clients = [c for c in (self._client_from(i) for i in self._items(self.clients_list)) if c]
        return [c for c in clients if include_inactive or c.active]

    def invalid_rows(self) -> list[str]:
        """Titles of list rows the tracker can't read, so staff can fix them."""
        return [i.get("fields", {}).get("Title", f"item {i.get('id')}")
                for i in self._items(self.clients_list) if self._client_from(i) is None]

    def get_client(self, client_id):
        try:
            item = self.graph.get(f"/sites/{self.site}/lists/{self.clients_list}/items/{client_id}?expand=fields")
        except GraphError as e:
            if e.status == 404:
                return None
            raise
        return self._client_from(item)

    def save_client(self, client):
        fields = self._client_fields(client)
        if client.id:
            self.graph.patch(f"/sites/{self.site}/lists/{self.clients_list}/items/{client.id}/fields", fields)
        else:
            item = self.graph.post(f"/sites/{self.site}/lists/{self.clients_list}/items", {"fields": fields})
            client.id = str(item["id"])
        return client

    def delete_client(self, client_id):
        self.graph.delete(f"/sites/{self.site}/lists/{self.clients_list}/items/{client_id}")

    def record_statuses(self, month, rows):
        for r in rows:
            self.graph.patch(f"/sites/{self.site}/lists/{self.clients_list}/items/{r.client.id}/fields", {
                "FinalActionStatus": r.final_action, "FilingStatus": r.dates_for_filing, "StatusMonth": month})

    # bulletins

    def _bulletin_items(self) -> dict[str, dict]:
        return {i["fields"].get("Title"): i for i in self._items(self.bulletins_list)}

    def save_bulletin(self, bulletin):
        existing = self._bulletin_items().get(bulletin.month)
        data = json.dumps(bulletin.to_dict())
        if existing:
            self.graph.patch(f"/sites/{self.site}/lists/{self.bulletins_list}/items/{existing['id']}/fields",
                             {"Data": data})
        else:
            self.graph.post(f"/sites/{self.site}/lists/{self.bulletins_list}/items",
                            {"fields": {"Title": bulletin.month, "Data": data, "Processed": False}})

    def get_bulletin(self, month):
        item = self._bulletin_items().get(month_key(month))
        return Bulletin.from_dict(json.loads(item["fields"]["Data"])) if item else None

    def bulletin_months(self):
        return sorted(m for m in self._bulletin_items() if m)

    def is_processed(self, month):
        item = self._bulletin_items().get(month_key(month))
        return bool(item and item["fields"].get("Processed"))

    def mark_processed(self, month):
        item = self._bulletin_items().get(month_key(month))
        if item:
            self.graph.patch(f"/sites/{self.site}/lists/{self.bulletins_list}/items/{item['id']}/fields",
                             {"Processed": True})


def provision(graph: GraphClient, site_id: str, clients_list: str, bulletins_list: str) -> list[str]:
    """Create the two lists if they don't exist, and add any columns a newer version needs.
    Safe to re-run. Returns what it created."""
    created = []
    for name, columns in ((clients_list, CLIENT_COLUMNS), (bulletins_list, BULLETIN_COLUMNS)):
        try:
            graph.get(f"/sites/{site_id}/lists/{name}")
            have = {c.get("name") for c in graph.get_all(f"/sites/{site_id}/lists/{name}/columns")}
            for col in columns:
                if col["name"] not in have:
                    graph.post(f"/sites/{site_id}/lists/{name}/columns", col)
                    created.append(f"{name}.{col['name']}")
            continue
        except GraphError as e:
            if e.status != 404:
                raise
        graph.post(f"/sites/{site_id}/lists", {
            "displayName": name, "columns": columns, "list": {"template": "genericList"}})
        created.append(name)
    return created


class SharePointInbox:
    """A folder in the site's default document library where staff drop bulletin PDFs."""

    def __init__(self, graph: GraphClient, site_id: str, folder: str, session=None):
        import requests

        self.graph = graph
        self.site = site_id
        self.folder = folder.strip("/")
        self.session = session or requests.Session()

    def pdfs(self) -> list[tuple[str, object]]:
        from urllib.parse import quote
        try:
            items = self.graph.get_all(f"/sites/{self.site}/drive/root:/{quote(self.folder)}:/children")
        except GraphError as e:
            if e.status == 404:
                return []
            raise
        out = []
        for item in items:
            name = item.get("name", "")
            url = item.get("@microsoft.graph.downloadUrl")
            if name.lower().endswith(".pdf") and url:
                # The download URL is pre-authenticated and short-lived; fetch it only when needed.
                out.append((f"sharepoint:{name}:{item.get('eTag', '')}",
                            lambda url=url: self.session.get(url, timeout=60).content))
        return out
