"""Minimal Microsoft Graph client: app-only auth, paging and throttling retries."""

from __future__ import annotations

import time

import requests

GRAPH = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Graph {status}: {message}")
        self.status = status


class GraphClient:
    def __init__(self, token_provider, session: requests.Session | None = None, max_retries: int = 4):
        self._token_provider = token_provider
        self._session = session or requests.Session()
        self._max_retries = max_retries

    @classmethod
    def from_settings(cls, tenant_id: str, client_id: str, client_secret: str) -> "GraphClient":
        import msal

        app = msal.ConfidentialClientApplication(
            client_id, authority=f"https://login.microsoftonline.com/{tenant_id}", client_credential=client_secret)

        def token():
            result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            if "access_token" not in result:
                raise GraphError(401, result.get("error_description", "could not get a token"))
            return result["access_token"]

        return cls(token)

    def request(self, method: str, path: str, **kwargs) -> dict:
        url = path if path.startswith("http") else GRAPH + path
        extra_headers = kwargs.pop("headers", {})
        for attempt in range(self._max_retries + 1):
            headers = {"Authorization": f"Bearer {self._token_provider()}", **extra_headers}
            resp = self._session.request(method, url, headers=headers, timeout=60, **kwargs)
            if resp.status_code in (429, 503, 504) and attempt < self._max_retries:
                time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                continue
            if resp.status_code >= 400:
                try:
                    message = resp.json().get("error", {}).get("message", resp.text)
                except ValueError:
                    message = resp.text
                raise GraphError(resp.status_code, message)
            return resp.json() if resp.content else {}
        raise GraphError(429, "throttled too many times")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, json, **kw):
        return self.request("POST", path, json=json, **kw)

    def patch(self, path, json, **kw):
        return self.request("PATCH", path, json=json, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def get_all(self, path: str) -> list[dict]:
        items, url = [], path
        while url:
            page = self.get(url)
            items.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
        return items

    def site_id(self, hostname: str, site_path: str) -> str:
        return self.get(f"/sites/{hostname}:{site_path}")["id"]

    def send_mail(self, sender: str, recipients: list[str], subject: str, html_body: str) -> None:
        self.post(f"/users/{sender}/sendMail", {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
                "toRecipients": [{"emailAddress": {"address": a}} for a in recipients],
            },
            "saveToSentItems": True,
        })
