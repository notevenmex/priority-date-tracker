"""Read matters straight from Docketwise's API instead of a CSV export.

Docketwise gives each firm an OAuth 2.0 client ID and secret on request (team@docketwise.com).
Signing in is the authorization-code flow:

  1. `pdtrack docketwise connect` (or Import clients > Connect to Docketwise) asks for the ID and
     secret, saves them on this computer only, and opens Docketwise's sign-in page.
  2. Docketwise sends the browser to the redirect URI registered for the firm with a one-time code.
     Docketwise registers Postman's callback by default, so the person copies the address they land
     on and pastes it back. A localhost redirect URI can be registered instead to skip that step.
  3. The code is swapped for an access token (good for 180 days) and a refresh token.

Matters then go through the same sorting as a CSV export (docketwise.read_rows): only green card
matters that wait on the Visa Bulletin are kept, and anything missing goes on the worklist.

Nothing here is office-specific. The client ID and secret come from environment variables when set
(DOCKETWISE_CLIENT_ID / DOCKETWISE_CLIENT_SECRET by default), otherwise from the per-user credentials
file written by `connect`. That file sits in the user's app data folder, not the office folder, so it
isn't synced to OneDrive or SharePoint with the office's other files.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from . import docketwise

DEFAULT_BASE_URL = "https://app.docketwise.com"
DEFAULT_REDIRECT_URI = "https://www.getpostman.com/oauth2/callback"
DEFAULT_SCOPE = "public write"
REFRESH_MARGIN = 7 * 24 * 3600          # refresh a week before the 180-day token runs out


class DocketwiseError(RuntimeError):
    pass


@dataclass
class ApiSettings:
    base_url: str = DEFAULT_BASE_URL
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scope: str = DEFAULT_SCOPE
    client_id_env: str = "DOCKETWISE_CLIENT_ID"
    client_secret_env: str = "DOCKETWISE_CLIENT_SECRET"
    credentials_file: str = ""          # default: the user's app data folder, one file per office
    matters_path: str = "/api/v1/matters"
    per_page: int = 200                 # Docketwise's maximum
    max_pages: int = 500
    # Our field -> dotted path in a matter's JSON, for when Docketwise names something differently
    # than the defaults below. `pdtrack docketwise fields` lists the names a firm's matters really have.
    fields: dict = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict | None) -> "ApiSettings":
        raw = raw or {}
        s = cls()
        for key in ("base_url", "redirect_uri", "scope", "client_id_env", "client_secret_env",
                    "credentials_file", "matters_path"):
            if raw.get(key):
                setattr(s, key, str(raw[key]))
        for key in ("per_page", "max_pages"):
            if raw.get(key):
                setattr(s, key, int(raw[key]))
        s.fields = dict(raw.get("fields") or {})
        s.base_url = s.base_url.rstrip("/")
        return s

    @property
    def authorize_url(self) -> str:
        return self.base_url + "/oauth/authorize"

    @property
    def token_url(self) -> str:
        return self.base_url + "/oauth/token"


def _app_data() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "pdtracker"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "pdtracker"


def credentials_path(api: ApiSettings, office_name: str) -> Path:
    if api.credentials_file:
        return Path(api.credentials_file).expanduser()
    slug = re.sub(r"[^a-z0-9]+", "-", office_name.lower()).strip("-") or "office"
    return _app_data() / f"docketwise-{slug}.json"


class Credentials:
    """Client ID, secret and tokens. Env vars win over the file for the ID and secret."""

    def __init__(self, path: Path, api: ApiSettings):
        self.path, self.api = path, api
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise DocketwiseError(f"Couldn't read the saved Docketwise sign-in at {path}: {e}")

    @property
    def client_id(self) -> str:
        return os.environ.get(self.api.client_id_env) or self.data.get("client_id", "")

    @property
    def client_secret(self) -> str:
        return os.environ.get(self.api.client_secret_env) or self.data.get("client_secret", "")

    @property
    def connected(self) -> bool:
        return bool(self.data.get("access_token") or self.data.get("refresh_token"))

    def set_client(self, client_id: str, client_secret: str) -> None:
        if client_id:
            self.data["client_id"] = client_id.strip()
        if client_secret:
            self.data["client_secret"] = client_secret.strip()

    def save_tokens(self, token: dict) -> None:
        if not token.get("access_token"):
            raise DocketwiseError("Docketwise didn't send an access token.")
        self.data["access_token"] = token["access_token"]
        if token.get("refresh_token"):
            self.data["refresh_token"] = token["refresh_token"]
        created = int(token.get("created_at") or time.time())
        self.data["expires_at"] = created + int(token.get("expires_in") or 180 * 24 * 3600)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        # Readable by this user only (Windows keeps files under LOCALAPPDATA private to the user already).
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def forget(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self.data = {}

    def need_client(self) -> None:
        if not self.client_id or not self.client_secret:
            raise DocketwiseError("The Docketwise client ID and secret aren't set. Run 'pdtrack docketwise connect' "
                                  f"or set {self.api.client_id_env} and {self.api.client_secret_env}.")


# --- Signing in ---------------------------------------------------------------------------------

def authorize_url(api: ApiSettings, creds: Credentials, state: str) -> str:
    creds.need_client()
    return api.authorize_url + "?" + urlencode({
        "client_id": creds.client_id, "redirect_uri": api.redirect_uri, "response_type": "code",
        "scope": api.scope, "state": state})


def new_state() -> str:
    return secrets.token_urlsafe(16)


def code_from_redirect(pasted: str, state: str) -> str:
    """Pull the one-time code out of the address the browser landed on (or accept the bare code)."""
    text = pasted.strip()
    if not text:
        raise DocketwiseError("Paste the address from your browser's address bar after signing in.")
    if "?" not in text and "=" not in text and "/" not in text:
        return text                                       # just the code
    q = parse_qs(urlparse(text).query)
    if q.get("error"):
        raise DocketwiseError(f"Docketwise didn't allow the sign-in: {q.get('error_description', q['error'])[0]}")
    if state and q.get("state") and q["state"][0] != state:
        raise DocketwiseError("That address is from a different sign-in attempt. Start the connection again.")
    code = (q.get("code") or [""])[0]
    if not code:
        raise DocketwiseError("That address has no sign-in code in it. Copy the whole address after signing in.")
    return code


def is_local_redirect(api: ApiSettings) -> bool:
    u = urlparse(api.redirect_uri)
    return u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")


def wait_for_code(api: ApiSettings, state: str, timeout: int = 300) -> str:
    """Catch Docketwise's redirect on a localhost redirect URI (when the firm registered one)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    u = urlparse(api.redirect_uri)
    got: dict = {}

    class Once(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != (u.path or "/"):
                self.send_error(404)
                return
            got["url"] = self.path
            body = b"<p>Connected. You can close this tab and go back to the Priority Date Tracker.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer(("127.0.0.1", u.port or 80), Once)
    except OSError:
        raise DocketwiseError(f"Port {u.port} is busy (is the tracker's web page open?). Connect from the web page "
                              "instead: Import clients, then Connect to Docketwise.")
    server.timeout = timeout
    with server:
        deadline = time.time() + timeout
        while "url" not in got and time.time() < deadline:
            server.handle_request()
    if "url" not in got:
        raise DocketwiseError("Timed out waiting for the Docketwise sign-in. Try connecting again.")
    return code_from_redirect(got["url"], state)


def exchange_code(api: ApiSettings, creds: Credentials, code: str, session=None) -> None:
    creds.need_client()
    creds.save_tokens(_token_request(api, session, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": api.redirect_uri,
        "client_id": creds.client_id, "client_secret": creds.client_secret}))


def refresh(api: ApiSettings, creds: Credentials, session=None) -> None:
    if not creds.data.get("refresh_token"):
        raise DocketwiseError("The Docketwise sign-in has run out. Connect to Docketwise again.")
    creds.need_client()
    creds.save_tokens(_token_request(api, session, {
        "grant_type": "refresh_token", "refresh_token": creds.data["refresh_token"],
        "client_id": creds.client_id, "client_secret": creds.client_secret}))


def _session(session):
    if session is not None:
        return session
    import requests
    return requests.Session()


def _token_request(api: ApiSettings, session, form: dict) -> dict:
    r = _session(session).post(api.token_url, data=form, headers={"Accept": "application/json"}, timeout=30)
    if r.status_code >= 400:
        try:
            detail = r.json().get("error_description") or r.json().get("error") or ""
        except ValueError:
            detail = ""
        raise DocketwiseError(f"Docketwise refused the sign-in ({r.status_code}). {detail}".strip())
    return r.json()


# --- Reading ------------------------------------------------------------------------------------

class Client:
    def __init__(self, api: ApiSettings, creds: Credentials, session=None):
        self.api, self.creds = api, creds
        self.session = _session(session)

    def _token(self) -> str:
        if not self.creds.connected:
            raise DocketwiseError("Not connected to Docketwise yet. Run 'pdtrack docketwise connect' first.")
        if not self.creds.data.get("access_token") or \
                self.creds.data.get("expires_at", 0) - time.time() < REFRESH_MARGIN:
            refresh(self.api, self.creds, self.session)
        return self.creds.data["access_token"]

    def get(self, path: str, params: dict | None = None):
        url = path if path.startswith("http") else self.api.base_url + path
        for attempt in (1, 2):
            r = self.session.get(url, params=params, timeout=60, headers={
                "Authorization": f"Bearer {self._token()}", "Accept": "application/json"})
            if r.status_code == 401 and attempt == 1 and self.creds.data.get("refresh_token"):
                refresh(self.api, self.creds, self.session)      # revoked or expired early
                continue
            if r.status_code == 429 and attempt == 1:
                time.sleep(min(60, int(r.headers.get("Retry-After") or 10)))
                continue
            if r.status_code >= 400:
                raise DocketwiseError(f"Docketwise answered {r.status_code} for {path}.")
            return r
        raise DocketwiseError(f"Docketwise kept refusing {path}. Connect to Docketwise again.")

    def pages(self, path: str):
        """Every record of an index action. Docketwise pages at 200 and describes the paging in X-Pagination."""
        page = 1
        while page and page <= self.api.max_pages:
            r = self.get(path, {"page": page, "per_page": self.api.per_page})
            body = r.json()
            items = body if isinstance(body, list) else next(
                (body[k] for k in ("data", "matters", "contacts", "results") if isinstance(body.get(k), list)), [])
            yield from items
            info = _pagination(r.headers.get("X-Pagination"))
            if info:
                nxt = info.get("next_page")
                total = info.get("total_pages")
                page = int(nxt) if nxt else (page + 1 if total and page < int(total) else 0)
            else:
                page = page + 1 if len(items) >= self.api.per_page else 0

    def matters(self) -> list[dict]:
        return list(self.pages(self.api.matters_path))


def _pagination(header: str | None) -> dict:
    if not header:
        return {}
    try:
        info = json.loads(header)
        return info if isinstance(info, dict) else {}
    except ValueError:
        return {}


# --- From matter JSON to the rows docketwise.read_rows understands -------------------------------

# Where each export column usually lives in a matter's JSON. The first path that has a value wins;
# ApiSettings.fields puts an office's own path in front.
PATHS = {
    "id": ["id"],
    "title": ["title", "name"],
    "client": ["client", "client_name", "contact"],
    "applicant": ["beneficiary", "applicant", "beneficiary_name", "applicant_name"],
    "description": ["description"],
    "type": ["matter_type", "type", "case_type"],
    "status": ["status", "matter_status"],
    "priority_date_status": ["priority_date_status"],
    "final_action_date_status": ["final_action_date_status"],
    "assignees": ["assignees", "users", "attorneys"],
    "priority_date": ["priority_date"],
    "preference_category": ["preference_category", "preference_category_name", "category"],
    "country_of_chargeability": ["country_of_chargeability", "chargeability",
                                 "beneficiary.country_of_birth", "client.country_of_birth"],
    "receipts": ["receipts", "uscis_receipts"],
    "receipt_number": ["receipt_number"],
    "archived": ["archived"],
    "updated": ["updated_at", "updated"],
}

# Our docketwise.ALIASES field name -> the PATHS key whose value fills it, for config overrides.
_FIELD_TO_COLUMN = {"title": "title", "client": "client", "applicant": "applicant", "description": "description",
                    "type": "type", "status": "status", "outside_status": "priority_date_status",
                    "attorney": "assignees", "priority_date": "priority_date", "category": "preference_category",
                    "chargeability": "country_of_chargeability", "receipt_number": "receipt_number",
                    "external_id": "id", "archived": "archived", "updated": "updated", "receipts": "receipts"}


def _dig(obj, path: str):
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _text(value) -> str:
    """Flatten whatever Docketwise sends (a name, a nested contact, a list of users) into export text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value).strip()
    if isinstance(value, list):
        return ", ".join(t for t in (_text(v) for v in value) if t)
    if isinstance(value, dict):
        for key in ("name", "title", "full_name", "display_name", "label"):
            if value.get(key):
                return _text(value[key])
        first, last = value.get("first_name") or "", value.get("last_name") or ""
        if first or last:
            return f"{last}, {first}".strip(", ") if last and first else (last or first)
        for key in ("number", "receipt_number", "value"):
            if value.get(key):
                return _text(value[key])
    return ""


def _iso(text: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text or "")
    return f"{int(m[2])}/{int(m[3])}/{m[1]}" if m else text


def to_row(matter: dict, overrides: dict | None = None) -> dict:
    """One matter's JSON as a row with Docketwise's export column names."""
    overrides = overrides or {}
    row = {}
    for column, paths in PATHS.items():
        custom = [overrides[f] for f, c in _FIELD_TO_COLUMN.items() if c == column and f in overrides]
        for path in custom + paths:
            text = _text(_dig(matter, path))
            if text:
                row[column] = text
                break
    for column in ("priority_date", "updated"):
        if column in row:
            row[column] = _iso(row[column])       # read_rows takes US dates; the API sends ISO
    if "receipts" in row and not re.search(r"\b[A-Z]{3}\d{10}\b", row["receipts"]):
        del row["receipts"]
    return row


def read(client: Client, overrides: dict | None = None) -> list[docketwise.Matter]:
    return docketwise.read_rows((to_row(m, overrides) for m in client.matters()), first_row=1)


def field_names(matters: list[dict]) -> dict[str, str]:
    """Every field path seen in the matters, with its JSON type. No values, so it's safe to share."""
    seen: dict[str, str] = {}

    def walk(obj, prefix):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            seen.setdefault(prefix, "list")
            for v in obj[:3]:
                walk(v, prefix + "[]")
        else:
            kind = {bool: "true/false", int: "number", float: "number", str: "text"}.get(type(obj), "empty")
            if seen.get(prefix) in (None, "empty"):
                seen[prefix] = kind

    for m in matters:
        walk(m, "")
    return dict(sorted(seen.items()))
