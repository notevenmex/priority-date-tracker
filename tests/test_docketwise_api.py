"""Docketwise API connector, against a fake Docketwise (no network)."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from pdtracker import cli, config, docketwise, docketwise_api as api
from pdtracker.stores import MemoryStore

EXAMPLE = Path(__file__).parent.parent / "config" / "office.example.yaml"

# Shaped like Docketwise's documented matter: nested client, priority date fields, receipts.
MATTERS = [
    {"id": 101, "title": "DOE, Jane (I-140)", "description": "EB-2 NIW", "type": "I-140",
     "status": "Approved I-140", "updated_at": "2026-10-01T12:00:00Z", "archived": False,
     "priority_date": "2024-03-15", "priority_date_status": "not current",
     "preference_category": {"id": 7, "name": "EB 2nd: India"},
     "client": {"id": 9, "first_name": "Ann", "last_name": "EMPLOYER"},
     "receipts": [{"number": "IOE0900000001", "status": "approved"}]},
    {"id": 102, "title": "SMITH, Ana (AOS)", "description": "", "type": "AOS - Family",
     "status": "Interview", "priority_date": None, "preference_category": None,
     "client": {"first_name": "Ana", "last_name": "SMITH"}, "archived": False},
    {"id": 103, "title": "Test Person (H-1B)", "type": "H-1B", "client": {"name": "Test Person"}},
]


class Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self.data, self.headers = status, data, headers or {}

    def json(self):
        return self.data


class FakeDocketwise:
    """Two pages of matters, a token endpoint, and a request log."""

    def __init__(self, matters=MATTERS, per_page=2):
        self.matters, self.per_page = matters, per_page
        self.posts, self.gets = [], []
        self.token = "tok-1"
        self.reject_next_get = False

    def post(self, url, data=None, **kw):
        self.posts.append((url, dict(data)))
        if data.get("code") == "bad" or data.get("client_secret") != "s3cret":
            return Resp(401, {"error": "invalid_grant"})
        self.token = f"tok-{len(self.posts) + 1}"
        return Resp(200, {"access_token": self.token, "refresh_token": "ref-new", "expires_in": 15552000,
                          "created_at": int(time.time())})

    def get(self, url, params=None, headers=None, **kw):
        self.gets.append((url, dict(params or {}), headers["Authorization"]))
        if self.reject_next_get or headers["Authorization"] != f"Bearer {self.token}":
            self.reject_next_get = False
            return Resp(401, {})
        page = params["page"]
        chunk = self.matters[(page - 1) * self.per_page: page * self.per_page]
        pages = -(-len(self.matters) // self.per_page)
        info = {"total": len(self.matters), "total_pages": pages, "next_page": page + 1 if page < pages else None}
        return Resp(200, chunk, {"X-Pagination": json.dumps(info)})


@pytest.fixture
def creds(tmp_path):
    settings = api.ApiSettings()
    c = api.Credentials(tmp_path / "dw.json", settings)
    c.set_client("cid", "s3cret")
    return settings, c


def test_matter_json_becomes_export_rows():
    row = api.to_row(MATTERS[0])
    assert row["client"] == "EMPLOYER, Ann" and row["preference_category"] == "EB 2nd: India"
    assert row["priority_date"] == "3/15/2024" and row["updated"] == "10/1/2026" and row["id"] == "101"
    assert row["receipts"] == "IOE0900000001" and row["archived"] == "false"
    # an office can point a field at its own path
    assert api.to_row({"title": "X", "custom": {"cat": "F2A"}}, {"category": "custom.cat"})["preference_category"] == "F2A"


def test_sign_in_with_pasted_address_then_read_every_page(creds):
    settings, c = creds
    dw = FakeDocketwise()
    state = api.new_state()
    url = api.authorize_url(settings, c, state)
    assert url.startswith("https://app.docketwise.com/oauth/authorize?") and "scope=public+write" in url
    assert "getpostman.com" in url and "s3cret" not in url
    code = api.code_from_redirect(f"https://www.getpostman.com/oauth2/callback?code=abc&state={state}", state)
    api.exchange_code(settings, c, code, dw)
    assert dw.posts[0][1]["grant_type"] == "authorization_code" and dw.posts[0][1]["code"] == "abc"
    saved = json.loads(c.path.read_text())
    assert saved["access_token"] == dw.token and saved["refresh_token"] == "ref-new"
    if sys.platform != "win32":
        assert oct(c.path.stat().st_mode & 0o777) == "0o600"

    matters = api.read(api.Client(settings, c, dw))
    assert [g[1]["page"] for g in dw.gets] == [1, 2]                     # followed X-Pagination
    by = {m.applicant: m for m in matters}
    jane = by["DOE, Jane"]
    assert jane.complete and (jane.category, jane.chargeability) == ("EB2", "INDIA")
    assert str(jane.priority_date) == "2024-03-15" and jane.petitioner == "EMPLOYER, Ann"
    assert jane.external_id == "101" and jane.receipt_number == "IOE0900000001"
    assert by["SMITH, Ana"].missing == ["priority date", "preference category", "country of chargeability"]
    assert by["Test Person"].kind == docketwise.OTHER


def test_wrong_state_or_error_is_refused():
    with pytest.raises(api.DocketwiseError, match="different sign-in"):
        api.code_from_redirect("https://x/cb?code=abc&state=other", "mine")
    with pytest.raises(api.DocketwiseError, match="didn't allow"):
        api.code_from_redirect("https://x/cb?error=access_denied", "mine")
    assert api.code_from_redirect("abc123", "mine") == "abc123"


def test_expired_or_revoked_token_refreshes(creds):
    settings, c = creds
    dw = FakeDocketwise()
    c.save_tokens({"access_token": "old", "refresh_token": "ref-1", "expires_in": 10})   # about to run out
    client = api.Client(settings, c, dw)
    client.get("/api/v1/matters", {"page": 1})
    assert dw.posts[-1][1] == {"grant_type": "refresh_token", "refresh_token": "ref-1", "client_id": "cid",
                               "client_secret": "s3cret"}
    dw.reject_next_get = True                                             # revoked mid-way: refresh once, retry
    assert client.get("/api/v1/matters", {"page": 1}).status_code == 200
    assert len(dw.posts) == 2


def test_env_vars_win_and_nothing_secret_is_needed_in_config(tmp_path, monkeypatch):
    settings = api.ApiSettings.from_raw({"client_id_env": "OFFICE_DW_ID", "client_secret_env": "OFFICE_DW_SECRET"})
    c = api.Credentials(tmp_path / "dw.json", settings)
    with pytest.raises(api.DocketwiseError, match="OFFICE_DW_ID"):
        c.need_client()
    monkeypatch.setenv("OFFICE_DW_ID", "env-id")
    monkeypatch.setenv("OFFICE_DW_SECRET", "env-secret")
    c.need_client()
    assert (c.client_id, c.client_secret) == ("env-id", "env-secret")


def test_credentials_live_outside_the_office_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    p = api.credentials_path(api.ApiSettings(), "Garcia & Lee Immigration")
    assert p.name == "docketwise-garcia-lee-immigration.json" and "pdtracker" in p.parts
    assert api.credentials_path(api.ApiSettings(credentials_file=str(tmp_path / "x.json")), "o") == tmp_path / "x.json"


def test_api_sync_updates_clients_first_imported_from_a_csv():
    m = docketwise.read_rows([{"title": "DOE, Jane (I-140)", "type": "I-140", "priority_date": "3/15/2024",
                               "preference_category": "EB 2nd: India"}])
    store = MemoryStore()
    docketwise.sync(store, m)                                          # CSV without ids
    assert store.list_clients()[0].external_id == "docketwise:DOE, Jane|DOE, Jane (I-140)"
    from_api = docketwise.read_rows([api.to_row(MATTERS[0])])
    assert docketwise.sync(store, from_api) == {"added": 0, "updated": 1}
    assert [c.external_id for c in store.list_clients()] == ["101"]


def test_field_names_show_shape_not_data():
    names = api.field_names(MATTERS)
    assert names["priority_date"] == "text" and names["client.last_name"] == "text"
    assert names["receipts"] == "list" and names["receipts[].number"] == "text"
    assert "DOE" not in json.dumps(names) and "IOE0900000001" not in json.dumps(names)


def test_web_page_connects_and_syncs(tmp_path, monkeypatch):
    from pdtracker import webui
    s = config.load(EXAMPLE)
    s.sqlite_path = str(tmp_path / "db.sqlite")
    s.docketwise = {"credentials_file": str(tmp_path / "dw.json")}
    app = webui.App(s)
    page = app.handle("GET", "/import", {})[1]
    assert "Connect to Docketwise" in page and "type='password'" in page
    status, _, to = app.handle("POST", "/docketwise/start",
                               {"token": app.token, "client_id": "cid", "client_secret": "s3cret"})
    assert status == 303 and app.dw_state
    page = app.handle("GET", "/import", {})[1]
    assert "Sign in to Docketwise" in page and "s3cret" not in page and "address" in page

    dw = FakeDocketwise()
    real_session = api._session
    monkeypatch.setattr(api, "_session", lambda session: dw if session is None else real_session(session))
    addr = f"https://www.getpostman.com/oauth2/callback?code=abc&state={app.dw_state}"
    _, _, to = app.handle("POST", "/docketwise/finish", {"token": app.token, "address": addr})
    assert "Connected to Docketwise" in to and not app.dw_state
    assert "Get clients from Docketwise" in app.handle("GET", "/import", {})[1]
    _, _, to = app.handle("POST", "/docketwise/sync", {"token": app.token})
    assert "Added 1" in to and "Also in Docketwise" in to
    assert [c.name for c in app.store.list_clients()] == ["DOE, Jane"]
    _, _, to = app.handle("POST", "/docketwise/disconnect", {"token": app.token})
    assert not (tmp_path / "dw.json").exists()


def test_localhost_redirect_is_caught_by_the_web_page(tmp_path, monkeypatch):
    from pdtracker import webui
    s = config.load(EXAMPLE)
    s.sqlite_path = str(tmp_path / "db.sqlite")
    s.docketwise = {"credentials_file": str(tmp_path / "dw.json"), "redirect_uri": "http://localhost:8765/callback"}
    app = webui.App(s)
    app.handle("POST", "/docketwise/start", {"token": app.token, "client_id": "cid", "client_secret": "s3cret"})
    assert "Finish connecting" not in app.handle("GET", "/import", {})[1]      # nothing to paste
    dw = FakeDocketwise()
    monkeypatch.setattr(api, "_session", lambda session: dw)
    status, _, to = app.handle("GET", f"/callback?code=abc&state={app.dw_state}", {})
    assert status == 303 and "Connected" in to
    assert app.handle("GET", "/callback?code=abc&state=x", {})[0] == 404     # no sign-in pending


def test_cli_sync_and_fields(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "office.yaml"
    cfg.write_text(f"office: {{name: Test}}\nstorage: {{sqlite_path: {tmp_path / 'db.sqlite'}}}\n"
                   f"docketwise: {{credentials_file: {tmp_path / 'dw.json'}}}\n")
    c = api.Credentials(tmp_path / "dw.json", api.ApiSettings())
    c.set_client("cid", "s3cret")
    c.save_tokens({"access_token": "tok-1", "refresh_token": "r"})
    dw = FakeDocketwise()
    monkeypatch.setattr(api, "_session", lambda session: dw)
    cli.main(["-c", str(cfg), "docketwise", "sync"])
    out = capsys.readouterr().out
    assert "Added 1" in out and "1 still need information" in out
    cli.main(["-c", str(cfg), "docketwise", "fields"])
    out = capsys.readouterr().out
    assert "preference_category.name" in out and "DOE" not in out
