"""A small web page on the office PC for entering clients and bulletins. Standard library only.

It listens on 127.0.0.1, so only the machine it runs on can open it. Every form carries a
per-run token, and requests whose Host isn't localhost are refused.
"""

from __future__ import annotations

import html
import secrets
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import dashboard, render, tracker
from .categories import CATEGORIES, COUNTRIES
from .evaluate import IS_CURRENT
from .models import CHART_LABELS, CHARTS, Bulletin, Client, cutoff_label, cutoff_str, month_key
from .stores import previous_bulletin

STATUS_CLASS = {IS_CURRENT: "ok"}


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


class App:
    def __init__(self, settings):
        self.s = settings
        self.store = tracker.store_for(settings)
        self.token = secrets.token_urlsafe(16)
        self.lock = threading.Lock()

    def page(self, title: str, body: str, message: str = "", active: str = "", kind: str = "") -> str:
        return dashboard.shell(title, self.s.office_name, body, active, message, kind)

    @staticmethod
    def panel(heading: str, inner: str) -> str:
        return (f"<section class='panel'><div class='head'><h2>{_e(heading)}</h2></div>"
                f"<div class='body' style='padding-top:14px'>{inner}</div></section>")

    def _hidden(self) -> str:
        return f'<input type="hidden" name="token" value="{self.token}">'

    def _select(self, name, options: dict, selected="") -> str:
        opts = "".join(f'<option value="{_e(k)}"{" selected" if k == selected else ""}>{_e(k)} · {_e(v)}</option>'
                       for k, v in options.items())
        return f'<select name="{name}">{opts}</select>'

    def client_form(self, c: Client | None = None) -> str:
        v = c.to_dict() if c else {}
        action = f"/client/{_e(c.id)}" if c else "/client"

        def field(label, name, kind="text", required=False):
            req = " required" if required else ""
            return f'<label>{label}<input type="{kind}" name="{name}" value="{_e(v.get(name) or "")}"{req}></label>'

        return (f'<form method="post" action="{action}">{self._hidden()}<div class="form-grid">'
                + field("Client name", "name", required=True)
                + f'<label>Category{self._select("category", CATEGORIES, v.get("category", "F2A"))}</label>'
                + f'<label>Chargeability{self._select("chargeability", COUNTRIES, v.get("chargeability", "ROW"))}</label>'
                + field("Priority date", "priority_date", "date", True)
                + field("Beneficiary date of birth (optional)", "beneficiary_dob", "date")
                + field("Case type", "case_type") + field("Receipt number", "receipt_number")
                + field("Responsible attorney email", "responsible_email", "email")
                + f'<label>Notes<textarea name="notes" rows="2">{_e(v.get("notes") or "")}</textarea></label>'
                + "</div><div><button>Save client</button></div></form>")

    def home(self, message="") -> str:
        months = self.store.bulletin_months()
        latest = self.store.get_bulletin(months[-1]) if months else None
        analysis = tracker.analyze(self.store, self.s, latest) if latest else None
        inactive = [c for c in self.store.list_clients(include_inactive=True) if not c.active]
        kind = ""
        nxt = tracker.next_month(date.today())
        if (not message and self.s.reminder_day and date.today().day >= self.s.reminder_day
                and nxt not in months):
            message = (f"The {dashboard.month_label(nxt)} Visa Bulletin isn't in yet. Check for it, or download the "
                       "PDF from travel.state.gov and upload it on Enter a bulletin.")
            kind = "warn"

        def actions(c):
            label = "Stop tracking" if c.active else "Track again"
            return (f"<form method='post' action='/client/{_e(c.id)}/toggle'>{self._hidden()}"
                    f"<button class='link'>{label}</button></form>")

        check = (f"<form method='post' action='/check'>{self._hidden()}"
                 "<button>Check for a new bulletin</button></form>")
        body = dashboard.dashboard(analysis, inactive, actions, check)
        if not analysis:
            names = "".join(f"<li>{_e(c.name)} · {_e(c.category)} · {c.priority_date}</li>"
                            for c in self.store.list_clients())
            body += self.panel("Clients", f"<ul>{names}</ul>" if names else "<p class='empty'>No clients yet.</p>")
        body += (f"<section class='panel'><details class='add'><summary>Add a client</summary>"
                 f"{self.client_form()}</details></section>")
        return self.page(f"{self.s.office_name}: priority dates", body, message, "clients", kind)

    def bulletin_form(self, month: str | None = None, message="") -> str:
        today = date.today()
        month = month_key(month or f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}")
        current = self.store.get_bulletin(month)
        base = current or previous_bulletin(self.store, month)
        note = ("Editing the saved bulletin." if current else
                f"Prefilled from {base.month}; change only the cells that moved." if base else "Blank form.")
        countries = ["ROW", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"]
        upload = self.panel("Upload the bulletin PDF", (
            f"<form method='post' action='/bulletin/pdf' enctype='multipart/form-data' class='filters'>{self._hidden()}"
            "<input type='file' name='pdf' accept='application/pdf' required> <button>Upload and check</button></form>"
            "<p class='muted small'>Download it from travel.state.gov. The month is read from the PDF, and the tracker "
            "compares it with last month and sends the usual alerts.</p>"))
        parts = [f"<section class='panel'><div class='head'><h2>Or type the dates</h2></div><div class='body'>",
                 f"<form method='get' action='/bulletin' class='filters' style='padding-top:12px'><label>Month <input name='month' value='{month}' "
                 f"pattern='\\d{{4}}-\\d{{2}}'></label> <button class='plain'>Open</button></form>",
                 f"<p class='muted small'>{note} Enter dates as YYYY-MM-DD, or C for current, U for unavailable. "
                 "Leave blank if the bulletin has no entry.</p>",
                 f"<form method='post' action='/bulletin'>{self._hidden()}<input type='hidden' name='month' value='{month}'>"]
        for chart in CHARTS:
            parts.append(f"<h3 style='margin-top:18px'>{CHART_LABELS[chart]}</h3><div class='scroll'><table><tr><th></th>"
                         + "".join(f"<th>{_e(c)}</th>" for c in countries) + "</tr>")
            for cat in CATEGORIES:
                cells = []
                for country in countries:
                    val = base.chart(chart).get(cat, {}).get(country) if base else None
                    cells.append(f"<td><input name='{chart}|{cat}|{country}' value='{_e(cutoff_str(val) if val else '')}'></td>")
                parts.append(f"<tr><th>{cat}</th>{''.join(cells)}</tr>")
            parts.append("</table></div>")
        fam = (current.uscis_family_chart if current else None) or ""
        emp = (current.uscis_employment_chart if current else None) or ""
        opts = {"": "Not confirmed (use office default)", **CHART_LABELS}

        def sel(name, chosen):
            return f"<select name='{name}'>" + "".join(
                f"<option value='{k}'{' selected' if k == chosen else ''}>{v}</option>" for k, v in opts.items()) + "</select>"

        parts.append("<h3 style='margin-top:18px'>Chart USCIS accepts for I-485 this month</h3><p class='muted small'>From "
                     "uscis.gov/visabulletininfo.</p><div class='form-grid'>"
                     f"<label>Family{sel('uscis_family_chart', fam)}</label>"
                     f"<label>Employment{sel('uscis_employment_chart', emp)}</label></div>"
                     "<p><button>Save bulletin</button></p></form></div></section>")
        return self.page("Enter a Visa Bulletin", upload + "".join(parts), message, "bulletin")

    def save_bulletin(self, form: dict) -> str:
        data = {"month": form["month"], "source": "manual entry",
                "uscis_family_chart": form.get("uscis_family_chart") or None,
                "uscis_employment_chart": form.get("uscis_employment_chart") or None,
                "final_action": {}, "dates_for_filing": {}}
        for key, value in form.items():
            if key.count("|") == 2 and value.strip():
                chart, cat, country = key.split("|")
                if chart in CHARTS:
                    data[chart].setdefault(cat, {})[country] = value.strip()
        b = Bulletin.from_dict(data)
        self.store.save_bulletin(b)
        return b.month

    def report(self) -> str:
        out = tracker.current_report(self.store, self.s)
        if not out:
            return self.page("Report", self.panel("Report", "<p>No bulletin on file yet.</p>"), active="report")
        return self.page("Report", self.panel("Monthly report", render.to_html(out[1])), active="report")

    def handle(self, method: str, path: str, form: dict) -> tuple[int, str, str | None]:
        """Returns (status, html, redirect)."""
        parts = [p for p in urlparse(path).path.split("/") if p]
        query = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        if method == "POST" and form.get("token") != self.token:
            return 403, self.page("Expired form", "<p>Reload the page and try again.</p>"), None
        with self.lock:
            try:
                if method == "GET":
                    if not parts:
                        return 200, self.home(query.get("msg", "")), None
                    if parts == ["bulletin"]:
                        return 200, self.bulletin_form(query.get("month"), query.get("msg", "")), None
                    if parts == ["report"]:
                        return 200, self.report(), None
                    if len(parts) == 2 and parts[0] == "client":
                        c = self.store.get_client(parts[1])
                        if c:
                            return 200, self.page(f"Edit {c.name}", self.panel(f"Edit {c.name}", self.client_form(c))), None
                    return 404, self.page("Not found", ""), None
                if parts == ["client"] or (len(parts) == 2 and parts[0] == "client"):
                    d = {k: form.get(k, "") for k in ("name", "category", "chargeability", "priority_date",
                                                        "beneficiary_dob", "case_type", "receipt_number",
                                                        "responsible_email", "notes")}
                    if len(parts) == 2:
                        old = self.store.get_client(parts[1])
                        d.update(id=parts[1], active=old.active if old else True, external_id=old.external_id if old else "")
                    c = self.store.save_client(Client.from_dict(d))
                    return 303, "", f"/?msg=Saved {c.name}"
                if len(parts) == 3 and parts[0] == "client" and parts[2] == "toggle":
                    c = self.store.get_client(parts[1])
                    if c:
                        c.active = not c.active
                        self.store.save_client(c)
                    return 303, "", "/"
                if parts == ["bulletin", "pdf"]:
                    from .bulletin import parse_bulletin_pdf
                    upload = form.get("pdf")
                    if not isinstance(upload, tuple):
                        raise ValueError("Choose a PDF file first.")
                    name, data = upload
                    b = parse_bulletin_pdf(data, source=f"upload:{name}")
                    stored = self.store.get_bulletin(b.month)
                    if stored:
                        b.uscis_family_chart = stored.uscis_family_chart
                        b.uscis_employment_chart = stored.uscis_employment_chart
                    self.store.save_bulletin(b)
                    result = tracker.check(self.store, tracker.StoredSource(self.store), self.s,
                                           tracker.notifiers_for(self.s), month=b.month)
                    return 303, "", f"/?msg=Read the {b.month} bulletin from {name}. {result.summary}"
                if parts == ["bulletin"]:
                    month = self.save_bulletin(form)
                    return 303, "", f"/bulletin?month={month}&msg=Saved the {month} bulletin"
                if parts == ["check"]:
                    source = tracker.source_for(self.s, self.store)
                    result = tracker.check(self.store, source, self.s, tracker.notifiers_for(self.s))
                    return 303, "", f"/?msg={result.summary}"
                return 404, self.page("Not found", ""), None
            except Exception as e:      # show the problem on the page instead of a dropped connection
                return 400, self.page("Couldn't do that", f"<p>{_e(e)}</p><p><a href='javascript:history.back()'>Go back</a></p>"), None


def _multipart(content_type: str, body: bytes) -> dict:
    """Text fields as strings, files as (filename, bytes)."""
    from email.parser import BytesParser
    from email.policy import HTTP

    msg = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {content_type}\r\n\r\n".encode() + body)
    form = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b""
        form[name] = (filename, data) if filename is not None else data.decode("utf-8", "replace")
    return form


def make_handler(app: App, port: int):
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _respond(self, method):
            if self.headers.get("Host") not in allowed:
                self.send_error(403)
                return
            form = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > 20_000_000:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("multipart/form-data"):
                    form = _multipart(ctype, body)
                else:
                    form = {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
            status, body, redirect = app.handle(method, self.path, form)
            if redirect:
                from urllib.parse import quote
                self.send_response(303)
                self.send_header("Location", quote(redirect, safe="/?=&"))
                self.end_headers()
                return
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._respond("GET")

        def do_POST(self):
            self._respond("POST")

        def log_message(self, *args):
            pass

    return Handler


def serve(settings, port: int = 8765, open_browser: bool = True):
    app = App(settings)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    url = f"http://localhost:{port}/"
    print(f"Open {url} (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
