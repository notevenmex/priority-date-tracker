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

from . import render, tracker
from .categories import CATEGORIES, COUNTRIES
from .evaluate import IS_CURRENT
from .models import CHART_LABELS, CHARTS, Bulletin, Client, cutoff_label, cutoff_str, month_key
from .stores import previous_bulletin

CSS = """
:root{--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--line:#ddddd6;--accent:#1f5f8b;--ok:#2e7d32;--warn:#a15c00}
@media (prefers-color-scheme:dark){:root{--bg:#1b1b1a;--fg:#ececea;--muted:#a0a09a;--line:#3a3a37;--accent:#7fb3dc;--ok:#7cc47f;--warn:#e0a54d}}
body{font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:1100px;padding:16px}
a{color:var(--accent)} h1{font-size:22px} h2{font-size:17px;margin-top:28px}
table{border-collapse:collapse;width:100%;font-size:14px} th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600} .ok{color:var(--ok);font-weight:600} .warn{color:var(--warn);font-weight:600}
form.inline{display:inline} input,select,textarea{font:inherit;padding:4px 6px;background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:4px}
button{font:inherit;padding:6px 12px;border-radius:4px;border:1px solid var(--accent);background:var(--accent);color:var(--bg);cursor:pointer}
button.plain{background:transparent;color:var(--accent)} .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.grid label{display:flex;flex-direction:column;gap:2px;color:var(--muted);font-size:13px} .note{color:var(--muted);font-size:13px}
.wrap{overflow-x:auto} td input{width:92px} .msg{padding:8px 12px;border:1px solid var(--line);border-radius:6px}
"""

STATUS_CLASS = {IS_CURRENT: "ok"}


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


class App:
    def __init__(self, settings):
        self.s = settings
        self.store = tracker.store_for(settings)
        self.token = secrets.token_urlsafe(16)
        self.lock = threading.Lock()

    def page(self, title: str, body: str, message: str = "") -> str:
        msg = f'<p class="msg">{_e(message)}</p>' if message else ""
        return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
                f"content='width=device-width,initial-scale=1'><title>{_e(title)}</title><style>{CSS}</style>"
                f"</head><body><p class='note'><a href='/'>Clients</a> · <a href='/bulletin'>Enter a bulletin</a> · "
                f"<a href='/report'>Full report</a></p><h1>{_e(title)}</h1>{msg}{body}</body></html>")

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

        return (f'<form method="post" action="{action}">{self._hidden()}<div class="grid">'
                + field("Client name", "name", required=True)
                + f'<label>Category{self._select("category", CATEGORIES, v.get("category", "F2A"))}</label>'
                + f'<label>Chargeability{self._select("chargeability", COUNTRIES, v.get("chargeability", "ROW"))}</label>'
                + field("Priority date", "priority_date", "date", True)
                + field("Beneficiary date of birth (optional)", "beneficiary_dob", "date")
                + field("Case type", "case_type") + field("Receipt number", "receipt_number")
                + field("Responsible attorney email", "responsible_email", "email")
                + f'<label>Notes<textarea name="notes" rows="2">{_e(v.get("notes") or "")}</textarea></label>'
                + "</div><p><button>Save client</button></p></form>")

    def home(self, message="") -> str:
        months = self.store.bulletin_months()
        latest = self.store.get_bulletin(months[-1]) if months else None
        rows = {}
        if latest:
            analysis = tracker.analyze(self.store, self.s, latest)
            rows = {r.client.id: r for r in analysis.rows}
        head = ("<tr><th>Client</th><th>Category</th><th>Priority date</th><th>Final Action</th>"
                "<th>Dates for Filing</th><th>I-485 open</th><th></th></tr>")
        body = []
        for c in self.store.list_clients(include_inactive=True):
            r = rows.get(c.id)
            if r and c.active:
                fa = f'<span class="{STATUS_CLASS.get(r.final_action, "")}">{_e(render.STATUS_LABELS[r.final_action])}</span>' \
                     f'<br><span class="note">{_e(cutoff_label(r.cutoffs["final_action"]))}</span>'
                df = f'<span class="{STATUS_CLASS.get(r.dates_for_filing, "")}">{_e(render.STATUS_LABELS[r.dates_for_filing])}</span>' \
                     f'<br><span class="note">{_e(cutoff_label(r.cutoffs["dates_for_filing"]))}</span>'
                i485 = '<span class="ok">Yes</span>' if r.can_file_i485 else "No"
            else:
                fa = df = i485 = '<span class="note">inactive</span>' if not c.active else "–"
            toggle = "Stop tracking" if c.active else "Track again"
            body.append(
                f"<tr><td><a href='/client/{_e(c.id)}'>{_e(c.name)}</a><br><span class='note'>{_e(c.case_type)}</span></td>"
                f"<td>{_e(c.category)} · {_e(COUNTRIES[c.chargeability])}</td><td>{c.priority_date:%b %d, %Y}</td>"
                f"<td>{fa}</td><td>{df}</td><td>{i485}</td><td><form class='inline' method='post' "
                f"action='/client/{_e(c.id)}/toggle'>{self._hidden()}<button class='plain'>{toggle}</button></form></td></tr>")
        bulletin_note = (f"Compared against the <b>{_e(latest.month)}</b> bulletin." if latest
                         else "No bulletin on file yet. Check for one or enter it by hand.")
        nxt = tracker.next_month(date.today())
        if (self.s.reminder_day and date.today().day >= self.s.reminder_day
                and nxt not in self.store.bulletin_months()):
            wanted = nxt
            message = message or (f"The {wanted} Visa Bulletin isn't in yet. Click 'Check for a new bulletin', "
                                  "or download the PDF from travel.state.gov and upload it on 'Enter a bulletin'.")
        check = (f"<form class='inline' method='post' action='/check'>{self._hidden()}"
                 "<button>Check for a new bulletin</button></form>")
        table = f"<div class='wrap'><table>{head}{''.join(body)}</table></div>" if body else "<p>No clients yet.</p>"
        return self.page(f"{self.s.office_name}: priority dates",
                         f"<p>{bulletin_note} {check}</p>{table}<h2>Add a client</h2>{self.client_form()}", message)

    def bulletin_form(self, month: str | None = None, message="") -> str:
        today = date.today()
        month = month_key(month or f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}")
        current = self.store.get_bulletin(month)
        base = current or previous_bulletin(self.store, month)
        note = ("Editing the saved bulletin." if current else
                f"Prefilled from {base.month}; change only the cells that moved." if base else "Blank form.")
        countries = ["ROW", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"]
        upload = (f"<h2>Upload the bulletin PDF</h2><form method='post' action='/bulletin/pdf' "
                  f"enctype='multipart/form-data'>{self._hidden()}<input type='file' name='pdf' accept='application/pdf' "
                  "required> <button>Upload and check</button></form><p class='note'>The month is read from the PDF. "
                  "After upload the tracker compares it with last month and sends the usual alerts.</p>"
                  "<h2>Or type the dates</h2>")
        parts = [upload, f"<form method='get' action='/bulletin'><label>Month <input name='month' value='{month}' "
                 f"pattern='\\d{{4}}-\\d{{2}}'></label> <button class='plain'>Open</button></form>",
                 f"<p class='note'>{note} Enter dates as YYYY-MM-DD, or C for current, U for unavailable. "
                 "Leave blank if the bulletin has no entry.</p>",
                 f"<form method='post' action='/bulletin'>{self._hidden()}<input type='hidden' name='month' value='{month}'>"]
        for chart in CHARTS:
            parts.append(f"<h2>{CHART_LABELS[chart]}</h2><div class='wrap'><table><tr><th></th>"
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

        parts.append("<h2>Chart USCIS accepts for I-485 this month</h2><p class='note'>From "
                     "uscis.gov/visabulletininfo.</p><div class='grid'>"
                     f"<label>Family{sel('uscis_family_chart', fam)}</label>"
                     f"<label>Employment{sel('uscis_employment_chart', emp)}</label></div>"
                     "<p><button>Save bulletin</button></p></form>")
        return self.page("Enter a Visa Bulletin", "".join(parts), message)

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
            return self.page("Report", "<p>No bulletin on file yet.</p>")
        return self.page("Report", render.to_html(out[1]))

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
                            return 200, self.page(f"Edit {c.name}", self.client_form(c)), None
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
